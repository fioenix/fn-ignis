"""What each analytical surface is allowed to claim.

ATTENTION describes what is being looked at. MARKET describes whether that is worth building.
The Opportunity Index belongs to the second question only, and the boundary is enforced in the
domain rather than left to whichever renderer happens to read the report.
"""

import pytest

from ignis.domain.research_workspace import (
    MissionLineage,
    ResearchSurface,
    SurfaceViolationError,
    opportunity_index_is_allowed,
    resolve_surface,
)
from ignis.infrastructure.connectors.registry import SearchPassResult


def test_the_two_surfaces_are_the_only_ones_that_exist():
    assert {s.value for s in ResearchSurface} == {"ATTENTION", "MARKET"}


def test_resolve_surface_accepts_the_stored_text_form():
    assert resolve_surface("market") is ResearchSurface.MARKET
    assert resolve_surface("ATTENTION") is ResearchSurface.ATTENTION
    assert resolve_surface(ResearchSurface.MARKET) is ResearchSurface.MARKET


def test_a_mission_with_no_recorded_surface_resolves_to_none_rather_than_a_guess():
    # Missions created before the workspace feature have no surface. Defaulting them to MARKET
    # would retroactively gate them on a Brief nobody was ever asked for.
    assert resolve_surface(None) is None
    assert resolve_surface("") is None


def test_an_unknown_surface_is_refused_instead_of_being_coerced():
    with pytest.raises(SurfaceViolationError):
        resolve_surface("OPPORTUNITY")


def test_the_opportunity_index_is_available_to_market_only():
    assert opportunity_index_is_allowed(ResearchSurface.MARKET) is True
    assert opportunity_index_is_allowed(ResearchSurface.ATTENTION) is False


def test_a_mission_without_a_surface_keeps_the_behaviour_it_already_had():
    # Suppressing the index for every legacy mission would break the existing tools that read
    # it. The boundary this feature adds is "ATTENTION never claims a market", not "everything
    # outside a workspace goes quiet".
    assert opportunity_index_is_allowed(None) is True


def test_attention_lineage_is_context_and_is_empty_by_default():
    lineage = MissionLineage()
    assert lineage.parent_attention_mission_id is None
    assert lineage.parent_cluster_id is None
    assert lineage.is_empty is True


@pytest.mark.asyncio
async def test_an_attention_report_carries_no_opportunity_and_a_market_one_does():
    """The boundary is enforced where the number is produced, not where it is rendered.

    Computing the index and suppressing it in a serializer would leave it on the report object
    for any caller that read it directly, which is the form the leak would actually take.
    """
    from ignis.domain.entities import ResearchMission, TrendSignal
    from ignis.domain.harness_models import QualityScorecard
    from ignis.domain.value_objects import GeoCode, PlatformType
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

    signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="ai customer service",
            metric_value=90.0,
            geo_code=GeoCode.VN,
            metadata={"keyword": "ai customer service"},
        )
    ]
    reasoner = StrategicMarketReasoner()

    def _report(surface):
        mission = ResearchMission(
            title="AI customer service",
            keywords=["ai customer service"],
            surface=surface,
        )
        return reasoner.analyze_mission(mission, signals, [], QualityScorecard())

    assert _report(ResearchSurface.ATTENTION.value).market_opportunities == []
    assert _report(ResearchSurface.MARKET.value).market_opportunities != []
    # A mission created outside a workspace declared no surface and keeps what it had.
    assert _report(None).market_opportunities != []


