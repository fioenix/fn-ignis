"""The two surfaces end to end, against a real database and the real mission ingress path.

Only the external connectors are replaced. Persistence, clustering, evidence attachment and
analysis are the production code, because the claims under test -- that Attention never emits an
Opportunity Index, that Market cannot probe without a confirmed Brief, and that every Market
citation reaches a canonical observation -- are claims about what those paths actually do.
"""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_attention_mission import (
    CreateAttentionMissionUseCase,
)
from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import ResearchMission, TrendSignal
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


# --- The Market authorization gate, at the real MCP tool boundary -------------

class ProbeCountingRegistry(StubRegistry):
    """A registry that records whether any connector was actually reached."""

    def __init__(self, signals):
        super().__init__(signals)
        self.probe_calls = 0

    async def search_across_all(self, **kwargs):
        self.probe_calls += 1
        return await super().search_across_all(**kwargs)

    def get_health_status(self):
        return {
            "google_rss": {"platform": "google", "circuit_state": "CLOSED"},
            "tiktok": {"platform": "tiktok", "circuit_state": "CLOSED"},
        }


def _mcp_components(repository, store, registry):
    """The real handlers over the real database, with only the connectors replaced."""
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
    from ignis.application.use_cases.get_top_clusters import GetTopClustersUseCase
    from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
    from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

    return {
        "repository": repository,
        "workspace_store": store,
        "registry": registry,
        "clusterer": SemanticClusterer(),
        "quality_evaluator": QualityEvaluator(),
        "strategic_reasoner": StrategicMarketReasoner(),
        "artifact_builder": HtmlArtifactBuilder(),
        "top_clusters_use_case": GetTopClustersUseCase(repository=repository),
        "get_mission_analysis_use_case": GetMissionAnalysisUseCase(repository=repository),
        "execute_mission_use_case": ExecuteMissionUseCase(
            repository=repository,
            registry=registry,
            clusterer=SemanticClusterer(),
            workspace_store=store,
        ),
    }


async def _unauthorized_market_mission(repository, workspace):
    """A MARKET mission with no confirmed Brief -- the state every gate has to refuse."""
    mission = ResearchMission(
        title="Unauthorized market investigation",
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.MARKET.value,
    )
    await repository.save_mission(mission)
    return mission


@pytest.mark.asyncio
async def test_ingress_on_an_unauthorized_market_mission_returns_the_blocked_contract(
    repository_case, host_workspace, monkeypatch
):
    from ignis.domain.research_workspace import REQUIRED_BRIEF_FIELDS
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _unauthorized_market_mission(repository, workspace)

    registry = ProbeCountingRegistry(_probe_signals())
    components = _mcp_components(repository, store, registry)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    payload = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))

    assert payload["status"] == "BLOCKED"
    assert payload["surface"] == "MARKET"
    assert payload["missing_fields"] == list(REQUIRED_BRIEF_FIELDS)
    assert payload["mission_id"] == str(mission.id)
    # Refused as a tool result, not as a transport error, and refused before any probe ran.
    assert registry.probe_calls == 0

    stored = await repository.get_mission(mission.id)
    assert stored.status == "BLOCKED"


