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
