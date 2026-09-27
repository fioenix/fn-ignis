"""Decision-grade evidence qualification, against both real storage backends.

Every contract here runs once on SQLite and once on PostgreSQL through the `repository_case`
fixture. Only external connectors and the host Agent's semantic judgment are replaced; storage,
mission execution, qualification, sufficiency policy and analysis are the production paths,
because the claims under test are claims about what those paths persist and refuse.
"""

import dataclasses
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ignis.application.ports.research_workspace_port import RunJournal
from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_attention_mission import (
    CreateAttentionMissionUseCase,
)
from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.domain.entities import TrendSignal
from ignis.domain.research_workspace import (
    EvidenceQualification,
    EvidenceQualificationConflictError,
    InvalidEvidenceQualificationError,
    MissionProbeOutcome,
    compute_frame_fingerprint,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

MARKET_BRIEF = {
    "decision": "Decide whether to pursue an AI operations copilot for small retailers",
    "target_user": "Owners of small Vietnamese retail stores",
    "problem": "Repeated manual store operations: stock counts, reorders and daily reports",
    "geo": "VN",
    "timeframe": "7d",
    "hypothesis": "Small VN retailers will adopt a lightweight AI copilot that removes repeated work",
    "falsifiers": ["No repeated operational pain is observed among small retailers"],
}
T0 = datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)


@pytest.fixture
def host_workspace(tmp_path):
    root = tmp_path / "host-project"
    root.mkdir()
    return root


async def _workspace(repository, host_workspace, name="AI retail copilot"):
    store = WorkspaceRepository(repository=repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    proposal = await use_case.propose(host_workspace, name)
    return store, await use_case.confirm(proposal, confirmation=True)


async def _market_mission(repository, store, workspace, keywords=("ai cho cửa hàng",), **brief):
    return await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=list(keywords),
        **{**MARKET_BRIEF, **brief},
    )


async def _attention_mission(repository, store, workspace, keywords=("ai cho cửa hàng",)):
    return await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="What is gaining attention around retail AI",
        keywords=list(keywords),
    )


def _signal(title, platform=PlatformType.YOUTUBE, external=None, metric=1000.0, **metadata):
    external = external or uuid4().hex[:11]
    urls = {
        PlatformType.YOUTUBE: f"https://www.youtube.com/watch?v={external:0<11}"[:43],
        PlatformType.GOOGLE_TRENDS: f"https://trends.google.com/trends/explore?q={external}",
        PlatformType.TIKTOK: f"https://www.tiktok.com/@shop/video/{abs(hash(external)) % 10**19:019d}",
    }
    return TrendSignal(
        platform=platform,
        raw_title=title,
        metric_value=metric,
        source_url=urls.get(platform, f"https://example.test/{external}"),
        geo_code=GeoCode.VN,
        captured_at=T0,
        metadata={"connector_surface": platform.value, **metadata},
    )


async def _hold(repository, mission, signals):
    """Write signals as the mission's own evidence, the way ingress does, and read them back."""
    for signal in signals:
        signal.mission_id = mission.id
    await repository.save_signals(signals)
    return await repository.get_mission_signals(mission.id)


def _judge(mission, frame, observation_id, relation="QUALIFIED_SUPPORT", purpose="SUPPLY",
           reason="DIRECT_TO_FRAME", confidence=0.9, brief_revision_id=None):
    return EvidenceQualification(
        mission_id=mission.id,
        observation_id=observation_id,
        frame_fingerprint=frame,
        brief_revision_id=brief_revision_id,
        relation=relation,
        purpose=purpose,
        confidence=None if relation == "UNASSESSED" else confidence,
        reason_code=reason,
        judged_by="contract-test",
        model="fixture",
    )