@pytest.mark.asyncio
async def test_analysis_of_an_unauthorized_market_mission_derives_no_opportunity_index(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _unauthorized_market_mission(repository, workspace)

    components = _mcp_components(repository, store, ProbeCountingRegistry(_probe_signals()))
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    raw = await mcp_server.handle_get_mission_analysis(str(mission.id))
    payload = json.loads(raw)

    assert payload["status"] == "BLOCKED"
    assert payload["opportunity_index_applies"] is False
    # No successful analysis shape at all, and no index anywhere in the response text.
    assert "market_opportunities" not in payload
    assert "quality_scorecard" not in payload
    assert "market_brief" not in payload
    # `opportunity_index_applies: false` is the only occurrence; no index value is computed.
    assert '"opportunity_index"' not in raw

    discover = json.loads(await mcp_server.handle_discover_market_opportunities(str(mission.id)))
    assert discover["status"] == "BLOCKED"
    assert "market_opportunities" not in discover


@pytest.mark.asyncio
async def test_an_unauthorized_market_mission_exports_no_artifact(
    repository_case, host_workspace, monkeypatch, tmp_path
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _unauthorized_market_mission(repository, workspace)

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    components = _mcp_components(repository, store, ProbeCountingRegistry(_probe_signals()))
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)
    monkeypatch.setattr(mcp_server, "_get_secure_reports_dir", lambda: reports_dir)

    payload = json.loads(await mcp_server.handle_generate_mission_artifact(str(mission.id)))

    assert payload["status"] == "BLOCKED"
    assert "artifact_file" not in payload
    # The exported dossier is the copy that outlives the chat, so nothing reaches disk.
    assert list(reports_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_the_gate_does_not_block_a_confirmed_brief_or_an_attention_mission(
    repository_case, host_workspace, monkeypatch, tmp_path
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    registry = ProbeCountingRegistry(_probe_signals())
    components = _mcp_components(repository, store, registry)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(mcp_server, "_get_secure_reports_dir", lambda: reports_dir)

    attention = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="VN customer service attention",
        seed="ai customer service",
    )
    attention_run = json.loads(
        await mcp_server.handle_execute_mission_ingress(str(attention.id))
    )
    assert attention_run["status"] == "COMPLETED"

    market, _revision = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["ai customer service"],
        **COMPLETE_BRIEF,
    )
    market_run = json.loads(await mcp_server.handle_execute_mission_ingress(str(market.id)))
    assert market_run["status"] == "COMPLETED"

    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(market.id)))
    assert analysis["surface"] == "MARKET"
    assert analysis["opportunity_index_applies"] is True
    assert analysis["market_brief"]["falsifiers"] == COMPLETE_BRIEF["falsifiers"]

    artifact = json.loads(await mcp_server.handle_generate_mission_artifact(str(market.id)))
    assert artifact["status"] == "SUCCESS"
    assert list(reports_dir.iterdir())


# --- Atomic Brief confirmation ----------------------------------------------

@pytest.mark.asyncio
async def test_a_failed_brief_write_leaves_no_orphan_market_mission(
    repository_case, host_workspace, monkeypatch
):
    """The mission and its Brief are one fact, so a failed confirmation writes neither.

    Failure is injected at the row writer rather than at the use case, because the invariant
    under test belongs to the transaction: writing the mission first and failing on the revision
    is exactly the sequence that used to leave a MARKET mission no Brief could ever authorize.
    """
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    def _explode(*_args, **_kwargs):
        raise RuntimeError("injected failure while persisting the Brief revision")

    monkeypatch.setattr(repository, "_write_brief_revision_row", _explode)

    with pytest.raises(Exception):
        await ConfirmMarketBriefUseCase(repository, store).execute(
            workspace_id=workspace.workspace_id,
            confirmed_by="requester",
            keywords=["ai customer service"],
            **COMPLETE_BRIEF,
        )

    assert await store.list_workspace_missions(workspace.workspace_id) == []
    assert await store.next_brief_revision_number(workspace.workspace_id) == 1


@pytest.mark.asyncio
async def test_a_confirmation_that_failed_can_simply_be_retried(
    repository_case, host_workspace, monkeypatch
):
    """Nothing is left behind to collide with, so the requester just confirms again."""
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    original = repository._write_brief_revision_row
    calls = {"n": 0}

    def _fail_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected failure while persisting the Brief revision")
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, "_write_brief_revision_row", _fail_once)

    use_case = ConfirmMarketBriefUseCase(repository, store)
    with pytest.raises(Exception):
        await use_case.execute(
            workspace_id=workspace.workspace_id, confirmed_by="requester", **COMPLETE_BRIEF
        )

    mission, revision = await use_case.execute(
        workspace_id=workspace.workspace_id, confirmed_by="requester", **COMPLETE_BRIEF
    )
    assert revision.revision_number == 1
    missions = await store.list_workspace_missions(workspace.workspace_id)
    assert [m.id for m in missions] == [mission.id]


