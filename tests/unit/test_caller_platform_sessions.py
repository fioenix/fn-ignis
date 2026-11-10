"""A caller root retains installation credentials for identity and historical audit reads.

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

    assert all(name not in components for name in AUTH_MANAGERS)
    credentials = components["credential_repository"]
    assert credentials is not components["repository"]
    assert credentials._db_path == str(installation)
    record = await credentials.get_platform_credentials("threads_browser")
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

    assert components["credential_repository"] is components["repository"]
    assert all(name not in components for name in AUTH_MANAGERS)
    assert components["repository"]._db_path == str(scope.database)
    assert components["registry"]._repository is components["repository"]
    assert not installation.exists()


def test_caller_reuses_the_composed_installation_repository(tmp_path, monkeypatch):
    shared = create_repository("sqlite:///" + str(tmp_path / "installation.sqlite3"))
    monkeypatch.setattr(server, "_COMPONENTS", {"repository": shared})
    root = tmp_path / "caller"
    (root / ".fnignis").mkdir(parents=True)
    components = server._init_components(caller_scope=CallerStorageScope(root))
    assert components["credential_repository"] is shared
    assert all(name not in components for name in AUTH_MANAGERS)


@pytest.mark.asyncio
async def test_channel_audit_reads_the_sessions_the_connectors_use(caller_root):
    _, scope = caller_root
    await create_repository().save_platform_credentials(
        "threads_browser", "session_cookies", {"cookies": [{"name": "synthetic", "value": "1"}]})
    components = server._init_components(caller_scope=scope)

    auth_status, _ = await server._collect_channel_context(components)

    assert auth_status["threads"] is True and auth_status["reels"] is False


@pytest.mark.asyncio
async def test_caller_auth_status_reads_installation_sessions(caller_root, monkeypatch):
    _, scope = caller_root
    await create_repository().save_platform_credentials(
        "threads_browser", "session_cookies", {"cookies": []})
    components = server._init_components(caller_scope=scope)
    monkeypatch.setattr(server, "get_components", lambda: components)

    result = json.loads(await server.handle_get_platform_auth_status())

    assert result["count"] == 1
    assert result["platforms"][0]["platform"] == "threads_browser"
    assert "credentials_data" not in result["platforms"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["threads", "threads_browser", "instagram", "instagram_browser"])
@pytest.mark.parametrize("browser_only", [True, False])
async def test_caller_clear_removes_installation_platform_sessions(
    caller_root, monkeypatch, platform, browser_only
):
    _, scope = caller_root
    base = platform.removesuffix("_browser")
    installation = create_repository()
    await installation.save_platform_credentials(base + "_browser", "session_cookies", {"cookies": []})
    if not browser_only:
        await installation.save_platform_credentials(base, "oauth2", {"access_token": "synthetic"})
    await installation.save_platform_credentials("tiktok", "session_cookies", {"cookies": []})
    components = server._init_components(caller_scope=scope)
    monkeypatch.setattr(server, "get_components", lambda: components)
    assert await components["repository"].get_platform_credentials(base + "_browser") is None

    result = json.loads(await server.handle_clear_platform_auth(platform))

    credentials = components["credential_repository"]
    assert await credentials.get_platform_credentials(base + "_browser") is None
    assert await credentials.get_platform_credentials(base) is None
    assert result["cleared"] is True
    assert await credentials.get_platform_credentials("tiktok") is not None
    assert json.loads(await server.handle_clear_platform_auth(platform))["cleared"] is False


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