@pytest.mark.asyncio
async def test_a_saved_mission_cannot_change_the_question_it_answers():
    """Surface is immutable in the write path, not merely by convention.

    Moving a mission from ATTENTION to MARKET would re-label evidence collected to answer the
    other question, which is the one thing the two surfaces exist to keep apart.
    """
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.domain.entities import ResearchMission

    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    try:
        mission = ResearchMission(
            title="VN customer service attention",
            keywords=["ai customer service"],
            surface=ResearchSurface.ATTENTION.value,
        )
        await repository.save_mission(mission)

        mission.surface = ResearchSurface.MARKET.value
        mission.status = "RUNNING"
        await repository.save_mission(mission)

        stored = await repository.get_mission(mission.id)
        assert stored.surface == ResearchSurface.ATTENTION.value
        # Everything a run legitimately updates still moves.
        assert stored.status == "RUNNING"
    finally:
        await repository.close()


# --- User Story 4: Attention context versus Market evidence ------------------

def _market_signal(title="ai customer service", observation_id=None):
    from uuid import uuid4

    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import GeoCode, PlatformType

    return TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title=title,
        metric_value=90.0,
        geo_code=GeoCode.VN,
        observation_id=observation_id or uuid4(),
        metadata={"keyword": title, "connector_surface": "google_rss"},
    )


def test_the_two_evidence_roles_are_the_only_ones_that_exist():
    from ignis.domain.research_workspace import EvidenceRole

    assert {r.value for r in EvidenceRole} == {"MARKET_EVIDENCE", "ATTENTION_CONTEXT"}


def test_a_market_report_labels_its_own_observations_as_market_evidence():
    from ignis.domain.entities import ResearchMission
    from ignis.domain.harness_models import QualityScorecard
    from ignis.domain.research_workspace import EvidenceRole
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

    mission = ResearchMission(
        title="AI customer service",
        keywords=["ai customer service"],
        surface=ResearchSurface.MARKET.value,
    )
    report = StrategicMarketReasoner().analyze_mission(
        mission, [_market_signal()], [], QualityScorecard()
    )
    cited = [c for opp in report.market_opportunities for c in opp.citations]
    assert cited
    assert all(c.evidence_role == EvidenceRole.MARKET_EVIDENCE.value for c in cited)


def test_carried_attention_observations_are_labelled_context_and_never_become_support():
    """Lineage explains where the question came from; it does not answer it.

    The carried observations are reported so a reader can see the origin, and they are kept out
    of the opportunity matrix entirely -- an Attention sighting counted as Market support is the
    exact promotion this story exists to prevent.
    """
    from ignis.domain.entities import ResearchMission
    from ignis.domain.harness_models import QualityScorecard
    from ignis.domain.research_workspace import EvidenceRole
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

    market_signal = _market_signal()
    context_signal = _market_signal(title="earlier attention sighting")

    mission = ResearchMission(
        title="AI customer service",
        keywords=["ai customer service"],
        surface=ResearchSurface.MARKET.value,
    )
    report = StrategicMarketReasoner().analyze_mission(
        mission,
        [market_signal],
        [],
        QualityScorecard(),
        attention_context_signals=[context_signal],
    )

    context_ids = {c.observation_id for c in report.attention_context}
    assert context_ids == {str(context_signal.observation_id)}
    assert all(
        c.evidence_role == EvidenceRole.ATTENTION_CONTEXT.value for c in report.attention_context
    )

    supporting = [
        c
        for item in list(report.market_opportunities)
        + list(report.strategic_insights)
        + list(report.actionable_takeaways)
        for c in item.citations
    ]
    assert supporting
    assert not any(c.observation_id in context_ids for c in supporting)


def test_an_attention_report_labels_its_observations_as_context_rather_than_evidence():
    from ignis.domain.entities import ResearchMission
    from ignis.domain.harness_models import QualityScorecard
    from ignis.domain.research_workspace import EvidenceRole
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

    mission = ResearchMission(
        title="AI customer service attention",
        keywords=["ai customer service"],
        surface=ResearchSurface.ATTENTION.value,
    )
    report = StrategicMarketReasoner().analyze_mission(
        mission, [_market_signal()], [], QualityScorecard()
    )
    cited = [ch.top_citation for ch in report.channel_summaries if ch.top_citation]
    assert cited
    assert all(c.evidence_role == EvidenceRole.ATTENTION_CONTEXT.value for c in cited)