# --- User Story 4: handoff and revision without rewriting history ------------

def _revision_use_case(repository, store):
    from ignis.application.use_cases.create_market_revision import CreateMarketRevisionUseCase

    return CreateMarketRevisionUseCase(repository=repository, store=store)


@pytest.mark.asyncio
async def test_an_attention_topic_hands_off_to_a_market_mission_with_its_lineage(
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
    attention_signals = await repository.get_mission_signals(attention.id)
    assert attention_signals

    cluster_id = next(
        (s.cluster_id for s in attention_signals if s.cluster_id is not None), None
    )
    market, revision = await _revision_use_case(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["ai customer service"],
        lineage=MissionLineage(
            parent_attention_mission_id=attention.id, parent_cluster_id=cluster_id
        ),
        **COMPLETE_BRIEF,
    )

    stored = await repository.get_mission(market.id)
    assert stored.surface == ResearchSurface.MARKET.value
    assert stored.parent_attention_mission_id == attention.id
    assert stored.parent_cluster_id == cluster_id
    assert stored.brief_revision_id == revision.brief_revision_id
    # A separate mission, not a re-labelled Attention one.
    assert stored.id != attention.id
    assert await repository.get_mission_signals(market.id) == []


@pytest.mark.asyncio
async def test_a_revised_brief_opens_a_new_evidence_line_and_leaves_the_old_one_untouched(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    use_case = _revision_use_case(repository, store)

    first_mission, first_revision = await use_case.execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["ai customer service"],
        **COMPLETE_BRIEF,
    )
    await _executor(repository, store).execute(first_mission.id)
    first_evidence = {
        str(s.observation_id) for s in await repository.get_mission_signals(first_mission.id)
    }
    assert first_evidence

    revised_brief = {
        **COMPLETE_BRIEF,
        "hypothesis": "Only VN retailers above 500 orders a month will pay for sub-minute replies",
    }
    second_mission, second_revision = await use_case.execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["ai customer service"],
        previous_mission_id=first_mission.id,
        **revised_brief,
    )

    # Two identities, two revisions, one monotonic line.
    assert second_mission.id != first_mission.id
    assert second_revision.brief_revision_id != first_revision.brief_revision_id
    assert second_revision.revision_number == first_revision.revision_number + 1

    # The earlier Brief and its evidence are exactly as they were.
    stored_first = await store.get_brief_revision_for_mission(first_mission.id)
    assert stored_first.hypothesis == COMPLETE_BRIEF["hypothesis"]
    assert stored_first.revision_number == first_revision.revision_number
    assert {
        str(s.observation_id) for s in await repository.get_mission_signals(first_mission.id)
    } == first_evidence

    # The new mission is authorized by its own Brief and owns no evidence yet.
    stored_second = await repository.get_mission(second_mission.id)
    assert stored_second.brief_revision_id == second_revision.brief_revision_id
    assert await repository.get_mission_signals(second_mission.id) == []

    # Its own probe run produces its own evidence line.
    assert (await _executor(repository, store).execute(second_mission.id))["status"] == "COMPLETED"
    second_evidence = await repository.get_mission_signals(second_mission.id)
    assert second_evidence and all(s.observation_id for s in second_evidence)


