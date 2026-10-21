"""Market listening must never ingest the operator's own connected accounts.

An authenticated connector can read two surfaces: the public one that demand analysis is about,
and the account's own timeline. These tests pin the three defences: the connector declares which
surface its feed belongs to, the registry refuses to read an account feed during a public pass,
and whatever still arrives is matched against the operator's identities and dropped.
"""

import json
from typing import List
from unittest.mock import AsyncMock

import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.self_content import SelfIdentity, is_self_authored, partition_self_authored
from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType, Timeframe
from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.infrastructure.auth.self_identity import SelfIdentityRegistry, signal_platforms_for
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry


def _signal(platform=PlatformType.THREADS, title="post", url=None, **metadata) -> TrendSignal:
    return TrendSignal(
        platform=platform,
        raw_title=title,
        metric_value=10.0,
        geo_code=GeoCode.VN,
        source_url=url,
        metadata=metadata,
    )


# --- Domain: recognising own content ------------------------------------------------------------

def test_matches_own_account_by_username_metadata():
    identity = SelfIdentity(platform="threads", username="own.account")
    assert is_self_authored(_signal(username="own.account"), [identity])
    assert is_self_authored(_signal(username="@Own.Account"), [identity])
    assert not is_self_authored(_signal(username="someone.else"), [identity])


def test_matches_own_account_by_numeric_id_when_the_handle_is_unknown():
    """A browser session knows its numeric account id but not always its handle."""
    identity = SelfIdentity(platform="threads", account_id="1000000000001")
    assert is_self_authored(_signal(user_id="1000000000001"), [identity])
    assert not is_self_authored(_signal(user_id="2000000000002"), [identity])


def test_matches_own_account_from_the_post_url():
    identity = SelfIdentity(platform="threads", username="own.account")
    assert is_self_authored(_signal(url="https://www.threads.net/@own.account/post/DaH1iwmk3oa"), [identity])
    assert not is_self_authored(_signal(url="https://www.threads.net/@other/post/DaH1iwmk3oa"), [identity])

    ig = SelfIdentity(platform="reels", username="own.account")
    assert is_self_authored(
        _signal(platform=PlatformType.REELS, url="https://www.instagram.com/own.account/reel/abc/"), [ig]
    )


def test_identity_never_leaks_across_platforms():
    identity = SelfIdentity(platform="threads", username="own.account")
    assert not is_self_authored(_signal(platform=PlatformType.TIKTOK, username="own.account"), [identity])


def test_partition_preserves_order_on_both_sides():
    identity = SelfIdentity(platform="threads", username="me")
    signals = [_signal(username="a"), _signal(username="me"), _signal(username="b")]
    public, own = partition_self_authored(signals, [identity])
    assert [s.metadata["username"] for s in public] == ["a", "b"]
    assert [s.metadata["username"] for s in own] == ["me"]


# --- Identity discovery -------------------------------------------------------------------------

def test_one_instagram_login_owns_the_reels_surface_too():
    assert set(signal_platforms_for("instagram_browser")) == {"instagram", "reels"}
    assert set(signal_platforms_for("threads_browser")) == {"threads"}


@pytest.mark.asyncio
async def test_identity_discovered_from_a_browser_session_cookie():
    repo = AsyncMock()
    repo.get_runtime_config.return_value = None
    repo.list_platform_credentials.return_value = [{"platform": "threads_browser"}]
    repo.get_platform_credentials.return_value = {
        "platform": "threads_browser",
        "credentials_data": {"cookies": [{"name": "ds_user_id", "value": "1000000000001"}], "origins": []},
    }

    identities = await SelfIdentityRegistry(repo).load()
    assert [i.normalized_account_id for i in identities] == ["1000000000001"]
    assert identities[0].platform == "threads"
    assert identities[0].source == "session_cookie"


@pytest.mark.asyncio
async def test_explicit_runtime_config_covers_what_no_api_reports():
    repo = AsyncMock()
    repo.get_runtime_config.return_value = json.dumps({"threads": ["own.account"], "tiktok": ["own.account"]})
    repo.list_platform_credentials.return_value = []

    identities = await SelfIdentityRegistry(repo).load()
    by_platform = {i.platform: i.normalized_username for i in identities}
    assert by_platform == {"threads": "own.account", "tiktok": "own.account"}


# --- Registry: routing and the guard ------------------------------------------------------------

class _AccountFeedPlugin(IConnectorPlugin):
    """Stands in for Threads and Reels: its feed is the authenticated account's own."""

    def __init__(self, own_username="own.account"):
        self.fetch_scopes: List[IngressScope] = []
        self.search_calls: List[List[str]] = []
        self._own_username = own_username

    @property
    def platform(self) -> PlatformType:
        return PlatformType.THREADS

    @property
    def name(self) -> str:
        return "Account Feed Plugin"

    @property
    def default_feed_scope(self) -> IngressScope:
        return IngressScope.OWN_PROFILE

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50,
                            scope=IngressScope.PUBLIC_MARKET) -> List[TrendSignal]:
        self.fetch_scopes.append(scope)
        return [_signal(title="my own post", username=self._own_username)]

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H,
                             limit=20) -> List[TrendSignal]:
        self.search_calls.append(list(keywords))
        # A public keyword probe can still surface the operator's own post on that keyword.
        return [
            _signal(title="market post", username="stranger"),
            _signal(title="my own post about the keyword", username=self._own_username),
        ]