def test_a_legacy_mission_without_a_surface_labels_no_evidence_role():
    from ignis.domain.entities import ResearchMission
    from ignis.domain.harness_models import QualityScorecard
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

    mission = ResearchMission(title="Legacy", keywords=["ai customer service"])
    report = StrategicMarketReasoner().analyze_mission(
        mission, [_market_signal()], [], QualityScorecard()
    )
    cited = [c for opp in report.market_opportunities for c in opp.citations]
    assert cited
    assert all(c.evidence_role is None for c in cited)


def test_a_context_citation_is_dropped_from_anything_a_conclusion_rests_on():
    """The filter is the enforcement point, so it is asserted directly.

    Context observations are never fed into the analysis in the first place, but the boundary
    has to hold for a caller that assembles a report some other way.
    """
    from ignis.domain.harness_models import CitationEvidence, MarketOpportunity, StrategicInsight
    from ignis.domain.research_workspace import EvidenceRole
    from ignis.domain.value_objects import PlatformType
    from ignis.infrastructure.harness.strategic_reasoner import strip_context_citations

    def _cit(role, observation_id):
        return CitationEvidence(
            citation_id="CIT-01",
            platform=PlatformType.GOOGLE_TRENDS,
            title_or_query="ai customer service",
            metric_highlight="search index 90/100",
            observation_id=observation_id,
            evidence_role=role,
        )

    support = _cit(EvidenceRole.MARKET_EVIDENCE.value, "kept")
    context = _cit(EvidenceRole.ATTENTION_CONTEXT.value, "dropped")

    opportunity = MarketOpportunity(
        topic="ai customer service",
        opportunity_type="HIGH_DEMAND_LOW_SUPPLY",
        search_interest_score=90.0,
        content_supply_score=10.0,
        opportunity_index=80.0,
        strategic_recommendation="Test it",
        citations=[support, context],
    )
    insight = StrategicInsight(statement="Demand outruns supply", citations=[context, support])

    strip_context_citations([opportunity, insight])
    assert [c.observation_id for c in opportunity.citations] == ["kept"]
    assert [c.observation_id for c in insight.citations] == ["kept"]


# --- User Story 5: mission state under a run ---------------------------------

class _ExplodingRegistry:
    """A connector pass that fails, which is what the failure path exists for."""

    async def search_with_outcomes(self, **kwargs):
        # The mission executor asks for per-surface outcomes; this double reports none.
        return SearchPassResult(signals=await self.search_across_all(**kwargs))

    async def search_across_all(self, **_kwargs):
        raise RuntimeError("connector pass failed")


class _SilentRegistry:
    async def search_with_outcomes(self, **kwargs):
        # The mission executor asks for per-surface outcomes; this double reports none.
        return SearchPassResult(signals=await self.search_across_all(**kwargs))

    async def search_across_all(self, **_kwargs):
        return []


async def _workspace_mission(repository, store, tmp_path, title="VN customer service"):
    from ignis.application.use_cases.create_research_workspace import (
        CreateResearchWorkspaceUseCase,
    )
    from ignis.domain.entities import ResearchMission

    use_case = CreateResearchWorkspaceUseCase(store=store)
    host = tmp_path / "host"
    host.mkdir(exist_ok=True)
    workspace = await use_case.confirm(
        await use_case.propose(host, "AI customer service"), confirmation=True
    )
    mission = ResearchMission(
        title=title,
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository.create_mission(mission)
    return workspace, mission


def _executor(repository, store, registry):
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer

    return ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=SemanticClusterer(),
        workspace_store=store,
    )


