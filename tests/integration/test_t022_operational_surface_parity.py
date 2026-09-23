"""The operational surface has to answer identically on both backends.

SC-004 promises coverage for the repository, and the repository is two implementations of one port.
Audit logging and platform credentials were exercised on SQLite only, so their PostgreSQL
implementations -- separate SQL, separate row factories, separate conflict clauses -- were carried
by nothing. A divergence there is invisible until a deployment on the other backend reads a
different answer from the same call.

These are contract tests through the port, not line exercises: each one states an answer both
implementations owe the caller, and would fail on either backend alone if that backend drifted.

Caller casing is part of the contract, not a convention the caller is trusted to keep (T038). The
repository port is the boundary, so it normalizes equivalent input the same way on both backends:

- an audit-log `level` is stored upper case, filtered without regard to the caller's casing, and
  read back upper case even from a row written before the rule existed; and
- a credential `platform` is the trimmed lower-case key on save, get, list and delete, and a row
  stored under another casing is still found by it rather than orphaned.

Until T038, PostgreSQL applied both rules and SQLite applied neither, so `save("Threads")` then
`get("threads")` succeeded on one backend and returned None on the other.

Not covered here: `runtime_configs` and `market_lexicons`. The integration fixture applies the
source/observation migration set, which does not create those tables, so their PostgreSQL paths
cannot be reached without widening the fixture's schema -- a change that touches every test using
`repository_case`.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from ignis.domain.exceptions import RepositoryException
from ignis.infrastructure.auth.crypto import encrypt_credentials


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


# Each schema generates its own key and timestamp, so a raw legacy row is written by per-backend
# SQL that binds the same four values.
LEGACY_LOG_SQLITE = (
    "INSERT INTO system_audit_logs (id, component, event_type, message, level, details, created_at)"
    " VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, '{}',"
    " strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')) RETURNING level"
)
LEGACY_LOG_POSTGRES = (
    "INSERT INTO system_audit_logs (component, event_type, message, level)"
    " VALUES (%s, %s, %s, %s) RETURNING level"
)


@pytest.mark.asyncio
async def test_a_level_written_in_lower_case_is_stored_and_returned_upper_case(repository_case):
    repository = repository_case.repository

    await repository.log_event(
        component="youtube", event_type="quota", message="quota low", level="warning"
    )

    entry = (await repository.get_recent_logs(limit=1))[0]
    stored = repository_case.query_one(
        "SELECT level FROM system_audit_logs", "SELECT level FROM system_audit_logs"
    )

    assert entry["level"] == "WARNING"
    assert stored[0] == "WARNING", "the level was not stored in its canonical form"


@pytest.mark.asyncio
async def test_filtering_by_level_does_not_depend_on_the_callers_casing(repository_case):
    """An operator typing `warning` during an incident must see the same rows as `WARNING`."""
    repository = repository_case.repository
    await repository.log_event(
        component="youtube", event_type="quota", message="quota low", level="Warning"
    )
    await repository.log_event(
        component="youtube", event_type="fetch", message="pass ok", level="INFO"
    )

    lower = await repository.get_recent_logs(level="warning")
    upper = await repository.get_recent_logs(level="WARNING")

    assert [entry["message"] for entry in lower] == ["quota low"]
    assert [entry["id"] for entry in lower] == [entry["id"] for entry in upper]


@pytest.mark.asyncio
async def test_a_row_stored_before_the_rule_reads_upper_case_and_is_found_by_its_level(
    repository_case,
):
    """Rows written verbatim by an older build stay in the store; they are read, not rewritten."""
    repository = repository_case.repository
    repository_case.query_one(
        LEGACY_LOG_SQLITE,
        LEGACY_LOG_POSTGRES,
        ("scheduler", "tick", "legacy tick", "error"),
    )

    listed = await repository.get_recent_logs(limit=10)
    filtered = await repository.get_recent_logs(level="ERROR")
    stored = repository_case.query_one(
        "SELECT level FROM system_audit_logs", "SELECT level FROM system_audit_logs"
    )

    assert [entry["level"] for entry in listed] == ["ERROR"]
    assert [entry["message"] for entry in filtered] == ["legacy tick"]
    assert stored[0] == "error", "reading a legacy row must not rewrite it"


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


@pytest.mark.asyncio
async def test_a_platform_saved_in_any_casing_is_one_canonical_key_everywhere(repository_case):
    """`save("Threads")` then `get("threads")` used to succeed on PostgreSQL only."""
    repository = repository_case.repository

    await repository.save_platform_credentials(
        platform=" Threads ", auth_type="oauth", credentials_data={"access_token": "t"}
    )

    for spelling in ("threads", "THREADS", "Threads"):
        stored = await repository.get_platform_credentials(spelling)
        assert stored is not None, f"get({spelling!r}) missed the saved credential"
        assert stored["platform"] == "threads"
        assert stored["credentials_data"]["access_token"] == "t"

    listed = await repository.list_platform_credentials()
    row = repository_case.query_one(
        "SELECT platform FROM platform_credentials", "SELECT platform FROM platform_credentials"
    )
    assert [entry["platform"] for entry in listed] == ["threads"]
    assert row[0] == "threads", "the platform key was not stored in its canonical form"


@pytest.mark.asyncio
async def test_saving_again_under_another_casing_replaces_rather_than_adds(repository_case):
    repository = repository_case.repository

    await repository.save_platform_credentials(
        platform="threads", auth_type="oauth", credentials_data={"access_token": "first"}
    )
    await repository.save_platform_credentials(
        platform="THREADS", auth_type="oauth", credentials_data={"access_token": "second"}
    )

    listed = await repository.list_platform_credentials()
    stored = await repository.get_platform_credentials("Threads")

    assert len(listed) == 1
    assert stored["credentials_data"]["access_token"] == "second"


@pytest.mark.asyncio
async def test_deleting_under_another_casing_erases_the_credential(repository_case):
    """Erasure after a leak must not depend on the operator remembering the stored casing."""
    repository = repository_case.repository
    await repository.save_platform_credentials(
        platform="Threads", auth_type="oauth", credentials_data={"access_token": "x"}
    )

    assert await repository.delete_platform_credentials("ThReAdS") is True
    assert await repository.get_platform_credentials("threads") is None
    assert await repository.delete_platform_credentials("threads") is False
    assert await repository.list_platform_credentials() == []


# A credential row written verbatim by an older SQLite build, or by hand, under a non-canonical
# key. The payload is encrypted the way the port would have encrypted it.
LEGACY_CREDENTIAL_SQLITE = (
    "INSERT INTO platform_credentials"
    " (id, platform, auth_type, encrypted_data, is_active, created_at, updated_at)"
    " VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, datetime('now'), datetime('now'))"
    " RETURNING platform"
)
LEGACY_CREDENTIAL_POSTGRES = (
    "INSERT INTO platform_credentials (platform, auth_type, credentials_data, is_active)"
    " VALUES (%s, %s, %s, %s) RETURNING platform"
)
STORED_PLATFORM_KEYS = "SELECT platform FROM platform_credentials"


def _insert_legacy_credential(
    repository_case, platform: str, token: str, is_active: bool = True
) -> None:
    payload = json.dumps(encrypt_credentials({"access_token": token}))
    repository_case.query_one(
        LEGACY_CREDENTIAL_SQLITE,
        LEGACY_CREDENTIAL_POSTGRES,
        (platform, "oauth", payload, is_active),
    )


def _stored_platform_keys(repository_case) -> list:
    """Stored keys sorted in Python, since the two backends collate mixed case differently."""
    if repository_case.name == "sqlite":
        with sqlite3.connect(repository_case.repository._db_path) as conn:
            rows = conn.execute(STORED_PLATFORM_KEYS).fetchall()
    else:
        with psycopg.connect(repository_case.dsn) as conn:
            rows = conn.execute(STORED_PLATFORM_KEYS).fetchall()
    return sorted(row[0] for row in rows)


@pytest.mark.asyncio
async def test_a_legacy_mixed_case_credential_is_readable_listable_and_erasable(repository_case):
    repository = repository_case.repository
    _insert_legacy_credential(repository_case, "Threads", "legacy")

    stored = await repository.get_platform_credentials("threads")
    listed = await repository.list_platform_credentials()

    assert stored is not None, "a legacy row was orphaned by the canonical key"
    assert stored["platform"] == "threads"
    assert stored["credentials_data"]["access_token"] == "legacy"
    assert [entry["platform"] for entry in listed] == ["threads"]
    assert "legacy" not in str(listed)
    assert _stored_platform_keys(repository_case) == ["Threads"], "a read rewrote the row"

    assert await repository.delete_platform_credentials("threads") is True
    assert _stored_platform_keys(repository_case) == []


@pytest.mark.asyncio
async def test_re_authenticating_over_a_legacy_row_replaces_it_instead_of_duplicating(
    repository_case,
):
    """A second row beside the legacy one would make the platform ambiguous on the next read."""
    repository = repository_case.repository
    _insert_legacy_credential(repository_case, "Threads", "legacy")

    await repository.save_platform_credentials(
        platform="threads", auth_type="oauth", credentials_data={"access_token": "fresh"}
    )

    stored = await repository.get_platform_credentials("threads")
    assert stored["credentials_data"]["access_token"] == "fresh"
    assert _stored_platform_keys(repository_case) == ["threads"]


@pytest.mark.asyncio
async def test_two_legacy_rows_for_one_platform_are_refused_rather_than_merged(repository_case):
    """Picking one of two secrets, or folding them together, would be a guess made for the operator.

    Both reads and writes refuse and name the ambiguity; both rows survive untouched, and delete
    -- the one call whose intent covers every row -- is how the operator resolves it.
    """
    repository = repository_case.repository
    _insert_legacy_credential(repository_case, "Threads", "one")
    _insert_legacy_credential(repository_case, "THREADS", "two")

    with pytest.raises(RepositoryException, match="threads"):
        await repository.get_platform_credentials("threads")
    with pytest.raises(RepositoryException, match="threads"):
        await repository.save_platform_credentials(
            platform="threads", auth_type="oauth", credentials_data={"access_token": "three"}
        )
    assert _stored_platform_keys(repository_case) == ["THREADS", "Threads"]

    assert await repository.delete_platform_credentials("threads") is True
    assert _stored_platform_keys(repository_case) == []
    assert await repository.get_platform_credentials("threads") is None


def _stored_credential_rows(repository_case) -> list:
    """Every stored row as (platform, active, payload), to prove a refusal changed nothing."""
    if repository_case.name == "sqlite":
        with sqlite3.connect(repository_case.repository._db_path) as conn:
            rows = conn.execute(
                "SELECT platform, is_active, encrypted_data FROM platform_credentials"
            ).fetchall()
    else:
        with psycopg.connect(repository_case.dsn) as conn:
            rows = conn.execute(
                "SELECT platform, is_active, credentials_data::text FROM platform_credentials"
            ).fetchall()
    return sorted((platform, bool(active), payload) for platform, active, payload in rows)


@pytest.mark.asyncio
async def test_an_inactive_second_row_still_makes_the_platform_ambiguous(repository_case):
    """Activity is a property of one credential, not a tie-breaker between two of them.

    Filtering by `is_active` before counting let `get` return the active row while `save`
    refused the same pair, so the two calls disagreed about whether the platform was ambiguous.
    """
    repository = repository_case.repository
    _insert_legacy_credential(repository_case, "Threads", "active")
    _insert_legacy_credential(repository_case, "THREADS", "inactive", is_active=False)
    before = _stored_credential_rows(repository_case)

    with pytest.raises(RepositoryException, match="threads"):
        await repository.get_platform_credentials("threads")
    with pytest.raises(RepositoryException, match="threads"):
        await repository.save_platform_credentials(
            platform="threads", auth_type="oauth", credentials_data={"access_token": "new"}
        )
    assert _stored_credential_rows(repository_case) == before, "a refusal changed a stored row"

    assert await repository.delete_platform_credentials("threads") is True
    assert _stored_platform_keys(repository_case) == []


@pytest.mark.asyncio
async def test_a_single_inactive_row_reads_as_not_connected_rather_than_ambiguous(
    repository_case,
):
    _insert_legacy_credential(repository_case, "Threads", "inactive", is_active=False)

    assert await repository_case.repository.get_platform_credentials("threads") is None
    assert _stored_platform_keys(repository_case) == ["Threads"]


# --- the public credential record (T039) --------------------------------------------------------

# The record a caller reads is the port's contract, not whatever columns a backend happens to
# select. Exact key sets, because an extra storage field on one backend is exactly the drift a
# "contains these keys" check lets through.
DETAIL_KEYS = {"platform", "auth_type", "credentials_data", "is_active", "expires_at", "updated_at"}
LIST_KEYS = DETAIL_KEYS - {"credentials_data"}
EXPIRY = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _assert_utc_iso(value) -> None:
    assert isinstance(value, str), f"a timestamp must be an ISO-8601 string, got {type(value)}"
    parsed = datetime.fromisoformat(value)
    assert "T" in value, f"{value!r} is not in ISO-8601 form"
    assert parsed.utcoffset() == timedelta(0), f"{value!r} is not an explicit UTC timestamp"


def _assert_public_record(record: dict, keys: set) -> None:
    assert set(record) == keys
    assert record["platform"] == record["platform"].strip().lower()
    assert isinstance(record["auth_type"], str)
    assert type(record["is_active"]) is bool
    _assert_utc_iso(record["updated_at"])
    if record["expires_at"] is not None:
        _assert_utc_iso(record["expires_at"])


@pytest.mark.asyncio
async def test_a_credential_detail_read_has_exactly_the_public_keys_and_types(repository_case):
    repository = repository_case.repository
    await repository.save_platform_credentials(
        platform="Threads",
        auth_type="oauth",
        credentials_data={"access_token": "detail-secret"},
        expires_at=EXPIRY,
    )

    record = await repository.get_platform_credentials("threads")

    _assert_public_record(record, DETAIL_KEYS)
    assert record["platform"] == "threads"
    assert record["credentials_data"] == {"access_token": "detail-secret"}
    assert record["is_active"] is True
    assert record["expires_at"] == "2026-10-01T12:00:00+00:00"


@pytest.mark.asyncio
async def test_a_credential_listing_has_exactly_the_public_keys_and_never_a_secret(repository_case):
    repository = repository_case.repository
    await repository.save_platform_credentials(
        platform="threads",
        auth_type="oauth",
        credentials_data={"access_token": "list-secret"},
        expires_at=EXPIRY,
    )
    await repository.save_platform_credentials(
        platform="tiktok",
        auth_type="session_cookies",
        credentials_data={"cookies": [{"name": "sid", "value": "list-cookie"}]},
        is_active=False,
    )

    listed = sorted(await repository.list_platform_credentials(), key=lambda r: r["platform"])

    for record in listed:
        _assert_public_record(record, LIST_KEYS)
    assert [(r["platform"], r["is_active"], r["expires_at"]) for r in listed] == [
        ("threads", True, "2026-10-01T12:00:00+00:00"),
        ("tiktok", False, None),
    ]
    assert "list-secret" not in str(listed) and "list-cookie" not in str(listed)


@pytest.mark.asyncio
async def test_a_legacy_row_reads_in_the_public_shape_without_being_rewritten(repository_case):
    """A row an older build wrote keeps its stored timestamp text; only the read is canonical."""
    repository = repository_case.repository
    _insert_legacy_credential(repository_case, "Threads", "legacy")
    before = _stored_credential_rows(repository_case)
    stored_updated = repository_case.query_one(
        "SELECT updated_at FROM platform_credentials",
        "SELECT updated_at::text FROM platform_credentials",
    )[0]

    record = await repository.get_platform_credentials("THREADS")
    listed = await repository.list_platform_credentials()

    _assert_public_record(record, DETAIL_KEYS)
    assert record["credentials_data"] == {"access_token": "legacy"}
    assert [set(r) for r in listed] == [LIST_KEYS]
    _assert_public_record(listed[0], LIST_KEYS)
    assert _stored_credential_rows(repository_case) == before
    assert repository_case.query_one(
        "SELECT updated_at FROM platform_credentials",
        "SELECT updated_at::text FROM platform_credentials",
    )[0] == stored_updated, "reading a legacy row rewrote its timestamp"


@pytest.mark.asyncio
async def test_an_inactive_row_lists_as_inactive_and_reads_as_not_connected(repository_case):
    repository = repository_case.repository
    _insert_legacy_credential(repository_case, "Threads", "inactive", is_active=False)

    listed = await repository.list_platform_credentials()

    assert await repository.get_platform_credentials("threads") is None
    assert len(listed) == 1
    _assert_public_record(listed[0], LIST_KEYS)
    assert listed[0]["is_active"] is False


# --- auth consumers read `credentials_data` only ------------------------------------------------


@pytest.mark.asyncio
async def test_the_oauth_manager_reads_its_token_from_the_public_record(repository_case):
    from ignis.infrastructure.auth.meta_oauth import ThreadsAuthManager

    repository = repository_case.repository
    future = datetime.now(timezone.utc) + timedelta(days=30)
    await repository.save_platform_credentials(
        platform="threads",
        auth_type="oauth2",
        credentials_data={"access_token": "oauth-token", "expires_at": future.isoformat()},
        expires_at=future,
    )

    manager = ThreadsAuthManager(repository)

    assert await manager.is_authenticated() is True
    assert await manager.get_access_token(auto_refresh=False) == "oauth-token"


@pytest.mark.asyncio
async def test_the_browser_session_manager_reads_its_state_from_the_public_record(repository_case):
    from ignis.infrastructure.auth.meta_browser_auth import ThreadsBrowserAuthManager

    repository = repository_case.repository
    state = {"cookies": [{"name": "sessionid", "value": "browser-cookie"}], "origins": []}
    await repository.save_platform_credentials(
        platform="threads_browser",
        auth_type="session_cookies",
        credentials_data=state,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )

    manager = ThreadsBrowserAuthManager(repository)

    assert await manager.get_storage_state() == state
    assert (await manager.get_auth_status())["authenticated"] is True


@pytest.mark.asyncio
async def test_self_identity_reads_the_account_from_the_public_record(repository_case):
    from ignis.infrastructure.auth.self_identity import SelfIdentityRegistry

    repository = repository_case.repository
    await repository.save_platform_credentials(
        platform="threads",
        auth_type="oauth2",
        credentials_data={"access_token": "t", "user_id": "178414"},
    )

    identities = await SelfIdentityRegistry(repository).load(["threads"])

    assert "178414" in {identity.account_id for identity in identities}


@pytest.mark.asyncio
async def test_the_tiktok_manager_reads_its_state_from_the_public_record(repository_case):
    from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager

    repository = repository_case.repository
    state = {"cookies": [{"name": "sessionid", "value": "tiktok-cookie"}]}
    await repository.save_platform_credentials(
        platform="tiktok", auth_type="session_cookies", credentials_data=state
    )

    manager = TikTokAuthManager(repository)

    assert await manager.is_authenticated() is True
    assert await manager.get_storage_state() == state
