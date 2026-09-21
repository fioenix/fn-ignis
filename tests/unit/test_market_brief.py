"""The Market Brief is the contract that authorizes a Market mission.

Seven fields, confirmed by a requester, immutable once confirmed. Everything here is about what
the domain refuses: an incomplete Brief, an empty falsifier list, and a mutation of a revision
that evidence has already been attached to.
"""

import asyncio
import dataclasses
from uuid import uuid4

import pytest
import pytest_asyncio

from ignis.application.use_cases.create_market_revision import CreateMarketRevisionUseCase
from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.research_workspace import (
    REQUIRED_BRIEF_FIELDS,
    IncompleteMarketBriefError,
    InvalidMissionLineageError,
    MarketBriefRevision,
    MissionLineage,
    ResearchSurface,
    ResearchWorkspace,
    SurfaceViolationError,
    WorkspaceScopeMismatchError,
    missing_brief_fields,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

COMPLETE_PAYLOAD = {
    "decision": "Should we test a VN-focused customer service assistant?",
    "target_user": "VN fashion retailers running their own support inbox",
    "problem": "Support replies take hours and lose the sale",
    "geo": "VN",
    "timeframe": "30d",
    "hypothesis": "VN retailers will pay for an assistant that answers in under a minute",
    "falsifiers": ["No retailer reports reply latency as a top-three cost"],
}


def _revision(**overrides):
    payload = {**COMPLETE_PAYLOAD, **overrides}
    return MarketBriefRevision(confirmed_by="requester@example.com", **payload)


def test_required_field_list_is_the_seven_the_specification_names():
    assert REQUIRED_BRIEF_FIELDS == (
        "decision",
        "target_user",
        "problem",
        "geo",
        "timeframe",
        "hypothesis",
        "falsifiers",
    )


@pytest.mark.parametrize("field_name", REQUIRED_BRIEF_FIELDS)
def test_every_required_field_is_named_when_it_is_missing(field_name):
    payload = {k: v for k, v in COMPLETE_PAYLOAD.items() if k != field_name}
    assert missing_brief_fields(payload) == [field_name]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_text_field_counts_as_missing_rather_than_as_an_answer(blank):
    assert "hypothesis" in missing_brief_fields({**COMPLETE_PAYLOAD, "hypothesis": blank})


def test_falsifiers_holding_only_blank_entries_is_not_a_useful_falsifier():
    assert "falsifiers" in missing_brief_fields({**COMPLETE_PAYLOAD, "falsifiers": ["  ", ""]})


def test_constructing_an_incomplete_revision_names_every_missing_field():
    with pytest.raises(IncompleteMarketBriefError) as excinfo:
        MarketBriefRevision(
            confirmed_by="requester",
            decision="",
            target_user="",
            problem=COMPLETE_PAYLOAD["problem"],
            geo="VN",
            timeframe="30d",
            hypothesis=COMPLETE_PAYLOAD["hypothesis"],
            falsifiers=[],
        )
    assert excinfo.value.missing_fields == ["decision", "target_user", "falsifiers"]


def test_a_confirmed_revision_cannot_be_mutated():
    revision = _revision()
    with pytest.raises(dataclasses.FrozenInstanceError):
        revision.hypothesis = "something else"


def test_falsifiers_are_stored_as_an_immutable_sequence():
    revision = _revision()
    assert revision.falsifiers == ("No retailer reports reply latency as a top-three cost",)
    assert isinstance(revision.falsifiers, tuple)


def test_confirmation_metadata_is_recorded_on_the_revision():
    revision = _revision()
    assert revision.confirmed_by == "requester@example.com"
    assert revision.confirmed_at.tzinfo is not None
    assert revision.revision_number == 1


def test_a_revision_confirms_without_a_requester_identity_being_optional():
    with pytest.raises(IncompleteMarketBriefError) as excinfo:
        MarketBriefRevision(confirmed_by="  ", **COMPLETE_PAYLOAD)
    assert excinfo.value.missing_fields == ["confirmed_by"]


def test_the_workspace_store_offers_no_way_to_persist_a_draft():
    """There is no draft operation, so an abandoned framing cannot leave a record behind.

    This is a structural check rather than a behavioural one on purpose. The guarantee the
    specification makes is about what fn-ignis is unable to store, and an absent operation is
    the only form of that guarantee a later caller cannot work around.
    """
    from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore

    operations = {name for name in dir(IResearchWorkspaceStore) if not name.startswith("_")}
    forbidden = [
        name
        for name in operations
        if any(word in name for word in ("draft", "transcript", "question", "answer"))
    ]
    assert forbidden == []
    assert "save_brief_revision" in operations


def test_an_edit_before_confirmation_is_just_a_different_payload():
    """Editing happens in the host Agent's context, so the domain sees only the final answer."""
    edited = _revision(hypothesis="VN retailers will pay only when latency costs them a sale")
    assert edited.hypothesis.endswith("costs them a sale")
    assert edited.revision_number == 1


# --- User Story 4: handoff lineage and immutable revisions -------------------


async def _open_workspace(repository, tmp_path, slug="ai-customer-service"):
    store = WorkspaceRepository(repository=repository)
    workspace = await store.save_research_workspace(
        ResearchWorkspace(slug=slug, root_path=tmp_path / slug)
    )
    return store, workspace


async def _cluster(repository, name="ai customer service"):
    cluster = TopicCluster(canonical_name=name)
    await repository.save_clusters([cluster])
    return cluster.id


async def _attention_mission(repository, workspace, cluster_id=None):
    """An Attention mission, optionally holding one observation inside a selected cluster."""
    mission = ResearchMission(
        title="What is gaining attention in VN customer service",
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository.create_mission(mission)
    if cluster_id is not None:
        signal = TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="ai customer service",
            metric_value=80.0,
            geo_code=GeoCode.VN,
            cluster_id=cluster_id,
            mission_id=mission.id,
            metadata={"keyword": "ai customer service"},
        )
        await repository.save_signals([signal])
        await repository.assign_observation_clusters([signal])
        await repository.attach_mission_evidence(mission.id, [signal])
    return mission


def _revision_use_case(repository, store):
    return CreateMarketRevisionUseCase(repository=repository, store=store)


@pytest_asyncio.fixture
async def sqlite_repository():
    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    await repository._ensure_schema()
    try:
        yield repository
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_a_handoff_records_the_attention_parent_as_context_lineage(
    sqlite_repository, tmp_path
):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    attention = await _attention_mission(sqlite_repository, workspace)

    mission, revision = await _revision_use_case(sqlite_repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        lineage=MissionLineage(parent_attention_mission_id=attention.id),
        **COMPLETE_PAYLOAD,
    )

    assert mission.surface == ResearchSurface.MARKET.value
    assert mission.parent_attention_mission_id == attention.id
    assert mission.brief_revision_id == revision.brief_revision_id
    # The Attention mission is context, and nothing about it changed.
    unchanged = await sqlite_repository.get_mission(attention.id)
    assert unchanged.surface == ResearchSurface.ATTENTION.value
    assert unchanged.brief_revision_id is None


@pytest.mark.asyncio
async def test_a_selected_cluster_the_attention_mission_observed_is_recorded(
    sqlite_repository, tmp_path
):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    cluster_id = await _cluster(sqlite_repository)
    attention = await _attention_mission(sqlite_repository, workspace, cluster_id=cluster_id)

    mission, _revision = await _revision_use_case(sqlite_repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        lineage=MissionLineage(
            parent_attention_mission_id=attention.id, parent_cluster_id=cluster_id
        ),
        **COMPLETE_PAYLOAD,
    )
    assert mission.parent_cluster_id == cluster_id


@pytest.mark.asyncio
async def test_a_parent_mission_from_another_workspace_is_refused(sqlite_repository, tmp_path):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    _other_store, other = await _open_workspace(sqlite_repository, tmp_path, slug="other-research")
    foreign = await _attention_mission(sqlite_repository, other)

    with pytest.raises(WorkspaceScopeMismatchError):
        await _revision_use_case(sqlite_repository, store).execute(
            workspace_id=workspace.workspace_id,
            confirmed_by="requester",
            lineage=MissionLineage(parent_attention_mission_id=foreign.id),
            **COMPLETE_PAYLOAD,
        )
    assert await store.list_workspace_missions(workspace.workspace_id) == []


@pytest.mark.asyncio
async def test_a_parent_that_is_not_an_attention_mission_is_refused(sqlite_repository, tmp_path):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    use_case = _revision_use_case(sqlite_repository, store)
    market, _revision = await use_case.execute(
        workspace_id=workspace.workspace_id, confirmed_by="requester", **COMPLETE_PAYLOAD
    )

    with pytest.raises(SurfaceViolationError):
        await use_case.execute(
            workspace_id=workspace.workspace_id,
            confirmed_by="requester",
            lineage=MissionLineage(parent_attention_mission_id=market.id),
            **COMPLETE_PAYLOAD,
        )


@pytest.mark.asyncio
async def test_a_parent_mission_that_does_not_exist_is_refused(sqlite_repository, tmp_path):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    with pytest.raises(InvalidMissionLineageError):
        await _revision_use_case(sqlite_repository, store).execute(
            workspace_id=workspace.workspace_id,
            confirmed_by="requester",
            lineage=MissionLineage(parent_attention_mission_id=uuid4()),
            **COMPLETE_PAYLOAD,
        )


@pytest.mark.asyncio
async def test_a_cluster_the_attention_mission_never_observed_is_refused(
    sqlite_repository, tmp_path
):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    attention = await _attention_mission(
        sqlite_repository, workspace, cluster_id=await _cluster(sqlite_repository)
    )
    unrelated = await _cluster(sqlite_repository, name="unrelated topic")

    with pytest.raises(InvalidMissionLineageError):
        await _revision_use_case(sqlite_repository, store).execute(
            workspace_id=workspace.workspace_id,
            confirmed_by="requester",
            lineage=MissionLineage(
                parent_attention_mission_id=attention.id, parent_cluster_id=unrelated
            ),
            **COMPLETE_PAYLOAD,
        )


@pytest.mark.asyncio
async def test_a_cluster_without_the_mission_it_came_from_is_refused(sqlite_repository, tmp_path):
    """A cluster identifier alone does not say which Attention run selected it."""
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    with pytest.raises(InvalidMissionLineageError):
        await _revision_use_case(sqlite_repository, store).execute(
            workspace_id=workspace.workspace_id,
            confirmed_by="requester",
            lineage=MissionLineage(parent_cluster_id=uuid4()),
            **COMPLETE_PAYLOAD,
        )


@pytest.mark.asyncio
async def test_a_changed_brief_creates_a_new_revision_and_leaves_the_first_one_intact(
    sqlite_repository, tmp_path
):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    use_case = _revision_use_case(sqlite_repository, store)

    first_mission, first = await use_case.execute(
        workspace_id=workspace.workspace_id, confirmed_by="requester", **COMPLETE_PAYLOAD
    )
    second_mission, second = await use_case.execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        previous_mission_id=first_mission.id,
        **{**COMPLETE_PAYLOAD, "hypothesis": "Only retailers above 500 orders a month will pay"},
    )

    assert second.revision_number == first.revision_number + 1
    assert second.brief_revision_id != first.brief_revision_id
    assert second_mission.id != first_mission.id
    assert second_mission.brief_revision_id == second.brief_revision_id

    # The first revision is read back exactly as it was confirmed.
    stored_first = await store.get_brief_revision_for_mission(first_mission.id)
    assert stored_first.hypothesis == COMPLETE_PAYLOAD["hypothesis"]
    assert stored_first.revision_number == first.revision_number
    assert stored_first.brief_revision_id == first.brief_revision_id


