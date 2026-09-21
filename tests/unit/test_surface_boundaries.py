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
