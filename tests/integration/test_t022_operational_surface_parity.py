"""The operational surface has to answer identically on both backends.

SC-004 promises coverage for the repository, and the repository is two implementations of one port.
Audit logging and platform credentials were exercised on SQLite only, so their PostgreSQL
implementations -- separate SQL, separate row factories, separate conflict clauses -- were carried
by nothing. A divergence there is invisible until a deployment on the other backend reads a
different answer from the same call.

These are contract tests through the port, not line exercises: each one states an answer both
implementations owe the caller, and would fail on either backend alone if that backend drifted.

Two known divergences are deliberately *not* asserted here, because asserting current behaviour
would pin a defect rather than a contract, and correcting the behaviour is a repository change
outside a coverage task. Both are recorded in `.handoff/T022-coverage-gate.handoff.md`:

- `log_event` normalizes `level` to upper case on PostgreSQL and stores it verbatim on SQLite, and
  `get_recent_logs` filters the same way, so a level written in one case is unfindable in the other
  on SQLite alone.
- `save_platform_credentials` lower-cases `platform` on PostgreSQL and stores it verbatim on
  SQLite, so `save("Threads")` then `get("threads")` succeeds on one backend and returns None on
  the other.

Every call below therefore uses one consistent casing, which is what production callers do.

Not covered here: `runtime_configs` and `market_lexicons`. The integration fixture applies the
source/observation migration set, which does not create those tables, so their PostgreSQL paths
cannot be reached without widening the fixture's schema -- a change that touches every test using
`repository_case`.
"""

from datetime import datetime, timezone

import pytest


# --- audit logging ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_logged_event_comes_back_with_its_component_details_and_timestamp(repository_case):
    repository = repository_case.repository

    await repository.log_event(
        component="ingress",
        event_type="pass_completed",
        message="One ingress pass finished",
        level="INFO",
        details={"keywords": 10, "geo": "VN"},
    )

    logs = await repository.get_recent_logs(limit=10)

    assert len(logs) == 1
    entry = logs[0]
    assert entry["component"] == "ingress"
    assert entry["event_type"] == "pass_completed"
    assert entry["message"] == "One ingress pass finished"
    assert entry["level"] == "INFO"
    assert entry["details"] == {"keywords": 10, "geo": "VN"}
    assert entry["created_at"], "a log entry with no timestamp cannot be ordered or filtered"


@pytest.mark.asyncio
async def test_logs_are_returned_newest_first_and_the_limit_is_honoured(repository_case):
    """`get_recent_logs` is what an operator reads during an incident; order is the whole value."""
    repository = repository_case.repository

    for index in range(5):
        await repository.log_event(
            component="scheduler",
            event_type="tick",
            message=f"tick {index}",
            level="INFO",
        )

    recent = await repository.get_recent_logs(limit=2)

    assert len(recent) == 2
    assert [entry["message"] for entry in recent] == ["tick 4", "tick 3"]


@pytest.mark.asyncio
async def test_logs_can_be_filtered_by_level_and_by_component(repository_case):
    repository = repository_case.repository

    await repository.log_event(
        component="youtube", event_type="quota", message="quota spent", level="ERROR"
    )
    await repository.log_event(
        component="youtube", event_type="fetch", message="pass ok", level="INFO"
    )
    await repository.log_event(
        component="threads", event_type="fetch", message="pass ok", level="ERROR"
    )

    errors = await repository.get_recent_logs(level="ERROR")
    youtube = await repository.get_recent_logs(component="youtube")
    youtube_errors = await repository.get_recent_logs(level="ERROR", component="youtube")

    assert {entry["component"] for entry in errors} == {"youtube", "threads"}
    assert len(errors) == 2
    assert len(youtube) == 2
    assert len(youtube_errors) == 1
    assert youtube_errors[0]["message"] == "quota spent"


@pytest.mark.asyncio
async def test_an_audit_log_never_stores_the_personal_data_it_was_handed(repository_case):
    """Audit rows outlive the incident that produced them, so they are a durable leak if unfiltered.

    Both backends route the message and the details through the same sanitizer; asserting it on
    one would leave the other free to write the raw value.
    """
    repository = repository_case.repository

    await repository.log_event(
        component="auth",
        event_type="contact_captured",
        message="Reached operator at nguyenvana@example.com",
        level="WARNING",
        details={"phone": "+84 912 345 678"},
    )

    entry = (await repository.get_recent_logs(limit=1))[0]

    assert "nguyenvana@example.com" not in entry["message"]
    assert "912 345 678" not in str(entry["details"])