@pytest.mark.asyncio
async def test_a_revision_inherits_the_attention_lineage_of_the_mission_it_revises(
    sqlite_repository, tmp_path
):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    attention = await _attention_mission(sqlite_repository, workspace)
    use_case = _revision_use_case(sqlite_repository, store)

    first, _ = await use_case.execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        lineage=MissionLineage(parent_attention_mission_id=attention.id),
        **COMPLETE_PAYLOAD,
    )
    second, _ = await use_case.execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        previous_mission_id=first.id,
        **{**COMPLETE_PAYLOAD, "hypothesis": "A narrower hypothesis"},
    )
    assert second.parent_attention_mission_id == attention.id


@pytest.mark.asyncio
async def test_a_previous_mission_from_another_workspace_cannot_be_revised(
    sqlite_repository, tmp_path
):
    store, workspace = await _open_workspace(sqlite_repository, tmp_path)
    other_store, other = await _open_workspace(sqlite_repository, tmp_path, slug="other-research")
    foreign, _ = await _revision_use_case(sqlite_repository, other_store).execute(
        workspace_id=other.workspace_id, confirmed_by="requester", **COMPLETE_PAYLOAD
    )

    with pytest.raises(WorkspaceScopeMismatchError):
        await _revision_use_case(sqlite_repository, store).execute(
            workspace_id=workspace.workspace_id,
            confirmed_by="requester",
            previous_mission_id=foreign.id,
            **COMPLETE_PAYLOAD,
        )


@pytest.mark.asyncio
async def test_revision_numbers_are_allocated_once_when_two_callers_confirm_together(tmp_path):
    """The number is taken inside the write, not read before it.

    Reading the maximum and then inserting leaves a window in which two confirmations see the
    same number; the loser used to fail on the unique constraint and report the Brief as already
    confirmed, which is not what happened.
    """
    repository = SqliteTrendRepository(str(tmp_path / "revisions.sqlite"))
    await repository._ensure_schema()
    try:
        store, workspace = await _open_workspace(repository, tmp_path)
        use_case = _revision_use_case(repository, store)
        results = await asyncio.gather(
            *(
                use_case.execute(
                    workspace_id=workspace.workspace_id,
                    confirmed_by="requester",
                    **{**COMPLETE_PAYLOAD, "hypothesis": f"Variant {n}"},
                )
                for n in range(4)
            )
        )
        numbers = sorted(revision.revision_number for _mission, revision in results)
        assert numbers == [1, 2, 3, 4]
        assert await store.next_brief_revision_number(workspace.workspace_id) == 5
    finally:
        await repository.close()
