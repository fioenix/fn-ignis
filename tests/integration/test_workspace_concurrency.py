"""Two runs in one research workspace must not overwrite each other.

The foundational half of that contract: one writer per mission, and an exclusive journal name
per run even when two runs start inside the same second. The wider concurrency hardening --
independent progress for unrelated missions, and recovery readback -- is P2 work and is not
covered here.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import MissionWriterConflictError, ResearchSurface
from ignis.infrastructure.persistence import workspace_repository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


@pytest.fixture
def host_workspace(tmp_path) -> Path:
    root = tmp_path / "host-project"
    root.mkdir()
    return root


@pytest.mark.asyncio
async def test_two_runs_starting_in_the_same_second_get_distinct_journals(
    repository_case, host_workspace, monkeypatch
):
    """The clock is frozen, because the collision only exists inside one second.

    Allocating twice and hoping both land in the same second is not a test of anything: on a
    slow run the two straddle a second boundary, each starts its sequence at 001, and the
    assertion fails while the allocator was right the whole time. Freezing the clock is what the
    quickstart asks for and what makes the invariant deterministic on both backends.
    """
    frozen = datetime(2026, 9, 21, 10, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(workspace_repository, "_utc_now", lambda: frozen)

    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await use_case.confirm(
        await use_case.propose(host_workspace, "AI customer service"), confirmation=True
    )

    mission = ResearchMission(
        title="AI customer service",
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository_case.repository.save_mission(mission)

    first = await store.allocate_run_journal(workspace, mission.id, run_id=uuid4())
    original_bytes = first.journal_path.read_bytes()
    second = await store.allocate_run_journal(workspace, mission.id, run_id=uuid4())

    # Same second, same stamp, so only the fixed-width sequence keeps the two names apart.
    assert first.journal_path != second.journal_path
    assert (first.sequence, second.sequence) == (1, 2)
    assert "20260921-103000-001" in first.journal_path.name
    assert "20260921-103000-002" in second.journal_path.name
    # The earlier run's evidence is still exactly what it wrote.
    assert first.journal_path.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_a_mission_has_at_most_one_active_writer(repository_case, host_workspace):
    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await use_case.confirm(
        await use_case.propose(host_workspace, "AI customer service"), confirmation=True
    )

    mission = ResearchMission(
        title="AI customer service",
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository_case.repository.save_mission(mission)

    first_run, second_run = uuid4(), uuid4()
    assert await store.claim_mission_writer(mission.id, first_run) is True
    assert await store.claim_mission_writer(mission.id, second_run) is False

    # A run that does not hold the claim cannot release it either.
    await store.release_mission_writer(mission.id, second_run)
    assert await store.claim_mission_writer(mission.id, second_run) is False

    await store.release_mission_writer(mission.id, first_run)
    assert await store.claim_mission_writer(mission.id, second_run) is True


# --- User Story 5: independent progress, one writer, recoverable runs --------

COMPLETE_BRIEF = {
    "decision": "Should we build a VN customer service assistant?",
    "target_user": "VN fashion retailers answering their own support inbox",
    "problem": "Support replies take hours and the sale is lost before anyone answers",
    "geo": "VN",
    "timeframe": "30d",
    "hypothesis": "VN fashion retailers will pay for sub-minute automated support replies",
    "falsifiers": ["No retailer names reply latency among their top three costs"],
}


class GatedRegistry:
    """A connector pass that can be held open, so two runs genuinely overlap.

    Sleeping for a while would make the overlap a matter of timing, which is how a concurrency
    test passes on a fast machine and proves nothing. The gate makes the window explicit: the
    pass does not return until the test says so.
    """

    def __init__(self, signal_factory, gate=None):
        self._signal_factory = signal_factory
        self.gate = gate
        self.started = asyncio.Event()
        self.calls = 0

    async def search_across_all(self, keywords=None, **_kwargs):
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        return self._signal_factory(keywords or ["ai customer service"])


def _signals_for(keywords):
    """One sighting per mission, distinguishable by the keyword that found it."""
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import GeoCode, PlatformType

    term = keywords[0]
    return [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title=f"{term} explained",
            metric_value=1000.0,
            growth_velocity=5.0,
            source_url=f"https://www.youtube.com/watch?v={abs(hash(term)) % 10**11:011d}",
            geo_code=GeoCode.VN,
            metadata={"keyword": term, "connector_surface": "youtube", "channel_title": term},
            captured_at=datetime.now(timezone.utc),
        )
    ]


def _executor(repository, store, registry):
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer

    return ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=SemanticClusterer(),
        workspace_store=store,
    )


async def _confirmed_workspace(repository, host_workspace, name="AI customer service"):
    store = WorkspaceRepository(repository=repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await use_case.confirm(
        await use_case.propose(host_workspace, name), confirmation=True
    )
    return store, workspace


async def _attention_mission(repository, workspace, title, seed):
    from ignis.application.use_cases.create_attention_mission import (
        CreateAttentionMissionUseCase,
    )

    store = WorkspaceRepository(repository=repository)
    return await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id, title=title, seed=seed
    )


@pytest.mark.asyncio
async def test_two_missions_of_one_research_run_at_the_same_time(
    repository_case, host_workspace
):
    """Unrelated missions must not wait for each other.

    Both passes are held open together and only then released, so the test fails if the second
    run cannot start until the first has finished -- which is what a research-wide lock would
    do.
    """
    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)

    first = await _attention_mission(repository, workspace, "First question", "ai chatbot")
    second = await _attention_mission(repository, workspace, "Second question", "live chat")

    gate = asyncio.Event()
    registries = [GatedRegistry(_signals_for, gate), GatedRegistry(_signals_for, gate)]
    runs = [
        asyncio.create_task(_executor(repository, store, registries[0]).execute(first.id)),
        asyncio.create_task(_executor(repository, store, registries[1]).execute(second.id)),
    ]
    # Both are inside their connector pass before either is allowed to finish.
    await asyncio.wait_for(
        asyncio.gather(*(r.started.wait() for r in registries)), timeout=10
    )
    gate.set()
    results = await asyncio.wait_for(asyncio.gather(*runs), timeout=30)

    assert [r["status"] for r in results] == ["COMPLETED", "COMPLETED"]
    assert results[0]["run"]["run_id"] != results[1]["run"]["run_id"]

    # Each mission kept its own evidence and its own journal.
    first_evidence = {s.raw_title for s in await repository.get_mission_signals(first.id)}
    second_evidence = {s.raw_title for s in await repository.get_mission_signals(second.id)}
    assert first_evidence and second_evidence
    assert first_evidence.isdisjoint(second_evidence)
    assert (await repository.get_mission(first.id)).status == "COMPLETED"
    assert (await repository.get_mission(second.id)).status == "COMPLETED"
    assert len(await store.list_run_journals(first.id)) == 1
    assert len(await store.list_run_journals(second.id)) == 1
    assert await store.get_mission_writer_claim(first.id) is None
    assert await store.get_mission_writer_claim(second.id) is None


@pytest.mark.asyncio
async def test_a_second_run_of_one_mission_is_refused_while_the_first_is_writing(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)
    mission = await _attention_mission(repository, workspace, "One question", "ai chatbot")

    gate = asyncio.Event()
    holder = GatedRegistry(_signals_for, gate)
    intruder = GatedRegistry(_signals_for)
    first = asyncio.create_task(_executor(repository, store, holder).execute(mission.id))
    await asyncio.wait_for(holder.started.wait(), timeout=10)

    with pytest.raises(MissionWriterConflictError) as excinfo:
        await _executor(repository, store, intruder).execute(mission.id)
    assert str(mission.id) in str(excinfo.value)
    # The refused run never reached a connector, so it collected nothing to overwrite with.
    assert intruder.calls == 0

    gate.set()
    result = await asyncio.wait_for(first, timeout=30)
    assert result["status"] == "COMPLETED"

    # One run, one journal, and the evidence is the one the holder wrote.
    journals = await store.list_run_journals(mission.id)
    assert len(journals) == 1
    assert journals[0].run_id == UUID(result["run"]["run_id"])
    assert journals[0].status == "COMPLETED"
    assert await repository.get_mission_signals(mission.id)
    assert await store.get_mission_writer_claim(mission.id) is None


@pytest.mark.asyncio
async def test_a_failed_run_frees_the_mission_and_keeps_the_evidence_it_had(
    repository_case, host_workspace
):
    """The mission is not locked out by the run that broke, and keeps what it already held."""
    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)
    mission = await _attention_mission(repository, workspace, "One question", "ai chatbot")

    await _executor(repository, store, GatedRegistry(_signals_for)).execute(mission.id)
    evidence_before = {
        str(s.observation_id) for s in await repository.get_mission_signals(mission.id)
    }
    assert evidence_before

    class _Exploding:
        async def search_across_all(self, **_kwargs):
            raise RuntimeError("connector pass failed")

    with pytest.raises(RuntimeError):
        await _executor(repository, store, _Exploding()).execute(mission.id)

    assert (await repository.get_mission(mission.id)).status == "FAILED"
    assert await store.get_mission_writer_claim(mission.id) is None
    journals = await store.list_run_journals(mission.id)
    assert [j.status for j in journals] == ["FAILED", "COMPLETED"]
    # The failed pass wrote nothing over the evidence the mission already had.
    assert {
        str(s.observation_id) for s in await repository.get_mission_signals(mission.id)
    } == evidence_before
    # And the mission can be run again.
    assert (
        await _executor(repository, store, GatedRegistry(_signals_for)).execute(mission.id)
    )["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_a_run_reads_back_with_its_mission_run_status_and_completion(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)
    mission = await _attention_mission(repository, workspace, "One question", "ai chatbot")

    result = await _executor(repository, store, GatedRegistry(_signals_for)).execute(mission.id)
    journal = await store.latest_run_journal(mission.id)

    assert journal.mission_id == mission.id
    assert journal.workspace_id == workspace.workspace_id
    assert journal.run_id == UUID(result["run"]["run_id"])
    assert journal.status == "COMPLETED"
    assert journal.started_at is not None and journal.completed_at is not None
    assert journal.completed_at >= journal.started_at

    on_disk = json.loads(journal.journal_path.read_text(encoding="utf-8"))
    assert on_disk["status"] == "COMPLETED"
    assert on_disk["mission_id"] == str(mission.id)
    assert on_disk["run_id"] == str(journal.run_id)

    # An interrupted run is a different readback: no completion is claimed for it.
    orphan_run = uuid4()
    await store.allocate_run_journal(workspace, mission.id, run_id=orphan_run)
    interrupted = await store.latest_run_journal(mission.id)
    assert (interrupted.run_id, interrupted.status) == (orphan_run, "STARTED")
    assert interrupted.completed_at is None


@pytest.mark.asyncio
async def test_a_market_run_is_refused_a_second_writer_through_the_mcp_contract(
    repository_case, host_workspace, monkeypatch
):
    """The conflict reaches the Agent as a result, not as a transport error."""
    from ignis.application.use_cases.create_market_revision import CreateMarketRevisionUseCase
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)
    mission, _revision = await CreateMarketRevisionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["ai customer service"],
        **COMPLETE_BRIEF,
    )

    gate = asyncio.Event()
    holder = GatedRegistry(_signals_for, gate)
    components = {
        "repository": repository,
        "workspace_store": store,
        "execute_mission_use_case": _executor(repository, store, holder),
    }
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    first = asyncio.create_task(
        mcp_server.handle_execute_mission_ingress(str(mission.id))
    )
    await asyncio.wait_for(holder.started.wait(), timeout=10)

    intruder = GatedRegistry(_signals_for)
    components["execute_mission_use_case"] = _executor(repository, store, intruder)
    conflict = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))

    assert conflict["status"] == "CONFLICT"
    assert conflict["mission_id"] == str(mission.id)
    assert conflict["workspace_id"] == str(workspace.workspace_id)
    assert conflict["active_run_id"]
    assert intruder.calls == 0

    components["execute_mission_use_case"] = _executor(repository, store, holder)
    gate.set()
    completed = json.loads(await asyncio.wait_for(first, timeout=30))
    assert completed["status"] == "COMPLETED"
    # The run that was refused wrote no journal of its own, and the holder kept the slot it
    # was named by.
    assert completed["run"]["run_id"] == conflict["active_run_id"]
    assert len(await store.list_run_journals(mission.id)) == 1


@pytest.mark.asyncio
async def test_two_distinct_missions_stay_independently_executable_through_the_contract(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)
    first = await _attention_mission(repository, workspace, "First question", "ai chatbot")
    second = await _attention_mission(repository, workspace, "Second question", "live chat")

    components = {
        "repository": repository,
        "workspace_store": store,
        "execute_mission_use_case": _executor(
            repository, store, GatedRegistry(_signals_for)
        ),
    }
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    one = json.loads(await mcp_server.handle_execute_mission_ingress(str(first.id)))
    two = json.loads(await mcp_server.handle_execute_mission_ingress(str(second.id)))
    assert (one["status"], two["status"]) == ("COMPLETED", "COMPLETED")
    assert one["run"]["run_id"] != two["run"]["run_id"]


# --- Recovery from a writer that died holding the slot ----------------------

def _recovery_components(repository, store, registry):
    """The handlers the recovery path actually uses, over the real database."""
    return {
        "repository": repository,
        "workspace_store": store,
        "execute_mission_use_case": _executor(repository, store, registry),
    }


@pytest.mark.asyncio
async def test_a_claim_left_by_a_dead_run_is_released_by_naming_that_run(
    repository_case, host_workspace, monkeypatch
):
    """The recovery an operator can actually reach, end to end.

    A process that died holding the slot leaves a claim nothing expires, by design. What makes
    that safe rather than terminal is that the claim is readable and releasable by name through
    the same boundary the conflict was reported on.
    """
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)
    mission = await _attention_mission(repository, workspace, "One question", "ai chatbot")

    # A run that took the slot and never came back.
    dead_run = uuid4()
    assert await store.claim_mission_writer(mission.id, dead_run) is True

    components = _recovery_components(repository, store, GatedRegistry(_signals_for))
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    # 1. The stale claim is visible, and it is what blocks the mission.
    blocked = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))
    assert blocked["status"] == "CONFLICT"
    assert blocked["active_run_id"] == str(dead_run)
    assert blocked["active_since"]
    assert "release_mission_writer" in blocked["note"]

    # 2. A different run id cannot take the claim away from the run that holds it.
    wrong = json.loads(
        await mcp_server.handle_release_mission_writer(str(mission.id), str(uuid4()))
    )
    assert wrong["status"] == "CONFLICT"
    assert wrong["active_run_id"] == str(dead_run)
    still_held = await store.get_mission_writer_claim(mission.id)
    assert still_held is not None and still_held.run_id == dead_run

    # 3. The exact run id releases it.
    released = json.loads(
        await mcp_server.handle_release_mission_writer(str(mission.id), str(dead_run))
    )
    assert released["status"] == "RELEASED"
    assert released["mission_id"] == str(mission.id)
    assert released["workspace_id"] == str(workspace.workspace_id)
    assert released["run_id"] == str(dead_run)
    assert await store.get_mission_writer_claim(mission.id) is None

    # 4. Releasing again says so plainly rather than pretending it did something.
    again = json.loads(
        await mcp_server.handle_release_mission_writer(str(mission.id), str(dead_run))
    )
    assert again["status"] == "NOT_FOUND"

    # 5. The mission runs again, and the recovered run writes its own journal.
    result = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))
    assert result["status"] == "COMPLETED"
    assert result["run"]["run_id"] != str(dead_run)
    assert await store.get_mission_writer_claim(mission.id) is None


@pytest.mark.asyncio
async def test_releasing_the_writer_of_an_active_run_needs_that_run_s_own_id(
    repository_case, host_workspace, monkeypatch
):
    """Release is scoped to the holder, so it cannot be used to evict a run that is working."""
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)
    mission = await _attention_mission(repository, workspace, "One question", "ai chatbot")

    gate = asyncio.Event()
    holder = GatedRegistry(_signals_for, gate)
    components = _recovery_components(repository, store, holder)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    run = asyncio.create_task(mcp_server.handle_execute_mission_ingress(str(mission.id)))
    await asyncio.wait_for(holder.started.wait(), timeout=10)
    active = await store.get_mission_writer_claim(mission.id)
    assert active is not None

    refused = json.loads(
        await mcp_server.handle_release_mission_writer(str(mission.id), str(uuid4()))
    )
    assert refused["status"] == "CONFLICT"
    assert (await store.get_mission_writer_claim(mission.id)).run_id == active.run_id

    gate.set()
    completed = json.loads(await asyncio.wait_for(run, timeout=30))
    assert completed["status"] == "COMPLETED"
    assert completed["run"]["run_id"] == str(active.run_id)


@pytest.mark.asyncio
async def test_a_mission_whose_research_cannot_be_read_is_refused_as_a_result(
    repository_case, host_workspace, monkeypatch
):
    """An unaddressable scope is a refusal the Agent can read, not a transport error.

    The missing workspace is injected at the store rather than written as a row, because the
    schema will not hold that row: research_missions.workspace_id is a foreign key, and the
    cascade takes the mission with the research. What remains reachable is the read returning
    nothing -- a second host that dropped the research between this mission's creation and its
    run -- and that is the case the handler has to answer for.

    Nothing may run first: evidence written under a workspace nothing can address again is
    evidence lost in place.
    """
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _confirmed_workspace(repository, host_workspace)
    mission = await _attention_mission(repository, workspace, "One question", "ai chatbot")

    async def _research_is_gone(_workspace_id):
        return None

    monkeypatch.setattr(store, "get_research_workspace", _research_is_gone)

    registry = GatedRegistry(_signals_for)
    components = _recovery_components(repository, store, registry)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    payload = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))

    assert payload["status"] == "BLOCKED"
    assert payload["mission_id"] == str(mission.id)
    assert payload["workspace_id"] == str(workspace.workspace_id)
    assert str(workspace.workspace_id) in payload["error"]
    # No probe, no claim, no journal: the refusal happened before any of them.
    assert registry.calls == 0
    assert await store.get_mission_writer_claim(mission.id) is None
    assert await store.list_run_journals(mission.id) == []
    assert (await repository.get_mission(mission.id)).status == "PENDING"