@pytest.mark.asyncio
async def test_a_failed_run_leaves_no_false_running_state_and_no_active_writer(tmp_path):
    """A mission left RUNNING with nobody writing is the state recovery cannot tell from work.

    The failure has to land somewhere readable: the mission FAILED, the journal FAILED, and the
    writer slot free so the next attempt is not locked out by the attempt that broke.
    """
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    store = WorkspaceRepository(repository=repository)
    try:
        workspace, mission = await _workspace_mission(repository, store, tmp_path)

        with pytest.raises(RuntimeError):
            await _executor(repository, store, _ExplodingRegistry()).execute(mission.id)

        stored = await repository.get_mission(mission.id)
        assert stored.status == "FAILED"
        # The question it answers is not something a failed run gets to change.
        assert stored.surface == ResearchSurface.ATTENTION.value
        assert await store.get_mission_writer_claim(mission.id) is None
        assert (await store.latest_run_journal(mission.id)).status == "FAILED"
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_a_completed_run_reports_its_own_run_and_journal(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    store = WorkspaceRepository(repository=repository)
    try:
        workspace, mission = await _workspace_mission(repository, store, tmp_path)
        result = await _executor(repository, store, _SilentRegistry()).execute(mission.id)

        assert result["status"] == "COMPLETED"
        journal = await store.latest_run_journal(mission.id)
        assert result["run"]["run_id"] == str(journal.run_id)
        assert result["run"]["workspace_id"] == str(workspace.workspace_id)
        assert result["run"]["journal_status"] == "COMPLETED"
        assert await store.get_mission_writer_claim(mission.id) is None
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_a_mission_outside_a_research_workspace_runs_exactly_as_before(tmp_path):
    """No workspace means no journal to write and no research to serialize against.

    Every mission created before this feature is in that state, and making the run path depend
    on a workspace would stop all of them.
    """
    from ignis.domain.entities import ResearchMission
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    store = WorkspaceRepository(repository=repository)
    try:
        mission = ResearchMission(title="Legacy mission", keywords=["ai customer service"])
        await repository.create_mission(mission)

        result = await _executor(repository, store, _SilentRegistry()).execute(mission.id)
        assert result["status"] == "COMPLETED"
        assert "run" not in result
        assert await store.list_run_journals(mission.id) == []
    finally:
        await repository.close()


# --- User Story 2: the deterministic evidence minimum for a Market verdict ----------------------
#
# The semantic judgment labels evidence; policy code decides whether a verdict is allowed. The
# minimums are product safety defaults: one qualified demand observation, and either two qualified
# supply observations from two canonical sources or two relevant surfaces that completed and came
# back empty for the same query.

from datetime import datetime, timezone  # noqa: E402
from uuid import uuid4  # noqa: E402

from ignis.domain.research_workspace import (  # noqa: E402
    EvidencePurpose,
    EvidenceSufficiency,
    MissionProbeOutcome,
    QualificationStatus,
    QualifiedObservation,
    assess_topic_sufficiency,
)

QUERY = "q" * 64
RUN = uuid4()


def _qualified(purpose, source=None, platform="youtube"):
    return QualifiedObservation(
        observation_id=str(uuid4()),
        source_id=source or str(uuid4()),
        purpose=EvidencePurpose(purpose),
        platform=platform,
    )


def _probe(surface, status="EMPTY_NO_DATA", platform=None, query=QUERY, count=0):
    return MissionProbeOutcome(
        run_id=RUN, platform=platform or surface, connector_surface=surface, status=status,
        signals_collected=count, query_fingerprint=query,
        completed_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
    )


def _assess(qualified=(), outcomes=(), state=QualificationStatus.READY):
    return assess_topic_sufficiency(
        topic="ai cho cửa hàng",
        qualified=list(qualified),
        probe_outcomes=list(outcomes),
        query_fingerprint=QUERY,
        assessment_state=state,
    )


def test_no_qualified_demand_withholds_the_verdict_whatever_the_supply():
    result = _assess([_qualified("SUPPLY"), _qualified("SUPPLY"), _qualified("VOC", platform="threads")])

    assert result.state is EvidenceSufficiency.MISSING_DEMAND
    assert result.state.permits_verdict is False
    assert result.qualified_demand_count == 0 and result.qualified_supply_count == 2


def test_one_demand_and_two_supply_observations_from_two_sources_is_sufficient():
    result = _assess([_qualified("DEMAND", platform="google"), _qualified("SUPPLY"), _qualified("SUPPLY")])

    assert result.state is EvidenceSufficiency.SUFFICIENT_POSITIVE_SUPPLY
    assert result.state.permits_verdict is True
    assert (result.qualified_demand_count, result.qualified_supply_count,
            result.independent_supply_sources) == (1, 2, 2)


def test_two_sightings_of_one_canonical_source_count_once():
    source = str(uuid4())
    result = _assess([
        _qualified("DEMAND", platform="google"),
        _qualified("SUPPLY", source=source, platform="youtube"),
        _qualified("SUPPLY", source=source, platform="tiktok"),
    ])

    assert result.state is EvidenceSufficiency.MISSING_SUPPLY
    assert result.independent_supply_sources == 1


def test_a_single_supply_observation_is_neither_supply_nor_measured_absence():
    result = _assess(
        [_qualified("DEMAND", platform="google"), _qualified("SUPPLY")],
        [_probe("tiktok_video_grid", platform="tiktok"), _probe("reels")],
    )

    assert result.state is EvidenceSufficiency.MISSING_SUPPLY


def test_two_completed_empty_supply_surfaces_measure_zero_supply():
    result = _assess(
        [_qualified("DEMAND", platform="google")],
        [_probe("youtube"), _probe("tiktok_video_grid", platform="tiktok")],
    )

    assert result.state is EvidenceSufficiency.SUFFICIENT_ZERO_SUPPLY
    assert result.measured_zero_surfaces == ("tiktok_video_grid", "youtube")
    assert result.qualified_supply_count == 0


@pytest.mark.parametrize("failed", ["AUTH_REQUIRED", "RATE_LIMITED", "DEGRADED"])
def test_a_surface_that_could_not_measure_is_never_zero_supply(failed):
    result = _assess(
        [_qualified("DEMAND", platform="google")],
        [_probe("youtube"), _probe("tiktok_video_grid", status=failed, platform="tiktok")],
    )

    assert result.state is EvidenceSufficiency.MISSING_SUPPLY
    assert result.measured_zero_surfaces == ("youtube",)


def test_an_empty_surface_measures_zero_only_for_its_own_query_and_only_as_supply():
    stale = _assess(
        [_qualified("DEMAND", platform="google")],
        [_probe("youtube", query="z" * 64), _probe("tiktok_video_grid", platform="tiktok")],
    )
    not_supply = _assess(
        [_qualified("DEMAND", platform="google")],
        [_probe("google"), _probe("threads"), _probe("youtube")],
    )
    healthy_but_irrelevant = _assess(
        [_qualified("DEMAND", platform="google")],
        [_probe("youtube", status="HEALTHY", count=30), _probe("reels")],
    )

    assert stale.state is EvidenceSufficiency.MISSING_SUPPLY
    assert not_supply.state is EvidenceSufficiency.MISSING_SUPPLY
    assert healthy_but_irrelevant.state is EvidenceSufficiency.MISSING_SUPPLY, (
        "a surface that returned only irrelevant items measured no absence"
    )


def test_unfinished_or_failed_qualification_withholds_every_verdict():
    sufficient = [_qualified("DEMAND", platform="google"), _qualified("SUPPLY"), _qualified("SUPPLY")]

    pending = _assess(sufficient, state=QualificationStatus.QUALIFICATION_REQUIRED)
    unavailable = _assess(sufficient, state=QualificationStatus.UNAVAILABLE)

    assert pending.state is EvidenceSufficiency.QUALIFICATION_REQUIRED
    assert unavailable.state is EvidenceSufficiency.QUALIFIER_UNAVAILABLE
    assert not pending.state.permits_verdict and not unavailable.state.permits_verdict


def test_every_withheld_state_carries_a_reason():
    for result in (
        _assess(),
        _assess([_qualified("DEMAND", platform="google")]),
        _assess(state=QualificationStatus.QUALIFICATION_REQUIRED),
        _assess(state=QualificationStatus.UNAVAILABLE),
    ):
        assert not result.state.permits_verdict
        assert result.reason, result.state


# --- User Story 3: an Attention handoff candidate must be qualified, never a fallback -----------
#
# Attention ranks what is being looked at; a ranked list is not evidence that any item clears a
# bar. A cluster becomes a Market handoff candidate only when its qualified evidence is directly
# relevant to the declared scope and comes from two canonical sources.

from ignis.domain.entities import ResearchMission, TrendSignal  # noqa: E402
from ignis.domain.harness_models import QualityScorecard  # noqa: E402
from ignis.domain.research_workspace import (  # noqa: E402
    EvidenceQualification,
    HandoffStatus,
    QualificationContext,
    select_handoff_candidates,
)
from ignis.domain.value_objects import GeoCode, PlatformType  # noqa: E402
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner  # noqa: E402

ATTENTION = ResearchMission(
    title="What is gaining attention around retail AI",
    keywords=["AI cho cửa hàng bán lẻ", "phần mềm AI bán hàng"],
    surface="ATTENTION",
)


def _attention_signal(title, cluster, source=None):
    return TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title=title,
        metric_value=1000.0,
        source_url=f"https://www.youtube.com/watch?v={uuid4().hex[:11]}",
        geo_code=GeoCode.VN,
        observation_id=uuid4(),
        source_id=source or uuid4(),
        cluster_id=cluster,
        metadata={"keyword": "AI cho cửa hàng bán lẻ", "connector_surface": "youtube"},
    )


