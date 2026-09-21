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