@pytest.mark.asyncio
async def test_a_market_conclusion_cites_only_the_evidence_of_its_own_brief(
    repository_case, host_workspace
):
    """Attention lineage travels with the mission; Attention observations do not become proof."""
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)

    attention = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="VN customer service attention",
        seed="ai customer service",
    )
    await _executor(repository, store).execute(attention.id)
    attention_ids = {
        str(s.observation_id) for s in await repository.get_mission_signals(attention.id)
    }

    market, revision = await _revision_use_case(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["ai customer service"],
        lineage=MissionLineage(parent_attention_mission_id=attention.id),
        **COMPLETE_BRIEF,
    )
    await _executor(repository, store).execute(market.id)

    market_signals = await repository.get_mission_signals(market.id)
    market_ids = {str(s.observation_id) for s in market_signals}
    context_only = attention_ids - market_ids
    assert context_only, "The Attention run must hold at least one observation of its own."

    stored = await repository.get_mission(market.id)
    report = StrategicMarketReasoner().analyze_mission(
        mission=stored,
        signals=market_signals,
        clusters=[],
        scorecard=QualityScorecard(),
        market_brief=revision.to_payload(),
        attention_context_signals=await repository.get_mission_signals(attention.id),
    )

    supporting = [
        c
        for item in list(report.market_opportunities)
        + list(report.strategic_insights)
        + list(report.actionable_takeaways)
        for c in item.citations
    ]
    assert supporting
    assert all(c.observation_id in market_ids for c in supporting)
    assert all(c.evidence_role == "MARKET_EVIDENCE" for c in supporting)
    # The carried observations are reported, and reported as context.
    carried = {c.observation_id for c in report.attention_context}
    assert context_only <= carried
    assert all(c.evidence_role == "ATTENTION_CONTEXT" for c in report.attention_context)


@pytest.mark.asyncio
async def test_the_analysis_response_separates_attention_context_from_market_evidence(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    registry = ProbeCountingRegistry(_probe_signals())
    components = _mcp_components(repository, store, registry)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    attention = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="VN customer service attention",
        seed="ai customer service",
    )
    await _executor(repository, store).execute(attention.id)

    market, _revision = await _revision_use_case(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["ai customer service"],
        lineage=MissionLineage(parent_attention_mission_id=attention.id),
        **COMPLETE_BRIEF,
    )
    await _executor(repository, store).execute(market.id)

    payload = json.loads(await mcp_server.handle_get_mission_analysis(str(market.id)))

    assert payload["surface"] == "MARKET"
    assert payload["lineage"]["parent_attention_mission_id"] == str(attention.id)
    market_ids = {
        str(s.observation_id) for s in await repository.get_mission_signals(market.id)
    }
    for opportunity in payload["market_opportunities"]:
        for citation in opportunity["citations"]:
            assert citation["evidence_role"] == "MARKET_EVIDENCE"
            assert citation["observation_id"] in market_ids
    assert payload["attention_context"]
    assert all(c["evidence_role"] == "ATTENTION_CONTEXT" for c in payload["attention_context"])


@pytest.mark.asyncio
async def test_a_handoff_from_another_workspace_is_refused_and_writes_nothing(
    repository_case, host_workspace, tmp_path
):
    from ignis.domain.research_workspace import WorkspaceScopeMismatchError

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    other_host = tmp_path / "other-project"
    other_host.mkdir()
    _other_store, other = await _workspace(repository, other_host, name="Other research")

    foreign = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=other.workspace_id, title="Foreign attention", seed="something else"
    )

    with pytest.raises(WorkspaceScopeMismatchError):
        await _revision_use_case(repository, store).execute(
            workspace_id=workspace.workspace_id,
            confirmed_by="requester",
            lineage=MissionLineage(parent_attention_mission_id=foreign.id),
            **COMPLETE_BRIEF,
        )

    assert await store.list_workspace_missions(workspace.workspace_id) == []
    assert await store.next_brief_revision_number(workspace.workspace_id) == 1


@pytest.mark.asyncio
async def test_the_brief_tool_refuses_a_parent_that_is_not_an_attention_result(
    repository_case, host_workspace, monkeypatch
):
    """The lineage check runs at the tool boundary, before a mission is written."""
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    components = _mcp_components(repository, store, ProbeCountingRegistry(_probe_signals()))
    components["confirm_market_brief_use_case"] = ConfirmMarketBriefUseCase(repository, store)
    components["create_market_revision_use_case"] = _revision_use_case(repository, store)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    market, _revision = await _revision_use_case(repository, store).execute(
        workspace_id=workspace.workspace_id, confirmed_by="requester", **COMPLETE_BRIEF
    )

    payload = json.loads(
        await mcp_server.handle_confirm_market_brief(
            workspace_id=str(workspace.workspace_id),
            confirmed_by="requester",
            parent_attention_mission_id=str(market.id),
            **COMPLETE_BRIEF,
        )
    )
    assert "error" in payload
    assert "surface" in payload["error"]
    # One mission, the one that was legitimately confirmed.
    assert [m.id for m in await store.list_workspace_missions(workspace.workspace_id)] == [
        market.id
    ]


