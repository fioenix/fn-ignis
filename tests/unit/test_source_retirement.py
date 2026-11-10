"""Spec 022: retired collection is absent without invalidating retained evidence."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.research_workspace import InvalidMissionAuthorizationError
from ignis.interfaces.mcp import server
from tests.unit.test_mission_manifest import _manifest

RETIRED = ('google', 'tiktok_creative_center', 'tiktok_video_grid', 'reels')
REMOVED = {
    'get_tiktok_creative_center_trends', 'get_tiktok_search_suggestions',
    'get_threads_trending_topics', 'get_threads_search_suggestions',
    'authenticate_tiktok', 'authenticate_threads', 'authenticate_instagram',
    'clear_instagram_auth', 'get_instagram_auth_status',
    'clear_threads_auth', 'get_threads_auth_status', 'extract_customer_pain_points',
}


@pytest.mark.asyncio
async def test_catalog_removes_exactly_twelve_and_preserves_survivor_parameters():
    schemas = json.loads(Path('tests/fixtures/source_retirement/survivor-schemas.json').read_text())
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert not tools.keys() & REMOVED
    assert len(tools) == 41
    assert tools.keys() == schemas.keys()
    for name, schema in schemas.items():
        assert tools[name].parameters == schema, name
    for name in REMOVED:
        assert not hasattr(server, name), name
        assert not hasattr(server, 'handle_' + name), name


def components(monkeypatch):
    repo = Mock()
    repo.list_platform_credentials = AsyncMock(return_value=[])
    repo.get_domain_lexicons = AsyncMock(return_value=[])
    repo.get_recent_logs = AsyncMock(return_value=[])
    repo.save_clusters = AsyncMock()
    repo.log_event = AsyncMock()
    monkeypatch.setattr(server, 'create_repository', lambda *a, **kw: repo)
    monkeypatch.setattr(server.settings, 'YOUTUBE_API_KEY', '')
    comp = server._init_components()
    monkeypatch.setattr(server, 'get_components', lambda: comp)
    return comp


def test_composition_has_no_retired_collectors(monkeypatch):
    comp = components(monkeypatch)
    assert set(comp['registry']._plugins).isdisjoint(RETIRED)
    assert {p.platform.value for p in comp['registry'].list_plugins()} == {'threads'}
    assert comp['tiktok_plugin']._auth_manager is None


@pytest.mark.asyncio
async def test_health_never_probes_retired_sources_or_refreshes_their_sessions(monkeypatch):
    comp = components(monkeypatch)
    comp['repository'].list_platform_credentials.return_value = [
        {'platform': p, 'is_active': True, 'expires_at': '2020-01-01T00:00:00+00:00'}
        for p in ('tiktok', 'threads', 'instagram', 'threads_browser', 'instagram_browser')
    ]
    for p in comp['registry'].list_plugins():
        p.is_healthy = AsyncMock(return_value=True)
        if hasattr(p, 'synthetic_probe'):
            p.synthetic_probe = AsyncMock(return_value=[{}])
    result = json.loads(await server.handle_verify_connectors_health())
    assert {c['plugin_id'] for c in result['connectors'].values()}.isdisjoint(RETIRED)
    assert result['credential_refresh_plan'] == []
    assert not [a for a in result['alerts'] if 'EXPIR' in a.get('type', '')]
    diagnostics = json.loads(await server.handle_diagnose_system_health())
    assert set(diagnostics['connectors']).isdisjoint({'google', 'reels', 'tiktok'})


@pytest.mark.asyncio
async def test_comments_do_not_load_a_retired_session(monkeypatch):
    comp = components(monkeypatch)
    auth = Mock(get_storage_state=AsyncMock(side_effect=AssertionError('Session read')))
    comp['tiktok_auth_manager'] = auth
    seen = []

    async def fake_comments(self, **kwargs):
        seen.append(self._auth_manager)
        return [{'comment_id': '1', 'text': 'A public comment', 'likes': 2}]

    monkeypatch.setattr(server.TikTokPlugin, 'fetch_video_comments', fake_comments)
    result = json.loads(await server.handle_get_tiktok_video_comments('https://www.tiktok.com/video/12345'))
    assert result['status'] == 'SUCCESS'
    assert seen == [None]
    auth.get_storage_state.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('surface', RETIRED)
@pytest.mark.parametrize('optional', [False, True])
async def test_stored_manifest_refused_before_resolver_writer_or_mutation(surface, optional):
    manifest = _manifest(required_channels=('youtube',) if optional else (surface,),
                         optional_channels=(surface,) if optional else ())
    before = manifest.to_payload()
    mission = SimpleNamespace(id=uuid4(), surface='ATTENTION', platforms=['youtube'], status='PENDING')
    store = SimpleNamespace(get_mission_manifest=AsyncMock(return_value=manifest))
    repo = SimpleNamespace(get_mission=AsyncMock(return_value=mission), update_mission=AsyncMock())
    registry = SimpleNamespace(resolve_execution_requirements=AsyncMock(return_value={}))
    executor = ExecuteMissionUseCase(repo, registry, None, workspace_store=store)
    executor._build_collection_plan = AsyncMock(return_value={'probes': []})
    with pytest.raises(InvalidMissionAuthorizationError) as error:
        await executor._require_manifest_authority(mission)
    assert error.value.reason_code == 'SURFACE_RETIRED'
    assert error.value.retired_resources == (surface,)
    registry.resolve_execution_requirements.assert_not_awaited()
    repo.update_mission.assert_not_awaited()
    assert manifest.to_payload() == before


@pytest.mark.parametrize('surface', RETIRED)
def test_new_manifest_request_refuses_retired_surface_with_exact_reason(surface):
    payload = _manifest(required_channels=(surface,), optional_channels=()).to_payload()
    with pytest.raises(InvalidMissionAuthorizationError) as error:
        server._mission_manifest_from_payload(payload, created_by='codex')
    assert error.value.reason_code == 'SURFACE_RETIRED'
    assert error.value.retired_resources == (surface,)


@pytest.mark.asyncio
@pytest.mark.parametrize('surface', RETIRED)
@pytest.mark.parametrize('kind', ['attention', 'market'])
async def test_new_mission_use_case_refuses_retired_resource_before_saving(surface, kind):
    from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
    from ignis.domain.research_workspace import MissionOutputType

    store = SimpleNamespace(get_research_workspace=AsyncMock(return_value=object()),
                            create_attention_mission_with_manifest=AsyncMock())
    manifest = _manifest(required_channels=(surface,), optional_channels=(),
                         output_type=(MissionOutputType.ATTENTION_REPORT if kind == 'attention'
                                      else MissionOutputType.MARKET_ANALYSIS),
                         decision_context=None if kind == 'attention' else 'Decide on the MVP')
    with pytest.raises(InvalidMissionAuthorizationError) as error:
        if kind == 'attention':
            await CreateAttentionMissionUseCase(Mock(), store).execute(uuid4(), 'Bounded research', manifest)
        else:
            from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
            from tests.integration.test_dual_surface_journey import COMPLETE_BRIEF
            await ConfirmMarketBriefUseCase(Mock(), store).execute(
                workspace_id=uuid4(), confirmed_by='fixture', manifest=manifest, **COMPLETE_BRIEF,
            )
    assert error.value.reason_code == 'SURFACE_RETIRED'
    store.create_attention_mission_with_manifest.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_scope_refuses_an_optional_retired_surface_before_resolving():
    from ignis.application.use_cases.host_browser_mission import prepare_scope

    from ignis.domain.research_workspace import AuthorityBoundary
    manifest = _manifest(required_channels=('tiktok_video',), optional_channels=('reels',),
                         authority_boundary=AuthorityBoundary(True, True, True, False))
    mission = SimpleNamespace(id=uuid4(), workspace_id=uuid4(), surface='ATTENTION', status='PENDING',
                              platforms=['tiktok'])
    snapshot = SimpleNamespace(mission=mission, manifest=manifest, brief=None)
    executor = ExecuteMissionUseCase(Mock(),
        SimpleNamespace(resolve_execution_requirements=AsyncMock(return_value=dict(
            resources=(), authority=(), quota_costs={}, surface_requirements={}))), None,
        workspace_store=SimpleNamespace(load_mission_evidence_snapshot=AsyncMock(return_value=snapshot)))
    executor._build_collection_plan = AsyncMock(return_value={'probes': []})
    with pytest.raises(InvalidMissionAuthorizationError) as error:
        await prepare_scope(executor, mission.id)
    assert error.value.reason_code == 'SURFACE_RETIRED'
    executor._registry.resolve_execution_requirements.assert_not_awaited()




@pytest.mark.asyncio
async def test_setup_diagnostics_never_probe_rss(monkeypatch):
    from ignis.interfaces.cli import setup_bundle
    from ignis.infrastructure import persistence
    from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin

    repo = SimpleNamespace(get_domain_lexicons=AsyncMock(return_value=[]), close=AsyncMock())
    monkeypatch.setattr(persistence, 'create_repository', lambda: repo)
    monkeypatch.setattr(setup_bundle, '_read_back_research_workspaces', AsyncMock(return_value=[]))
    probe = AsyncMock(return_value=True)
    monkeypatch.setattr(GoogleTrendsRssPlugin, 'is_healthy', probe)
    result = await setup_bundle.run_synthetic_diagnostics()
    probe.assert_not_awaited()
    assert 'google_rss' not in result




def test_sample_generator_does_not_reintroduce_retired_registrations():
    text = Path('scripts/generate_sample_case_studies.py').read_text()
    for name in ('GoogleTrendsRssPlugin', 'TikTokCreativeCenterPlugin', 'ReelsPlugin', 'TikTokPlugin'):
        assert name not in text




@pytest.mark.asyncio
@pytest.mark.parametrize('surface', sorted(RETIRED))
async def test_registry_requirements_refuse_retired_surfaces_before_session_resolution(surface):
    from ignis.domain.research_workspace import RetiredSurfaceError
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

    registry = ConnectorPluginRegistry()
    with pytest.raises(RetiredSurfaceError) as error:
        await registry.resolve_execution_requirements(
            target_platforms=[], allowed_surfaces=('youtube', surface),
            required_surfaces=('youtube',), optional_surfaces=(surface,),
        )
    assert error.value.reason_code == 'SURFACE_RETIRED'
    assert error.value.retired_resources == (surface,)