@pytest.mark.asyncio
async def test_reading_logs_from_an_empty_store_returns_an_empty_list(repository_case):
    assert await repository_case.repository.get_recent_logs(limit=10) == []


# --- platform credentials -----------------------------------------------------------------------

# The column holding the encrypted payload is named differently by each schema, so a raw-row check
# has to ask each backend for its own column.
CREDENTIAL_BLOB_SQLITE = "SELECT encrypted_data FROM platform_credentials WHERE platform = ?"
CREDENTIAL_BLOB_POSTGRES = "SELECT credentials_data FROM platform_credentials WHERE platform = %s"


@pytest.mark.asyncio
async def test_stored_credentials_are_encrypted_at_rest_and_decrypted_on_read(repository_case):
    """The secret must not be readable in the row, and must be readable through the port."""
    repository = repository_case.repository
    secret = "token-value-that-must-not-appear-in-the-row"

    await repository.save_platform_credentials(
        platform="threads",
        auth_type="oauth",
        credentials_data={"access_token": secret},
        expires_at=datetime.now(timezone.utc),
    )

    stored = await repository.get_platform_credentials("threads")
    assert stored is not None
    assert stored["credentials_data"]["access_token"] == secret
    assert stored["auth_type"] == "oauth"
    assert stored["is_active"] is True

    row = repository_case.query_one(
        CREDENTIAL_BLOB_SQLITE, CREDENTIAL_BLOB_POSTGRES, ("threads",)
    )
    assert secret not in str(row[0]), "the credential is stored in clear text"


@pytest.mark.asyncio
async def test_saving_credentials_for_one_platform_twice_replaces_them(repository_case):
    """Re-authentication is routine, and it must refresh the row rather than accumulate rows."""
    repository = repository_case.repository

    await repository.save_platform_credentials(
        platform="threads", auth_type="oauth", credentials_data={"access_token": "first"}
    )
    await repository.save_platform_credentials(
        platform="threads", auth_type="oauth", credentials_data={"access_token": "second"}
    )

    listed = await repository.list_platform_credentials()
    stored = await repository.get_platform_credentials("threads")

    assert len([row for row in listed if row["platform"] == "threads"]) == 1
    assert stored["credentials_data"]["access_token"] == "second"


@pytest.mark.asyncio
async def test_listed_credentials_never_carry_the_secret(repository_case):
    """The listing answers "what is connected", which no caller needs the token to know."""
    repository = repository_case.repository
    await repository.save_platform_credentials(
        platform="threads", auth_type="oauth", credentials_data={"access_token": "listed-secret"}
    )

    listed = await repository.list_platform_credentials()

    assert listed, "a saved credential did not appear in the listing"
    assert "listed-secret" not in str(listed)
    assert {row["platform"] for row in listed} == {"threads"}


@pytest.mark.asyncio
async def test_two_platforms_are_stored_and_listed_independently(repository_case):
    repository = repository_case.repository

    await repository.save_platform_credentials(
        platform="threads", auth_type="oauth", credentials_data={"access_token": "t"}
    )
    await repository.save_platform_credentials(
        platform="instagram", auth_type="oauth", credentials_data={"access_token": "i"}
    )

    listed = await repository.list_platform_credentials()

    assert {row["platform"] for row in listed} == {"threads", "instagram"}
    threads = await repository.get_platform_credentials("threads")
    instagram = await repository.get_platform_credentials("instagram")
    assert threads["credentials_data"]["access_token"] == "t"
    assert instagram["credentials_data"]["access_token"] == "i"


@pytest.mark.asyncio
async def test_deleting_credentials_reports_whether_anything_was_removed(repository_case):
    """The boolean is the only way a caller learns it cleared a platform that was never connected."""
    repository = repository_case.repository
    await repository.save_platform_credentials(
        platform="threads", auth_type="oauth", credentials_data={"access_token": "x"}
    )

    assert await repository.delete_platform_credentials("threads") is True
    assert await repository.delete_platform_credentials("threads") is False
    assert await repository.get_platform_credentials("threads") is None


@pytest.mark.asyncio
async def test_credentials_for_an_unconnected_platform_read_as_none(repository_case):
    assert await repository_case.repository.get_platform_credentials("tiktok") is None


@pytest.mark.asyncio
async def test_listing_credentials_with_nothing_connected_returns_an_empty_list(repository_case):
    assert await repository_case.repository.list_platform_credentials() == []
