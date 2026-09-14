"""Clearing a stored credential has to erase it on both backends.

`delete_platform_credentials` is what an operator reaches for when a token has leaked, when a
machine is being decommissioned, or as a step of key rotation. All three assume the encrypted
material is gone afterwards.

The contract is written against the table rather than against the reader, because a reader that
filters on `is_active` reports "no credential" for a row that is still sitting there with its
ciphertext intact. Asking `get_platform_credentials()` would therefore pass on an implementation
that only hid the row -- which is exactly the implementation this file was written to catch.
"""

import pytest

# Not a real platform: nothing in the connector registry reads it, so saving one cannot touch a
# live integration, and the payload below is a literal rather than anything loaded from an
# environment file or an existing store.
FIXTURE_PLATFORM = "contract_fixture_platform"
FIXTURE_PAYLOAD = {"access_token": "fixture-not-a-real-token", "note": "test fixture only"}


def _stored_rows(case, platform: str) -> int:
    """Rows physically present for this platform, active or not."""
    row = case.query_one(
        "SELECT COUNT(*) FROM platform_credentials WHERE platform = ?",
        "SELECT COUNT(*) FROM platform_credentials WHERE platform = %s",
        (platform,),
    )
    return int(row[0])


@pytest.mark.asyncio
async def test_clearing_a_credential_removes_the_stored_row(repository_case):
    repository = repository_case.repository

    await repository.save_platform_credentials(
        platform=FIXTURE_PLATFORM,
        auth_type="oauth",
        credentials_data=FIXTURE_PAYLOAD,
    )
    assert _stored_rows(repository_case, FIXTURE_PLATFORM) == 1, (
        f"[{repository_case.name}] the fixture credential was not stored, so the deletion "
        "contract below would prove nothing"
    )

    assert await repository.delete_platform_credentials(FIXTURE_PLATFORM) is True, (
        f"[{repository_case.name}] the first clear reported no change"
    )

    remaining = _stored_rows(repository_case, FIXTURE_PLATFORM)
    assert remaining == 0, (
        f"[{repository_case.name}] {remaining} credential row(s) survive the clear. A row that is "
        "merely marked inactive still holds its encrypted payload, so a leaked token remains "
        "recoverable from a database copy after the operator was told it was deleted."
    )


@pytest.mark.asyncio
async def test_a_cleared_credential_is_invisible_to_readers(repository_case):
    repository = repository_case.repository

    await repository.save_platform_credentials(
        platform=FIXTURE_PLATFORM,
        auth_type="oauth",
        credentials_data=FIXTURE_PAYLOAD,
    )
    await repository.delete_platform_credentials(FIXTURE_PLATFORM)

    assert await repository.get_platform_credentials(FIXTURE_PLATFORM) is None, (
        f"[{repository_case.name}] the cleared credential is still readable"
    )
    listed = {entry.get("platform") for entry in await repository.list_platform_credentials()}
    assert FIXTURE_PLATFORM not in listed, (
        f"[{repository_case.name}] the cleared platform is still listed: {sorted(listed)}"
    )


@pytest.mark.asyncio
async def test_clearing_twice_reports_nothing_to_clear(repository_case):
    """The second call has nothing to act on, and must not claim it did something."""
    repository = repository_case.repository

    await repository.save_platform_credentials(
        platform=FIXTURE_PLATFORM,
        auth_type="oauth",
        credentials_data=FIXTURE_PAYLOAD,
    )
    assert await repository.delete_platform_credentials(FIXTURE_PLATFORM) is True

    assert await repository.delete_platform_credentials(FIXTURE_PLATFORM) is False, (
        f"[{repository_case.name}] a second clear reported success against an empty store. On an "
        "implementation that only flips a flag, the row is still there to update, so this is the "
        "assertion that separates erasure from deactivation."
    )