@pytest.mark.asyncio
async def test_the_brief_tool_revises_a_confirmed_brief_into_a_new_mission(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    components = _mcp_components(repository, store, ProbeCountingRegistry(_probe_signals()))
    components["create_market_revision_use_case"] = _revision_use_case(repository, store)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    first = json.loads(
        await mcp_server.handle_confirm_market_brief(
            workspace_id=str(workspace.workspace_id),
            confirmed_by="requester",
            **COMPLETE_BRIEF,
        )
    )
    assert first["status"] == "CONFIRMED"
    assert first["revision_number"] == 1

    second = json.loads(
        await mcp_server.handle_confirm_market_brief(
            workspace_id=str(workspace.workspace_id),
            confirmed_by="requester",
            previous_mission_id=first["mission_id"],
            **{**COMPLETE_BRIEF, "hypothesis": "A narrower hypothesis about repeat buyers"},
        )
    )
    assert second["revision_number"] == 2
    assert second["mission_id"] != first["mission_id"]
    assert second["brief_revision_id"] != first["brief_revision_id"]
    assert second["lineage"]["revises_mission_id"] == first["mission_id"]
    assert first["lineage"]["revises_mission_id"] is None

    # The first Brief still reads exactly as it was confirmed.
    stored_first = await store.get_brief_revision_for_mission(UUID(first["mission_id"]))
    assert stored_first.hypothesis == COMPLETE_BRIEF["hypothesis"]

    # And the relation is durable: a host that only has the database finds it.
    reopened = await repository.get_mission(UUID(second["mission_id"]))
    assert reopened.revises_mission_id == UUID(first["mission_id"])
    revised = await repository.get_mission(UUID(first["mission_id"]))
    assert revised.revises_mission_id is None

    analysis = json.loads(await mcp_server.handle_get_mission_analysis(second["mission_id"]))
    assert analysis["lineage"]["revises_mission_id"] == first["mission_id"]
    assert analysis["mission"]["lineage"]["revises_mission_id"] == first["mission_id"]


@pytest.mark.asyncio
async def test_the_brief_tool_refuses_a_revision_that_re_points_the_attention_origin(
    repository_case, host_workspace, monkeypatch
):
    """A revision inherits its origin; a payload that contradicts it is refused, not ignored."""
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    components = _mcp_components(repository, store, ProbeCountingRegistry(_probe_signals()))
    components["create_market_revision_use_case"] = _revision_use_case(repository, store)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    origin = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id, title="Origin", seed="ai customer service"
    )
    elsewhere = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id, title="Elsewhere", seed="something else"
    )
    first, _ = await _revision_use_case(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        lineage=MissionLineage(parent_attention_mission_id=origin.id),
        **COMPLETE_BRIEF,
    )

    payload = json.loads(
        await mcp_server.handle_confirm_market_brief(
            workspace_id=str(workspace.workspace_id),
            confirmed_by="requester",
            previous_mission_id=str(first.id),
            parent_attention_mission_id=str(elsewhere.id),
            **{**COMPLETE_BRIEF, "hypothesis": "A narrower hypothesis"},
        )
    )
    assert "error" in payload
    assert str(elsewhere.id) in payload["error"]

    market_missions = [
        m
        for m in await store.list_workspace_missions(workspace.workspace_id)
        if m.surface == ResearchSurface.MARKET.value
    ]
    assert [m.id for m in market_missions] == [first.id]
    assert await store.next_brief_revision_number(workspace.workspace_id) == 2