def _judged(signal, relation, reason, purpose="SUPPLY", confidence=0.9):
    return EvidenceQualification(
        mission_id=ATTENTION.id,
        observation_id=signal.observation_id,
        frame_fingerprint="a" * 64,
        relation=relation,
        purpose="CONTEXT" if relation != "QUALIFIED_SUPPORT" else purpose,
        confidence=None if relation == "UNASSESSED" else confidence,
        reason_code=reason,
        judged_by="unit-test",
    )


def _attention_report(signals, judgments):
    context = QualificationContext.build(
        [s.observation_id for s in signals], judgments, probe_outcomes=(), query_fingerprint=None
    )
    return StrategicMarketReasoner().analyze_mission(
        mission=ATTENTION, signals=signals, clusters=[], scorecard=QualityScorecard(),
        qualification=context,
    )


def test_attention_noise_and_adjacent_clusters_offer_no_candidate_and_no_fallback():
    noise, adjacent = uuid4(), uuid4()
    signals = [
        _attention_signal("Phim hành động AI cho cửa hàng bán lẻ tập 12", noise),
        _attention_signal("Xổ số hôm nay: AI cho cửa hàng bán lẻ", noise),
        _attention_signal("Cách tạo video AI drama viral", adjacent),
        _attention_signal("AI xây website bán hàng cho người mới", adjacent),
    ]
    judgments = [
        _judged(signals[0], "EXCLUDED_IRRELEVANT", "FICTION_NEWS_OR_ENTERTAINMENT"),
        _judged(signals[1], "EXCLUDED_IRRELEVANT", "KEYWORD_ONLY"),
        _judged(signals[2], "CONTEXT_ONLY", "ADJACENT_ONLY"),
        _judged(signals[3], "CONTEXT_ONLY", "ADJACENT_ONLY"),
    ]

    report = _attention_report(signals, judgments)

    assert report.handoff_status == HandoffStatus.NO_QUALIFIED_CANDIDATE.value
    assert report.qualified_handoff_candidates == []
    assert report.qualification.status == "INSUFFICIENT_RELEVANT_EVIDENCE"
    assert report.qualification.reason_code == "NO_QUALIFIED_CLUSTER"
    assert report.market_opportunities == [], "Attention never carries an Opportunity Index"
    visible = {row["cluster_id"]: row for row in report.cluster_qualification}
    assert visible[str(adjacent)]["CONTEXT_ONLY"] == 2 and not visible[str(adjacent)]["handoff_eligible"]
    assert visible[str(noise)]["EXCLUDED_IRRELEVANT"] == 2


