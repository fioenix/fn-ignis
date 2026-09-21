"""The two surfaces end to end, against a real database and the real mission ingress path.

Only the external connectors are replaced. Persistence, clustering, evidence attachment and
analysis are the production code, because the claims under test -- that Attention never emits an
Opportunity Index, that Market cannot probe without a confirmed Brief, and that every Market
citation reaches a canonical observation -- are claims about what those paths actually do.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_attention_mission import (
    CreateAttentionMissionUseCase,
)
from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus, QualityScorecard
from ignis.domain.research_workspace import (
    IncompleteMarketBriefError,
    MissionLineage,
    ResearchSurface,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

COMPLETE_BRIEF = {
    "decision": "Should we build a VN customer service assistant for fashion retailers?",
    "target_user": "VN fashion retailers answering their own support inbox",
    "problem": "Support replies take hours and the sale is lost before anyone answers",
    "geo": "VN",
    "timeframe": "30d",
    "hypothesis": "VN fashion retailers will pay for sub-minute automated support replies",
    "falsifiers": ["No retailer names reply latency among their top three costs"],
}


class StubRegistry:
    """Two connector surfaces on one platform, which is the case platform health used to hide."""

    def __init__(self, signals):
        self._signals = signals

    async def search_across_all(self, **_kwargs):
        return [
            TrendSignal(
                platform=s.platform,
                raw_title=s.raw_title,
                metric_value=s.metric_value,
                growth_velocity=s.growth_velocity,
                source_url=s.source_url,
                geo_code=s.geo_code,
                metadata=dict(s.metadata),
                captured_at=s.captured_at,
            )
            for s in self._signals
        ]


def _probe_signals():
    now = datetime.now(timezone.utc)
    return [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="ai customer service",
            metric_value=88.0,
            growth_velocity=14.0,
            source_url="https://trends.google.com/trends/explore?q=ai+customer+service",
            geo_code=GeoCode.VN,
            metadata={"keyword": "ai customer service", "connector_surface": "google_rss"},
            captured_at=now,
        ),
        TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title="AI customer service cho shop thoi trang",
            metric_value=42000.0,
            growth_velocity=9.0,
            source_url="https://www.tiktok.com/@shop/video/7300000000000000001",
            geo_code=GeoCode.VN,
            metadata={
                "keyword": "ai customer service",
                "connector_surface": "tiktok",
                "comments": 80,
            },
            captured_at=now,
        ),
    ]


async def _workspace(repository, host_workspace, name="AI customer service"):
    store = WorkspaceRepository(repository=repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    proposal = await use_case.propose(host_workspace, name)
    return store, await use_case.confirm(proposal, confirmation=True)


def _executor(repository, store):
    return ExecuteMissionUseCase(
        repository=repository,
        registry=StubRegistry(_probe_signals()),
        clusterer=SemanticClusterer(),
        workspace_store=store,
    )


@pytest.fixture
def host_workspace(tmp_path):
    root = tmp_path / "host-project"
    root.mkdir()
    return root


# --- User Story 2: Attention ------------------------------------------------

@pytest.mark.asyncio
async def test_attention_runs_without_a_hypothesis_and_cites_real_observations(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="What is gaining attention in VN customer service",
        seed="ai customer service",
        geo=GeoCode.VN,
        timeframe="7d",
    )
    assert mission.surface == ResearchSurface.ATTENTION.value
    assert mission.brief_revision_id is None

    result = await _executor(repository, store).execute(mission.id)
    assert result["status"] == "COMPLETED"

    signals = await repository.get_mission_signals(mission.id)
    assert signals and all(s.observation_id for s in signals)

    stored = await repository.get_mission(mission.id)
    report = StrategicMarketReasoner().analyze_mission(
        mission=stored,
        signals=signals,
        clusters=[],
        scorecard=QualityScorecard(),
        connector_health={
            "google_rss": {"platform": "google", "circuit_state": "CLOSED"},
            "tiktok": {"platform": "tiktok", "circuit_state": "CLOSED"},
        },
    )

    assert report.surface == ResearchSurface.ATTENTION.value
    # The index is not computed at all, not computed and then hidden.
    assert report.market_opportunities == []
    assert report.market_brief is None
    # Momentum, freshness and coverage stay visible, and every citation reaches an observation.
    assert report.channel_summaries
    cited = [c for ch in report.channel_summaries if (c := ch.top_citation)]
    assert cited and all(c.observation_id for c in cited)


@pytest.mark.asyncio
async def test_two_surfaces_of_one_platform_are_reported_separately(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="VN customer service attention",
        seed="ai customer service",
    )
    await _executor(repository, store).execute(mission.id)

    signals = await repository.get_mission_signals(mission.id)
    stored = await repository.get_mission(mission.id)

    report = StrategicMarketReasoner().analyze_mission(
        mission=stored,
        signals=signals,
        clusters=[],
        scorecard=QualityScorecard(),
        connector_health={
            "google_rss": {"platform": "google", "circuit_state": "CLOSED"},
            # The video grid answered; the comments probe did not.
            "tiktok": {"platform": "tiktok", "circuit_state": "CLOSED"},
            "tiktok_comments": {
                "platform": "tiktok",
                "circuit_state": "OPEN",
                "consecutive_failures": 4,
            },
        },
    )

    tiktok_rows = {
        ch.connector_surface: ch
        for ch in report.channel_summaries
        if ch.platform == PlatformType.TIKTOK
    }
    assert set(tiktok_rows) == {"tiktok", "tiktok_comments"}
    assert tiktok_rows["tiktok"].status is ChannelHealthStatus.HEALTHY
    # The failure is visible rather than averaged away behind the healthy grid.
    assert tiktok_rows["tiktok_comments"].status is ChannelHealthStatus.DEGRADED
    assert tiktok_rows["tiktok_comments"].signals_count == 0


# --- User Story 3: Market ---------------------------------------------------

@pytest.mark.asyncio
async def test_an_incomplete_brief_is_refused_and_writes_nothing(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    incomplete = {**COMPLETE_BRIEF, "hypothesis": "", "falsifiers": []}
    with pytest.raises(IncompleteMarketBriefError) as excinfo:
        await ConfirmMarketBriefUseCase(repository, store).execute(
            workspace_id=workspace.workspace_id, confirmed_by="requester", **incomplete
        )

    assert excinfo.value.missing_fields == ["hypothesis", "falsifiers"]
    assert await store.list_workspace_missions(workspace.workspace_id) == []
    assert await store.next_brief_revision_number(workspace.workspace_id) == 1


@pytest.mark.asyncio
async def test_a_market_mission_without_a_confirmed_brief_is_blocked_not_run(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    mission, _revision = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id, confirmed_by="requester", **COMPLETE_BRIEF
    )
    # Stand in for a Market mission whose Brief cannot be read: the gate has to fail closed.
    orphan = await repository.get_mission(mission.id)
    orphan.id = uuid4()
    orphan.shortcode = f"ORPHAN-{orphan.id.hex[:6].upper()}"
    orphan.brief_revision_id = None
    await repository.save_mission(orphan)

    with pytest.raises(IncompleteMarketBriefError):
        await _executor(repository, store).execute(orphan.id)

    blocked = await repository.get_mission(orphan.id)
    assert blocked.status == "BLOCKED"


@pytest.mark.asyncio
async def test_a_confirmed_brief_authorizes_the_run_and_stays_immutable(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    mission, revision = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester@example.com",
        keywords=["ai customer service"],
        lineage=MissionLineage(),
        **COMPLETE_BRIEF,
    )
    assert mission.surface == ResearchSurface.MARKET.value
    assert mission.brief_revision_id == revision.brief_revision_id
    assert revision.revision_number == 1

    result = await _executor(repository, store).execute(mission.id)
    assert result["status"] == "COMPLETED"

    # The confirmed revision is read back exactly as confirmed.
    stored_revision = await store.get_brief_revision_for_mission(mission.id)
    assert stored_revision.hypothesis == COMPLETE_BRIEF["hypothesis"]
    assert list(stored_revision.falsifiers) == COMPLETE_BRIEF["falsifiers"]
    assert stored_revision.confirmed_by == "requester@example.com"


@pytest.mark.asyncio
async def test_market_conclusions_are_traceable_to_canonical_observations(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    mission, revision = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["ai customer service"],
        **COMPLETE_BRIEF,
    )
    await _executor(repository, store).execute(mission.id)

    signals = await repository.get_mission_signals(mission.id)
    stored = await repository.get_mission(mission.id)
    report = StrategicMarketReasoner().analyze_mission(
        mission=stored,
        signals=signals,
        clusters=[],
        scorecard=QualityScorecard(),
        connector_health={
            "google_rss": {"platform": "google", "circuit_state": "CLOSED"},
            "tiktok": {"platform": "tiktok", "circuit_state": "CLOSED"},
        },
        market_brief=revision.to_payload(),
    )

    assert report.surface == ResearchSurface.MARKET.value
    assert report.market_brief["falsifiers"] == COMPLETE_BRIEF["falsifiers"]
    assert report.market_opportunities, "A Market mission must produce its opportunity matrix."

    observation_ids = {str(s.observation_id) for s in signals}
    cited = [c for opp in report.market_opportunities for c in opp.citations]
    assert cited, "An opportunity backed by collected evidence must cite the observations."
    for opportunity in report.market_opportunities:
        for citation in opportunity.citations:
            assert citation.observation_id in observation_ids
            # The URL is display payload, so it must never be the only handle on the evidence.
            assert citation.observation_id != citation.url

    for insight in list(report.strategic_insights) + list(report.actionable_takeaways):
        for citation in insight.citations:
            assert citation.observation_id in observation_ids


@pytest.mark.asyncio
async def test_an_attention_result_can_be_carried_into_a_market_brief_as_context(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    attention = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="VN customer service attention",
        seed="ai customer service",
    )
    await _executor(repository, store).execute(attention.id)

    market, _revision = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        lineage=MissionLineage(parent_attention_mission_id=attention.id),
        **COMPLETE_BRIEF,
    )

    stored = await repository.get_mission(market.id)
    assert stored.parent_attention_mission_id == attention.id
    # Lineage is context, not evidence: the new mission starts holding none of its own.
    assert await repository.get_mission_signals(market.id) == []