@pytest.mark.asyncio
async def test_public_pass_uses_the_keyword_probe_instead_of_the_account_feed():
    plugin = _AccountFeedPlugin()
    registry = ConnectorPluginRegistry()
    registry.register(plugin)
    registry.register_self_identities([SelfIdentity(platform="threads", username="own.account")])

    signals = await registry.fetch_from_all(scope=IngressScope.PUBLIC_MARKET, seed_keywords=["ai agent"])

    assert plugin.fetch_scopes == [], "The account feed must not be read during a public pass"
    assert plugin.search_calls == [["ai agent"]]
    assert [s.raw_title for s in signals] == ["market post"]
    assert registry.last_pass_report["filtered_out"] == 1


@pytest.mark.asyncio
async def test_public_pass_skips_the_connector_when_there_is_nothing_to_probe_with():
    plugin = _AccountFeedPlugin()
    registry = ConnectorPluginRegistry()
    registry.register(plugin)

    signals = await registry.fetch_from_all(scope=IngressScope.PUBLIC_MARKET, seed_keywords=[])

    assert signals == []
    assert plugin.fetch_scopes == []
    assert registry.last_pass_report["account_scoped_skipped"] == ["Account Feed Plugin"]


@pytest.mark.asyncio
async def test_own_profile_pass_reads_the_account_feed_and_keeps_only_own_content():
    plugin = _AccountFeedPlugin()
    registry = ConnectorPluginRegistry()
    registry.register(plugin)
    registry.register_self_identities([SelfIdentity(platform="threads", username="own.account")])

    signals = await registry.fetch_from_all(scope=IngressScope.OWN_PROFILE)

    assert plugin.fetch_scopes == [IngressScope.OWN_PROFILE]
    assert [s.raw_title for s in signals] == ["my own post"]


@pytest.mark.asyncio
async def test_keyword_search_across_all_is_guarded_too():
    plugin = _AccountFeedPlugin()
    registry = ConnectorPluginRegistry()
    registry.register(plugin)
    registry.register_self_identities([SelfIdentity(platform="threads", username="own.account")])

    signals = await registry.search_across_all(keywords=["ai agent"])

    assert [s.raw_title for s in signals] == ["market post"]
    assert registry.last_pass_report["filtered_out"] == 1


@pytest.mark.asyncio
async def test_guard_is_inert_when_no_identity_is_known():
    """Without a known identity nothing is dropped, and the report says so instead of pretending."""
    plugin = _AccountFeedPlugin()
    registry = ConnectorPluginRegistry()
    registry.register(plugin)

    signals = await registry.fetch_from_all(scope=IngressScope.PUBLIC_MARKET, seed_keywords=["ai"])

    assert len(signals) == 2
    assert registry.last_pass_report["self_identities_known"] == 0
    assert registry.last_pass_report["filtered_out"] == 0


# --- The host browser path (Spec 015, research R15) ---------------------------------------------


async def _host_submission(tmp_path, records):
    """Submit one host answer whose records are the given TikTok links, through the real writer."""
    from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from tests.integration.test_host_browser_mission import assignment, staged_answer

    repository = SqliteTrendRepository(str(tmp_path / "host.sqlite"))
    await repository._ensure_schema()
    _store, _workspace, mission, executor = await assignment(repository, tmp_path)
    executor._registry.register_self_identities([SelfIdentity(platform="tiktok", username="sentinel.operator.self")])
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        payload = staged_answer(request)
        template = payload["answers"][0]["records"][0]
        payload["answers"][0]["records"] = [{**template, "source_url": url} for url in records]
        service.stage(request["request_id"], payload)
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
    finally:
        service.close()
    held = await repository.get_mission_signals(mission.id)
    await repository.close()
    return receipt, held


@pytest.mark.asyncio
async def test_a_host_answer_drops_the_operators_own_posts(tmp_path):
    own = "https://www.tiktok.com/@sentinel.operator.self/video/7400000000000000001"
    public = "https://www.tiktok.com/@someone.else/video/7400000000000000002"

    _receipt, held = await _host_submission(tmp_path, [own, public])

    assert [s.source_url for s in held] == ["https://www.tiktok.com/share/video/7400000000000000002"]


@pytest.mark.asyncio
async def test_a_host_receipt_returns_identity_free_links(tmp_path):
    receipt, _held = await _host_submission(tmp_path, ["https://www.tiktok.com/@someone.else/video/7400000000000000002"])

    assert [o["source_url"] for o in receipt["observations"]] == [
        "https://www.tiktok.com/share/video/7400000000000000002"
    ]
    assert "someone.else" not in json.dumps(receipt, default=str)