def test_attention_one_source_seen_twice_is_not_two_independent_sources():
    cluster, source = uuid4(), uuid4()
    signals = [
        _attention_signal("Phần mềm quản lý bán hàng cho tiệm tạp hóa", cluster, source),
        _attention_signal("Phần mềm quản lý bán hàng cho tiệm tạp hóa (bản mới)", cluster, source),
    ]
    report = _attention_report(
        signals, [_judged(s, "QUALIFIED_SUPPORT", "DIRECT_TO_FRAME") for s in signals]
    )

    assert report.handoff_status == HandoffStatus.NO_QUALIFIED_CANDIDATE.value


def test_attention_two_source_direct_support_is_the_only_candidate_even_through_synonyms():
    supported, adjacent = uuid4(), uuid4()
    signals = [
        # Neither title repeats a mission keyword: relevance was judged, not string-matched.
        _attention_signal("Chủ tiệm tạp hóa hỏi phần mềm quản lý kho nào dễ dùng", supported),
        _attention_signal("Review phần mềm bán hàng cho shop nhỏ sau 3 tháng", supported),
        _attention_signal("AI xây website bán hàng", adjacent),
        _attention_signal("AI tạo landing page", adjacent),
    ]
    judgments = [
        _judged(signals[0], "QUALIFIED_SUPPORT", "DIRECT_TO_FRAME", purpose="VOC"),
        _judged(signals[1], "QUALIFIED_SUPPORT", "DIRECT_TO_FRAME"),
        _judged(signals[2], "CONTEXT_ONLY", "ADJACENT_ONLY"),
        _judged(signals[3], "CONTEXT_ONLY", "ADJACENT_ONLY"),
    ]

    report = _attention_report(signals, judgments)

    assert report.handoff_status == HandoffStatus.QUALIFIED_CANDIDATE_AVAILABLE.value
    assert [c["cluster_id"] for c in report.qualified_handoff_candidates] == [str(supported)]
    candidate = report.qualified_handoff_candidates[0]
    assert candidate["independent_sources"] == 2 and candidate["qualified_observations"] == 2
    assert {c.observation_id for c in candidate["citations"]} == {
        str(signals[0].observation_id), str(signals[1].observation_id),
    }
    assert report.qualification.status == "READY"
    assert report.market_opportunities == []


def test_attention_handoff_waits_for_qualification_and_refuses_on_evaluator_failure():
    cluster = uuid4()
    signals = [_attention_signal("a", cluster), _attention_signal("b", cluster)]

    pending = _attention_report(signals, [_judged(signals[0], "QUALIFIED_SUPPORT", "DIRECT_TO_FRAME")])
    failed = _attention_report(signals, [
        _judged(signals[0], "QUALIFIED_SUPPORT", "DIRECT_TO_FRAME"),
        _judged(signals[1], "UNASSESSED", "EVALUATOR_UNAVAILABLE"),
    ])

    assert pending.handoff_status == HandoffStatus.QUALIFICATION_REQUIRED.value
    assert failed.handoff_status == HandoffStatus.UNAVAILABLE.value
    assert pending.qualified_handoff_candidates == failed.qualified_handoff_candidates == []


def test_select_handoff_candidates_never_returns_a_least_bad_cluster():
    assert select_handoff_candidates({}) == []
    one = _qualified("SUPPLY")
    assert select_handoff_candidates({"c1": [one], "c2": [_qualified("SUPPLY")]}) == []
