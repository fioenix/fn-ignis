"""A caller root's missions read the platform sessions authenticate_* saved in the installation store.

The sessions live in the installation store; the caller store keeps only the caller's own evidence.
Found in the Spec 017 T006 acceptance: Threads and Reels reported AUTH_REQUIRED inside a caller root
while verify_connectors_health, which reads the installation store, reported them HEALTHY.
"""
import asyncio
import json

import pytest

import ignis.config as config
from ignis.infrastructure.caller_storage import CallerStorageScope
from ignis.infrastructure.persistence import create_repository
from ignis.interfaces.mcp import server

AUTH_MANAGERS = ("tiktok_auth_manager", "threads_auth_manager", "instagram_auth_manager",
                 "threads_browser_auth_manager", "instagram_browser_auth_manager")


@pytest.fixture
def caller_root(tmp_path, monkeypatch):
    installation = tmp_path / "installation.sqlite3"
    monkeypatch.setattr(config.settings, "DATABASE_URL", "sqlite:///" + str(installation))
    monkeypatch.setattr(server, "_COMPONENTS", None)
    root = tmp_path / "caller"
    (root / ".fnignis").mkdir(parents=True)
    return installation, CallerStorageScope(root)


@pytest.mark.asyncio
async def test_caller_missions_read_sessions_saved_in_the_installation_store(caller_root):
    installation, scope = caller_root
    await create_repository().save_platform_credentials(
        "threads_browser", "session_cookies", {"cookies": [{"name": "synthetic", "value": "1"}]})
    components = server._init_components(caller_scope=scope)

    for name in AUTH_MANAGERS:
        credentials = components[name]._repository
        assert credentials is not components["repository"], f"{name} reads the caller store"
        assert credentials._db_path == str(installation), f"{name} reads another store"
    record = await components["threads_browser_auth_manager"]._repository.get_platform_credentials(
        "threads_browser")
    assert record is not None and record["credentials_data"]["cookies"][0]["name"] == "synthetic"
    assert await components["repository"].get_platform_credentials("threads_browser") is None


@pytest.mark.asyncio
async def test_caller_self_content_guard_knows_the_signed_in_account(caller_root):
    _, scope = caller_root
    await create_repository().set_runtime_config(
        "self_accounts", json.dumps({"threads": "synthetic_owner"}))
    components = server._init_components(caller_scope=scope)

    identities = await components["vocabulary_synchronizer"].synchronize_self_identities()

    assert [identity.normalized_username for identity in identities] == ["synthetic_owner"]
    assert components["registry"].self_identities == tuple(identities)


def test_caller_never_creates_an_absent_installation_store(caller_root):
    installation, scope = caller_root
    components = server._init_components(caller_scope=scope)

    assert all(components[name]._repository is components["repository"] for name in AUTH_MANAGERS)
    assert components["repository"]._db_path == str(scope.database)
    assert components["registry"]._repository is components["repository"]
    assert not installation.exists()


def test_caller_reuses_the_composed_installation_repository(tmp_path, monkeypatch):
    shared = create_repository("sqlite:///" + str(tmp_path / "installation.sqlite3"))
    monkeypatch.setattr(server, "_COMPONENTS", {"repository": shared})
    root = tmp_path / "caller"
    (root / ".fnignis").mkdir(parents=True)
    components = server._init_components(caller_scope=CallerStorageScope(root))
    assert all(components[name]._repository is shared for name in AUTH_MANAGERS)


@pytest.mark.asyncio
async def test_channel_audit_reads_the_sessions_the_connectors_use(caller_root):
    _, scope = caller_root
    await create_repository().save_platform_credentials(
        "threads_browser", "session_cookies", {"cookies": [{"name": "synthetic", "value": "1"}]})
    components = server._init_components(caller_scope=scope)

    auth_status, _ = await server._collect_channel_context(components)

    assert auth_status["threads"] is True and auth_status["reels"] is False


def test_caller_closes_only_the_installation_repository_it_created(caller_root, tmp_path, monkeypatch):
    installation, scope = caller_root
    installation.touch()
    components = server._compose_caller_scope(scope)
    components["registry"]
    created = components["owned_credential_repository"]
    assert created is components["credential_repository"] and created in components.repositories()

    shared = create_repository("sqlite:///" + str(installation))
    monkeypatch.setattr(server, "_COMPONENTS", {"repository": shared})
    borrowed = server._compose_caller_scope(CallerStorageScope(scope.root))
    borrowed["registry"]
    assert borrowed["credential_repository"] is shared
    assert shared not in borrowed.repositories()


def test_market_analysis_audit_reads_the_installation_sessions(tmp_path, monkeypatch):
    from test_caller_analysis_composition import _prepared_completed_parent

    root, _, _ = _prepared_completed_parent(tmp_path)
    installation = tmp_path / "installation.sqlite3"
    monkeypatch.setattr(config.settings, "DATABASE_URL", "sqlite:///" + str(installation))
    monkeypatch.setattr(server, "_COMPONENTS", None)

    async def exercise():
        await create_repository().save_platform_credentials(
            "instagram_browser", "session_cookies", {"cookies": [{"name": "synthetic", "value": "1"}]})
        components = server._compose_caller_scope(CallerStorageScope(root))
        analysis = await components.analysis()
        auth_status, _ = await server._collect_channel_context(analysis)
        owned = components.repositories()
        for repository in owned:
            await repository.close()
        return components, analysis, auth_status, owned

    components, analysis, auth_status, owned = asyncio.run(exercise())
    assert analysis is not components and auth_status["reels"] is True
    assert analysis["owned_credential_repository"] in owned
