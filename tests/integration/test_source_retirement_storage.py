"""Spec 022 keeps historical evidence and credentials readable on both adapters."""

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ignis.application.ports.research_workspace_port import RunJournal
from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.research_workspace import (
    AuthorityBoundary, InvalidMissionAuthorizationError, MissionManifest,
    MissionOutputType, MissionProbeOutcome,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


@pytest.mark.asyncio
@pytest.mark.parametrize('surface,platform,url', [
    ('google', PlatformType.GOOGLE_TRENDS, 'https://trends.google.com/trending/rss?geo=VN'),
    ('tiktok_creative_center', PlatformType.TIKTOK, 'https://ads.tiktok.com/business/creativecenter/hashtag/tea'),
    ('tiktok_video_grid', PlatformType.TIKTOK, 'https://www.tiktok.com/share/video/123456789'),
    ('reels', PlatformType.REELS, 'https://www.instagram.com/reel/ABC123/'),
])
async def test_historical_manifest_observation_outcome_and_session_survive_refusal(
    repository_case, tmp_path, surface, platform, url,
):
    repo = repository_case.repository
    store = WorkspaceRepository(repository=repo)
    creator = CreateResearchWorkspaceUseCase(store)
    root = tmp_path / 'workspace'
    root.mkdir()
    workspace = await creator.confirm(await creator.propose(root, 'Historical sources'), confirmation=True)
    now = datetime.now(timezone.utc)
    mission = ResearchMission(title='Historical tea research', keywords=['tea'], platforms=[platform],
                              geo_code=GeoCode.VN, timeframe='7d', workspace_id=workspace.workspace_id,
                              surface='ATTENTION', status='PENDING')
    manifest = MissionManifest(
        mission_id=mission.id, outcome='Retain the original observations', decision_context=None, required_channels=(surface,),
        optional_channels=(), authority_boundary=AuthorityBoundary(True, True, True, False), quota_budget={},
        output_type=MissionOutputType.COLLECTION_FRAME, stop_conditions=('One pass',),
        analysis_policy='evidence-gated-v1', retention_policy='Until explicit removal',
        created_by='fixture', confirmed_at=now,
    )
    # Historical fixture installation uses storage directly, not new-mission admission.
    await store.create_attention_mission_with_manifest(mission, manifest)
    observation = TrendSignal(platform=platform, raw_title='Historical tea observation', metric_value=7,
                              source_url=url, geo_code=GeoCode.VN, captured_at=now, mission_id=mission.id,
                              metadata={'connector_surface': surface, 'keyword': 'tea'})
    await repo.save_signals([observation])
    run = RunJournal(run_id=uuid4(), mission_id=mission.id, workspace_id=workspace.workspace_id,
                     journal_path=workspace.journal_dir / 'historical.json', sequence=1,
                     status='STARTED', started_at=now)
    await store.record_run_journal(run)
    outcome = MissionProbeOutcome(run_id=run.run_id, platform=platform.value, connector_surface=surface,
                                 status='HEALTHY', signals_collected=1, queried_keywords=('tea',),
                                 query_fingerprint='f' * 64, completed_at=now, note='Historical fixture', collection_plan_digest='p' * 64,
                                 scope_attestation={'keywords': ['tea'], 'geo': 'VN', 'timeframe': '7d'})
    await store.record_probe_outcomes(run.run_id, [outcome])
    await store.record_run_journal(replace(run, status='COMPLETED', completed_at=now))
    # Synthetic data only; tests/conftest.py quarantines the encryption setting.
    await repo.save_platform_credentials('tiktok', 'browser', {'cookies': []})
    before = await store.load_mission_evidence_snapshot(mission.id)
    sessions = await repo.list_platform_credentials()
    counts = repository_case.counts()
    registry = Mock(resolve_execution_requirements=AsyncMock())
    executor = ExecuteMissionUseCase(repo, registry, Mock(), workspace_store=store)
    with pytest.raises(InvalidMissionAuthorizationError) as error:
        await executor.execute(mission.id)
    assert error.value.reason_code == 'SURFACE_RETIRED'
    assert error.value.retired_resources == (surface,)
    registry.resolve_execution_requirements.assert_not_awaited()
    after = await store.load_mission_evidence_snapshot(mission.id)
    assert after == before
    assert repository_case.counts() == counts
    assert await repo.list_platform_credentials() == sessions
    assert (await store.get_mission_manifest(mission.id)).manifest_digest == manifest.manifest_digest
    held = await repo.get_mission_signals(mission.id)
    assert len(held) == 1 and held[0].platform == platform and held[0].metric_value == 7
    outcomes = await store.get_latest_completed_probe_outcomes(mission.id)
    assert len(outcomes) == 1 and outcomes[0].connector_surface == surface