async def _journal(store, workspace, mission, status, started_at, sequence):
    journal = RunJournal(
        run_id=uuid4(),
        mission_id=mission.id,
        workspace_id=workspace.workspace_id,
        journal_path=workspace.journal_dir / f"run-{sequence:03d}.json",
        sequence=sequence,
        status="STARTED",
        started_at=started_at,
    )
    await store.record_run_journal(journal)
    if status != "STARTED":
        await store.record_run_journal(
            dataclasses.replace(journal, status=status, completed_at=started_at + timedelta(minutes=1))
        )
    return journal


def _outcome(run_id, surface, status="EMPTY_NO_DATA", count=0, platform="youtube"):
    return MissionProbeOutcome(
        run_id=run_id,
        platform=platform,
        connector_surface=surface,
        status=status,
        signals_collected=count,
        query_fingerprint="q" * 64,
        completed_at=T0,
    )


# --- Phase 2: the storage contract for judgments ------------------------------------------------


@pytest.mark.asyncio
async def test_a_batch_of_judgments_is_stored_and_read_back_exactly(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission, brief = await _market_mission(repository, store, workspace)
    held = await _hold(repository, mission, [_signal("Quản lý kho cho cửa hàng nhỏ bằng AI"),
                                             _signal("Phim hành động mới nhất 2026")])
    frame = compute_frame_fingerprint(mission, brief)
    batch = [
        _judge(mission, frame, held[0].observation_id, brief_revision_id=brief.brief_revision_id),
        _judge(mission, frame, held[1].observation_id, relation="EXCLUDED_IRRELEVANT",
               purpose="SUPPLY", reason="FICTION_NEWS_OR_ENTERTAINMENT", confidence=0.97,
               brief_revision_id=brief.brief_revision_id),
    ]

    assert await store.save_evidence_qualifications(mission.id, batch) == 2
    stored = sorted(await store.list_evidence_qualifications(mission.id), key=lambda q: q.relation.value)

    assert [q.same_judgment(b) for q, b in zip(stored, sorted(batch, key=lambda q: q.relation.value))] == [True, True]
    assert all(q.created_at is not None for q in stored)


@pytest.mark.asyncio
async def test_a_byte_equivalent_replay_is_idempotent(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    held = await _hold(repository, mission, [_signal("AI quản lý bán hàng")])
    frame = compute_frame_fingerprint(mission, None)
    batch = [_judge(mission, frame, held[0].observation_id, confidence=0.8123456789)]

    await store.save_evidence_qualifications(mission.id, batch)
    assert await store.save_evidence_qualifications(mission.id, batch) == 1

    stored = await store.list_evidence_qualifications(mission.id)
    assert len(stored) == 1 and stored[0].confidence == 0.8123456789


@pytest.mark.asyncio
async def test_a_conflicting_rewrite_is_refused_and_writes_nothing_of_its_batch(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    held = await _hold(repository, mission, [_signal("AI quản lý bán hàng"), _signal("AI POS")])
    frame = compute_frame_fingerprint(mission, None)
    await store.save_evidence_qualifications(mission.id, [_judge(mission, frame, held[0].observation_id)])

    rewrite = [
        # New and valid on its own, so a partial write would leave it behind.
        _judge(mission, frame, held[1].observation_id),
        _judge(mission, frame, held[0].observation_id, relation="EXCLUDED_IRRELEVANT",
               purpose="SUPPLY", reason="KEYWORD_ONLY"),
    ]
    with pytest.raises(EvidenceQualificationConflictError):
        await store.save_evidence_qualifications(mission.id, rewrite)

    stored = await store.list_evidence_qualifications(mission.id)
    assert [(str(q.observation_id), q.relation.value) for q in stored] == [
        (str(held[0].observation_id), "QUALIFIED_SUPPORT")
    ]


@pytest.mark.asyncio
async def test_a_different_frame_for_a_judged_observation_is_a_conflict(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    held = await _hold(repository, mission, [_signal("AI quản lý bán hàng")])
    await store.save_evidence_qualifications(mission.id, [_judge(mission, "f" * 64, held[0].observation_id)])

    with pytest.raises(EvidenceQualificationConflictError):
        await store.save_evidence_qualifications(mission.id, [_judge(mission, "e" * 64, held[0].observation_id)])


@pytest.mark.asyncio
async def test_a_mission_cannot_judge_an_observation_it_does_not_hold(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    other = await _attention_mission(repository, store, workspace, keywords=("khác",))
    held = await _hold(repository, mission, [_signal("AI quản lý bán hàng")])
    foreign = await _hold(repository, other, [_signal("Một chủ đề khác")])
    frame = compute_frame_fingerprint(mission, None)

    with pytest.raises(InvalidEvidenceQualificationError):
        await store.save_evidence_qualifications(
            mission.id,
            [_judge(mission, frame, held[0].observation_id), _judge(mission, frame, foreign[0].observation_id)],
        )
    assert await store.list_evidence_qualifications(mission.id) == []


@pytest.mark.asyncio
async def test_pruning_evidence_removes_only_its_judgment_and_keeps_the_observation(
    repository_case, host_workspace
):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    held = await _hold(repository, mission, [_signal("AI quản lý bán hàng"), _signal("AI POS")])
    frame = compute_frame_fingerprint(mission, None)
    await store.save_evidence_qualifications(
        mission.id, [_judge(mission, frame, s.observation_id) for s in held]
    )

    await repository.prune_mission_evidence(mission.id, [held[1].observation_id])

    stored = await store.list_evidence_qualifications(mission.id)
    assert [str(q.observation_id) for q in stored] == [str(held[1].observation_id)]
    assert repository_case.counts()["observations"] == 2, "the immutable observation stays"


@pytest.mark.asyncio
async def test_no_existing_mission_evidence_is_backfilled_with_a_judgment(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission, _brief = await _market_mission(repository, store, workspace)
    await _hold(repository, mission, [_signal("AI quản lý bán hàng")])

    assert await store.list_evidence_qualifications(mission.id) == []


# --- Phase 2: the storage contract for probe outcomes -------------------------------------------


@pytest.mark.asyncio
async def test_the_latest_completed_run_owns_the_probe_outcomes(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    assert await store.get_latest_completed_probe_outcomes(mission.id) == []

    first = await _journal(store, workspace, mission, "COMPLETED", T0, 1)
    await store.record_probe_outcomes(first.run_id, [
        _outcome(first.run_id, "youtube"),
        _outcome(first.run_id, "tiktok", status="AUTH_REQUIRED", platform="tiktok"),
    ])
    failed = await _journal(store, workspace, mission, "FAILED", T0 + timedelta(hours=1), 2)
    await store.record_probe_outcomes(failed.run_id, [_outcome(failed.run_id, "youtube", "DEGRADED")])
    await _journal(store, workspace, mission, "STARTED", T0 + timedelta(hours=2), 3)

    latest = await store.get_latest_completed_probe_outcomes(mission.id)
    assert sorted((o.connector_surface, o.status.value) for o in latest) == [
        ("tiktok", "AUTH_REQUIRED"), ("youtube", "EMPTY_NO_DATA"),
    ]
    assert {o.run_id for o in latest} == {first.run_id}

    later = await _journal(store, workspace, mission, "COMPLETED", T0 + timedelta(hours=3), 4)
    await store.record_probe_outcomes(later.run_id, [_outcome(later.run_id, "youtube", "HEALTHY", 4)])
    latest = await store.get_latest_completed_probe_outcomes(mission.id)
    assert [(o.run_id, o.status.value, o.signals_collected) for o in latest] == [
        (later.run_id, "HEALTHY", 4)
    ]


@pytest.mark.asyncio
async def test_a_run_s_probe_outcomes_are_written_all_or_none(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    run = await _journal(store, workspace, mission, "COMPLETED", T0, 1)

    with pytest.raises(Exception):
        await store.record_probe_outcomes(run.run_id, [
            _outcome(run.run_id, "youtube"), _outcome(run.run_id, "youtube", "HEALTHY", 2),
        ])
    assert await store.get_latest_completed_probe_outcomes(mission.id) == []


@pytest.mark.asyncio
async def test_probe_outcomes_are_bound_to_their_run(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    run = await _journal(store, workspace, mission, "COMPLETED", T0, 1)

    with pytest.raises(InvalidEvidenceQualificationError):
        await store.record_probe_outcomes(run.run_id, [_outcome(uuid4(), "youtube")])
    assert await store.get_latest_completed_probe_outcomes(mission.id) == []


# --- Phase 2: a workspace run records its probe outcomes before it completes ---------------------


class OutcomeRegistry:
    """Replaces only the connectors: returns fixed signals and the outcome of every surface."""

    def __init__(self, signals, outcomes):
        self._signals = signals
        self._outcomes = outcomes
        self.calls = 0

    async def search_with_outcomes(self, **_kwargs):
        from ignis.infrastructure.connectors.registry import SearchPassResult

        self.calls += 1
        return SearchPassResult(
            signals=[dataclasses.replace(s, metadata=dict(s.metadata)) for s in self._signals],
            outcomes=list(self._outcomes),
        )


def _surface(surface, status, count=0, platform=None):
    from ignis.infrastructure.connectors.registry import SurfaceProbeResult

    return SurfaceProbeResult(
        platform=platform or surface, connector_surface=surface, status=status,
        signals_collected=count,
    )


def _executor(repository, store, registry, vocabulary_sync=None):
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer

    kwargs = {"vocabulary_sync": vocabulary_sync} if vocabulary_sync is not None else {}
    return ExecuteMissionUseCase(
        repository=repository, registry=registry, clusterer=SemanticClusterer(),
        workspace_store=store, **kwargs,
    )


@pytest.mark.asyncio
async def test_a_workspace_run_records_every_surface_outcome_before_it_completes(
    repository_case, host_workspace
):
    from ignis.domain.research_workspace import compute_query_fingerprint

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    registry = OutcomeRegistry(
        [_signal("ai cho cửa hàng", PlatformType.GOOGLE_TRENDS, keyword="ai cho cửa hàng",
                 connector_surface="google")],
        [
            _surface("google", "HEALTHY", 1),
            _surface("youtube", "EMPTY_NO_DATA"),
            _surface("tiktok", "AUTH_REQUIRED"),
        ],
    )

    result = await _executor(repository, store, registry).execute(mission.id)

    assert result["status"] == "COMPLETED"
    outcomes = await store.get_latest_completed_probe_outcomes(mission.id)
    assert sorted((o.connector_surface, o.status.value, o.signals_collected) for o in outcomes) == [
        ("google", "HEALTHY", 1), ("tiktok", "AUTH_REQUIRED", 0), ("youtube", "EMPTY_NO_DATA", 0),
    ]
    assert {str(o.run_id) for o in outcomes} == {result["run"]["run_id"]}
    assert {o.query_fingerprint for o in outcomes} == {
        compute_query_fingerprint(mission.keywords, mission.geo_code, mission.timeframe)
    }


@pytest.mark.asyncio
async def test_a_run_whose_outcomes_cannot_be_stored_does_not_complete(repository_case, host_workspace):
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)

    class RefusingStore(WorkspaceRepository):
        async def record_probe_outcomes(self, run_id, outcomes):
            raise RuntimeError("outcome storage is unavailable")

    refusing = RefusingStore(repository=repository)
    registry = OutcomeRegistry([_signal("ai cho cửa hàng")], [_surface("youtube", "HEALTHY", 1)])

    with pytest.raises(RuntimeError):
        await _executor(repository, refusing, registry).execute(mission.id)

    assert (await repository.get_mission(mission.id)).status == "FAILED"
    journals = await store.list_run_journals(mission.id)
    assert [j.status for j in journals] == ["FAILED"]
    assert await store.get_latest_completed_probe_outcomes(mission.id) == []

