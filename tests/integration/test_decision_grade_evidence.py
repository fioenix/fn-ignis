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
        journal_path=workspace.journal_dir / f"run-{mission.id}-{sequence:03d}.json",
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
        queried_keywords=("ai cho cửa hàng",),
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


def _surface(surface, status, count=0, platform=None, queried=("ai cho cửa hàng",), window="7d"):
    from ignis.infrastructure.connectors.registry import SurfaceProbeResult

    return SurfaceProbeResult(
        platform=platform or surface, connector_surface=surface, status=status,
        signals_collected=count, queried_keywords=tuple(queried), queried_window=window,
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
    for outcome in outcomes:
        assert outcome.queried_keywords == ("ai cho cửa hàng",)
        assert outcome.queried_window == "7d"
        assert outcome.query_fingerprint == compute_query_fingerprint(
            outcome.queried_keywords, mission.geo_code, outcome.queried_window
        ), "each surface is fingerprinted over the query and window it ran"


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


# --- User Story 1: the first mission after startup matches a warmed process ----------------------
#
# The post-v0.5 validation's first two missions got no TikTok signals although the database held
# the vocabulary: the TikTok grid rejects every card until its UI-noise vocabulary is registered,
# and only an analysis call had ever registered it. These plugins are the real classes with the
# network replaced, so the mechanism under test is the production one.

from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin  # noqa: E402
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry  # noqa: E402
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin  # noqa: E402

# Test data: persisted vocabulary, written through the same repository path an operator uses.
PERSISTED_VOCABULARY = {
    ("probe_templates_vn", "template"): ["{} là gì", "{} giá bao nhiêu"],
    ("tiktok_ui_noise", "notification"): ["thông báo", "tin nhắn"],
    ("retail_ops", "vernacular"): ["quản lý kho", "phần mềm bán hàng"],
}
TIKTOK_CARDS = ["Quản lý kho bằng AI cho shop nhỏ", "thông báo mới: có 3 tin nhắn"]


class OfflineGoogle(GoogleTrendsRssPlugin):
    """Google demand probe with the network removed: one signal per registered template."""

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=None, custom_timeframe=None, limit=20):
        return [
            _signal(pattern.format(keywords[0]), PlatformType.GOOGLE_TRENDS, keyword=keywords[0],
                    external=f"g{index}-{keywords[0]}")
            for index, pattern in enumerate(self._get_probe_patterns(geo.value))
        ]


class OfflineTikTok(TikTokPlugin):
    """The video grid with the browser removed: fixed cards through the real public-card guard."""

    async def keyword_search_blocked_reason(self):
        return None

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=None, custom_timeframe=None, limit=20):
        return [
            _signal(card, PlatformType.TIKTOK, external=f"t{index}", keyword=keywords[0])
            for index, card in enumerate(TIKTOK_CARDS)
            if not self._is_private_or_notification(card)
        ]


async def _persist_vocabulary(repository_case):
    """Persist the vocabulary a first mission depends on, on either backend.

    The shared PostgreSQL fixture applies the source/observation migrations only, so the
    vocabulary tables are created here from 003 exactly as shipped; SQLite's bootstrap already
    holds them. Returns the VN probe templates the database now holds.
    """
    from ignis.infrastructure.config.vocabulary_loader import load_market_vocabulary

    if repository_case.name == "postgres":
        import psycopg
        from conftest import REPO_SQL

        with psycopg.connect(repository_case.dsn) as conn:
            conn.execute((REPO_SQL / "003_market_lexicons.sql").read_text(encoding="utf-8"))
    repository = repository_case.repository
    for (domain, category), terms in PERSISTED_VOCABULARY.items():
        await repository.register_lexicon_terms(domain, terms, category)
    return (await load_market_vocabulary(repository)).probe_templates["VN"]


def _fresh_process(repository):
    """What a newly started server holds: engines and plugins that have registered nothing."""
    from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
    from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
    from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector
    from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

    google, tiktok = OfflineGoogle(), OfflineTikTok()
    registry = ConnectorPluginRegistry(repository=repository)
    registry.register(google)
    registry.register(tiktok)
    detector = HeuristicLanguageDetector()
    clusterer = SemanticClusterer()
    synchronizer = VocabularySynchronizer(
        repository,
        quality_evaluator=QualityEvaluator(detector=detector),
        strategic_reasoner=StrategicMarketReasoner(detector=detector),
        clusterer=clusterer,
        google_trends_plugin=google,
        language_detector=detector,
        tiktok_plugin=tiktok,
        registry=registry,
    )
    return {"registry": registry, "google": google, "tiktok": tiktok, "sync": synchronizer}


async def _run_first_mission(repository, store, workspace, process):
    mission = await _attention_mission(repository, store, workspace)
    result = await _executor(repository, store, process["registry"], process["sync"]).execute(mission.id)
    outcomes = await store.get_latest_completed_probe_outcomes(mission.id)
    signals = await repository.get_mission_signals(mission.id)
    return result, outcomes, signals


def _observed(outcomes, signals):
    return (
        sorted((o.connector_surface, o.status.value, o.signals_collected) for o in outcomes),
        sorted(s.raw_title for s in signals),
    )


@pytest.mark.asyncio
async def test_cold_start_first_mission_registers_persisted_vocabulary_before_any_connector_call(
    repository_case, host_workspace
):
    repository = repository_case.repository
    templates = await _persist_vocabulary(repository_case)
    store, workspace = await _workspace(repository, host_workspace)
    cold = _fresh_process(repository)

    result, outcomes, signals = await _run_first_mission(repository, store, workspace, cold)

    assert result["status"] == "COMPLETED"
    surfaces, titles = _observed(outcomes, signals)
    assert surfaces == [
        ("google", "HEALTHY", len(templates)), ("tiktok_video_grid", "HEALTHY", 1),
    ], (
        "the first mission must see the persisted TikTok UI noise and probe templates"
    )
    assert "Quản lý kho bằng AI cho shop nhỏ" in titles
    assert "ai cho cửa hàng là gì" in titles and "ai cho cửa hàng giá bao nhiêu" in titles


@pytest.mark.asyncio
async def test_cold_start_and_warm_process_invoke_the_same_surfaces_with_the_same_vocabulary(
    repository_case, host_workspace
):
    repository = repository_case.repository
    await _persist_vocabulary(repository_case)
    store, workspace = await _workspace(repository, host_workspace)

    cold = _fresh_process(repository)
    cold_observed = _observed(*(await _run_first_mission(repository, store, workspace, cold))[1:])

    warm = _fresh_process(repository)
    await warm["sync"].synchronize()  # what an earlier analysis call used to do by accident
    warm_observed = _observed(*(await _run_first_mission(repository, store, workspace, warm))[1:])

    assert cold_observed == warm_observed
    assert cold["tiktok"]._ui_noise and len(cold["tiktok"]._ui_noise) == len(warm["tiktok"]._ui_noise)
    assert cold["google"]._probe_templates == warm["google"]._probe_templates


@pytest.mark.asyncio
async def test_cold_start_vocabulary_failure_calls_no_connector_and_fails_clearly(
    repository_case, host_workspace
):
    from ignis.domain.exceptions import VocabularySynchronizationError

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    process = _fresh_process(repository)
    mission = await _attention_mission(repository, store, workspace)

    class CountingRegistry:
        calls = 0

        async def search_with_outcomes(self, **_kwargs):
            CountingRegistry.calls += 1
            raise AssertionError("a connector was called under partial configuration")

    async def unreadable(*_args, **_kwargs):
        raise RuntimeError("market_lexicons is unreadable")

    process["sync"]._repository = type(
        "UnreadableVocabulary", (), {"get_domain_lexicons": unreadable,
                                     "get_industry_taxonomies": unreadable}
    )()

    with pytest.raises(VocabularySynchronizationError):
        await _executor(repository, store, CountingRegistry(), process["sync"]).execute(mission.id)

    assert CountingRegistry.calls == 0
    stored = await repository.get_mission(mission.id)
    assert stored.status == "FAILED" and "vocabulary" in stored.summary.lower()
    # Synchronization runs inside the writer claim, so the claim holder's run records the failure.
    assert [j.status for j in await store.list_run_journals(mission.id)] == ["FAILED"]
    assert await store.get_mission_writer_claim(mission.id) is None
    assert await store.get_latest_completed_probe_outcomes(mission.id) == []
    assert await repository.get_mission_signals(mission.id) == []


@pytest.mark.asyncio
async def test_cold_start_execute_mission_ingress_handler_needs_no_prior_analysis_call(
    repository_case, host_workspace, monkeypatch
):
    import json

    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    await _persist_vocabulary(repository_case)
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    process = _fresh_process(repository)
    components = {
        "repository": repository,
        "workspace_store": store,
        "execute_mission_use_case": _executor(repository, store, process["registry"], process["sync"]),
    }
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    payload = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))

    assert payload["status"] == "COMPLETED", payload
    outcomes = {o.connector_surface: o for o in await store.get_latest_completed_probe_outcomes(mission.id)}
    assert outcomes["tiktok_video_grid"].status.value == "HEALTHY"
    assert outcomes["tiktok_video_grid"].signals_collected == 1


# --- User Story 2: unsupported Market evidence fails closed --------------------------------------
#
# The acceptance corpus is the accepted post-v0.5 validation, redacted and committed as
# tests/fixtures/decision_grade_evidence.json. Judgments reach Ignis only through the two real MCP
# handlers, exactly as a host Agent submits them; analysis is read back through the real handler.

import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

CORPUS = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "decision_grade_evidence.json").read_text(
        encoding="utf-8"
    )
)
CONTROL_KEYWORDS = ["AI cho cửa hàng bán lẻ", "AI quản lý cửa hàng", "AI xây website bán hàng"]
VERDICT_WORDS = ("SATURATED", "HIGH_DEMAND_LOW_SUPPLY", "DEMAND_GAP", "GROWING_OPPORTUNITY",
                 "BALANCED_COMPETITION", "PROBE_OPPORTUNITY", "white space", "saturated")
SURFACE_OF = {"google": "google", "youtube": "youtube", "tiktok": "tiktok_video_grid",
              "threads": "threads", "reels": "reels"}


def _corpus_signal(item, captured_at=T0):
    """One fixture record as the connector would have returned it, with a stable identity."""
    key = item["source_key"]
    number = int(key, 16)
    platform = PlatformType(item["platform"])
    urls = {
        "google": f"https://trends.google.com/trends/explore?q={key}",
        "youtube": f"https://www.youtube.com/watch?v={(key * 2)[:11]}",
        "tiktok": f"https://www.tiktok.com/@handle/video/{number % 10**19:019d}",
        "threads": f"https://www.threads.net/@handle/post/{key[:11]}",
        "reels": f"https://www.instagram.com/reel/{key[:11]}/",
    }
    metadata = {"connector_surface": SURFACE_OF[item["platform"]]}
    if item.get("probe_keyword"):
        metadata["keyword"] = item["probe_keyword"]
    if item["platform"] == "threads":
        metadata["post_id"] = str(number % 10**18)
    return TrendSignal(
        platform=platform,
        raw_title=item["title"],
        metric_value=float(item["metric_value"] or 0.0),
        source_url=urls[item["platform"]],
        geo_code=GeoCode.VN,
        captured_at=captured_at,
        metadata=metadata,
    )


def _handler_components(repository, store):
    from ignis.application.use_cases.get_evidence_qualification_batch import (
        GetEvidenceQualificationBatchUseCase,
    )
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
    from ignis.application.use_cases.get_top_clusters import GetTopClustersUseCase
    from ignis.application.use_cases.submit_evidence_qualifications import (
        SubmitEvidenceQualificationsUseCase,
    )
    from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
    from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

    return {
        "repository": repository,
        "workspace_store": store,
        "quality_evaluator": QualityEvaluator(),
        "strategic_reasoner": StrategicMarketReasoner(),
        "artifact_builder": HtmlArtifactBuilder(),
        "top_clusters_use_case": GetTopClustersUseCase(repository=repository),
        "get_mission_analysis_use_case": GetMissionAnalysisUseCase(repository=repository),
        "get_evidence_qualification_batch_use_case": GetEvidenceQualificationBatchUseCase(
            repository=repository, store=store
        ),
        "submit_evidence_qualifications_use_case": SubmitEvidenceQualificationsUseCase(
            repository=repository, store=store
        ),
    }


async def _market_with(repository, store, workspace, items, keywords, brief=None, outcomes=()):
    """A confirmed Market mission holding `items`, with one completed run's probe outcomes."""
    from ignis.domain.research_workspace import compute_query_fingerprint

    mission, revision = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=list(keywords),
        **(brief or MARKET_BRIEF),
    )
    signals = [_corpus_signal(item) for item in items]
    held = await _hold(repository, mission, signals)
    by_url = {s.source_url: [] for s in held}
    for s in held:
        by_url[s.source_url].append(s)
    run = await _journal(store, workspace, mission, "COMPLETED", T0, 1)
    # Every surface here attests the whole keyword list, which is within its ten-keyword cap.
    queried = tuple(mission.keywords[:10])
    window = getattr(mission.timeframe, "value", mission.timeframe)
    fingerprint = compute_query_fingerprint(queried, mission.geo_code, window)
    await store.record_probe_outcomes(run.run_id, [
        MissionProbeOutcome(
            run_id=run.run_id, platform=platform, connector_surface=surface, status=status,
            signals_collected=count, queried_keywords=queried, queried_window=window,
            query_fingerprint=fingerprint, completed_at=T0,
        )
        for surface, platform, status, count in outcomes
    ])
    return mission, revision, held


def _judgments_by_observation(held, items, key="judgment"):
    """Map each stored observation to the judgment its fixture record carries."""
    judgment_by_url = {}
    for item in items:
        judgment_by_url.setdefault(_corpus_signal(item).source_url, []).append(item[key])
    queues = {url: list(js) for url, js in judgment_by_url.items()}
    return {str(s.observation_id): queues[s.source_url].pop(0) for s in held}


async def _qualify_through_handlers(mcp_server, mission, judgments):
    """What a host Agent does: read a batch, judge it, submit it, until nothing is pending."""
    responses = []
    for _ in range(20):
        batch = json.loads(
            await mcp_server.handle_get_mission_evidence_qualification_batch(str(mission.id), limit=7)
        )
        if batch["status"] == "READY" or not batch.get("evidence"):
            # READY, or nothing left to hand out because the remaining rows are final UNASSESSED.
            return batch, responses
        assert batch["status"] == "QUALIFICATION_REQUIRED", batch
        assessments = [
            {"observation_id": e["observation_id"], "judged_by": "fixture-host", "model": "replay",
             **judgments[e["observation_id"]]}
            for e in batch["evidence"]
        ]
        response = json.loads(
            await mcp_server.handle_submit_mission_evidence_qualifications(
                str(mission.id), batch["frame_fingerprint"], assessments
            )
        )
        assert response["status"] == "RECORDED", response
        responses.append(response)
    raise AssertionError("qualification never reached READY")


def _conclusion_units(analysis):
    units = []
    for opportunity in analysis.get("market_opportunities", []):
        units.append(("opportunity", opportunity.get("recommendation", ""), opportunity["citations"]))
    for kind in ("strategic_insights", "actionable_takeaways"):
        for insight in analysis.get(kind, []):
            units.append((kind, insight["statement"], insight["citations"]))
    return units


def _unsupported(units, qualified_ids):
    """Units that present a claim on evidence which is not qualified support for this Brief."""
    return [
        (kind, statement)
        for kind, statement, citations in units
        if any(c.get("observation_id") not in qualified_ids for c in citations)
    ]


def _qualified_ids(judgments):
    return {oid for oid, j in judgments.items() if j["relation"] == "QUALIFIED_SUPPORT"}


def test_the_committed_corpus_preserves_the_recorded_unsupported_baseline():
    baseline = CORPUS["baseline"]
    assert baseline["conclusion_units"] == 21 == len(CORPUS["conclusion_units"])
    assert baseline["supported_at_0_70"] == 0
    assert baseline["max_support_probability"] == 0.58
    assert all(u["support_probability"] < 0.70 for u in CORPUS["conclusion_units"])
    assert sum(len(j["observations"]) for j in CORPUS["journeys"].values()) == 133
    # Redaction is structural: every record carries exactly these fields, and no URL, database
    # row id or requester identity survives anywhere in the file.
    fields = {"case_id", "platform", "title", "probe_keyword", "metric_value", "source_key",
              "review", "judgment"}
    for record in CORPUS["journeys"].values():
        assert all(set(o) == fields for o in record["observations"])
        assert "confirmed_by" not in record.get("brief", {})
    blob = json.dumps(CORPUS, ensure_ascii=False)
    assert "://" not in blob and "http" not in blob
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", blob)


@pytest.mark.parametrize("journey", ["direct_market", "attention_to_market"])
@pytest.mark.asyncio
async def test_keyword_noise_corpus_replay_emits_zero_unsupported_conclusion_units(
    repository_case, host_workspace, monkeypatch, journey
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    record = CORPUS["journeys"][journey]
    mission, _revision, held = await _market_with(
        repository, store, workspace, record["observations"], record["keywords"],
        brief=record["brief"],
        outcomes=[(c["connector_surface"], c["platform"], c["status"], c["signals_count"])
                  for c in record["channels"]],
    )
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    judgments = _judgments_by_observation(held, record["observations"])

    ready, _ = await _qualify_through_handlers(mcp_server, mission, judgments)
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id), limit=50))

    units = _conclusion_units(analysis)
    assert _unsupported(units, _qualified_ids(judgments)) == [], (
        "a conclusion was emitted on evidence that is not qualified support"
    )
    recorded_baseline = [u for u in CORPUS["conclusion_units"] if u["journey"] == journey]
    assert recorded_baseline and all(u["support_probability"] < 0.70 for u in recorded_baseline)
    assert analysis["qualification"]["total_evidence"] == len(held) == ready["progress"]["total_evidence"]
    # The replayed review left low-confidence and ambiguous items UNASSESSED; a recorded
    # UNASSESSED judgment keeps the whole frame withheld rather than letting the rest conclude.
    unassessed = sum(o["judgment"]["relation"] == "UNASSESSED" for o in record["observations"])
    assert analysis["qualification"]["unassessed"] == unassessed
    if unassessed:
        assert analysis["analysis_status"] == "QUALIFICATION_REQUIRED"
        assert analysis["qualification"]["reason_code"] == "UNASSESSED_EVIDENCE"
        assert "new Market Brief revision" in analysis["next_step"]
    else:
        assert analysis["analysis_status"] == "INSUFFICIENT_RELEVANT_EVIDENCE"
        assert analysis["qualification"]["reason_code"] == "NO_SUFFICIENT_TOPIC"
    assert analysis["opportunity_index_applies"] is False
    assert analysis["market_opportunities"] == []
    scorecard = analysis["quality_scorecard"]
    assert scorecard["confidence_level"] in ("LOW", "UNRELIABLE")
    assert scorecard["question_relevance_score"] == analysis["qualification"]["question_relevance_score"]


@pytest.mark.asyncio
async def test_keyword_noise_negative_controls_support_nothing_and_stay_inspectable(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    negatives = CORPUS["semantic_controls"]["negative"]
    assert {c["category"] for c in negatives} == {
        "film", "lottery", "unrelated_news", "sports", "target_user_mismatch", "adjacent_demand",
    }
    # Keyword-matched demand beside two keyword-matched supply sources: counted as support, they
    # would be exactly enough for a verdict, which is what makes this control able to fail.
    assert sum(c["platform"] == "google" for c in negatives) == 1
    assert all(c["probe_keyword"] in CONTROL_KEYWORDS for c in negatives), "a control must repeat a probe keyword"
    mission, _revision, held = await _market_with(
        repository, store, workspace, negatives, CONTROL_KEYWORDS,
        outcomes=[("youtube", "youtube", "HEALTHY", 4), ("tiktok_video_grid", "tiktok", "HEALTHY", 3)],
    )
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    judgments = _judgments_by_observation(held, negatives, key="control_judgment")

    await _qualify_through_handlers(mcp_server, mission, judgments)
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id), limit=50))

    assert analysis["qualification"]["total_evidence"] == len(negatives)
    assert analysis["qualification"]["excluded_irrelevant"] == len(negatives) - 1
    assert analysis["qualification"]["context_only"] == 1
    assert analysis["qualification"]["question_relevance_score"] == 0.0
    assert analysis["analysis_status"] == "INSUFFICIENT_RELEVANT_EVIDENCE"
    assert analysis["opportunity_index_applies"] is False
    assert _conclusion_units(analysis) == []
    text = json.dumps(
        {k: analysis[k] for k in ("market_opportunities", "strategic_insights", "actionable_takeaways")},
        ensure_ascii=False,
    )
    assert not any(word in text for word in VERDICT_WORDS)
    # Excluded evidence stays readable for audit, labelled as what it is.
    assert {s["qualification_relation"] for s in analysis["top_signals"]} == {
        "EXCLUDED_IRRELEVANT", "CONTEXT_ONLY",
    }
    assert repository_case.counts()["observations"] == len(negatives), "no raw observation was deleted"


@pytest.mark.asyncio
async def test_insufficient_market_supply_withholds_every_verdict_even_with_qualified_demand(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    positives = {c["case_id"]: c for c in CORPUS["semantic_controls"]["positive"]}
    items = [positives["ctl-dm-038"], positives["ctl-dm-012"]]  # demand, and one supply source
    mission, _revision, held = await _market_with(
        repository, store, workspace, items, CONTROL_KEYWORDS,
        outcomes=[("google", "google", "HEALTHY", 1), ("youtube", "youtube", "HEALTHY", 1),
                  ("tiktok_video_grid", "tiktok", "AUTH_REQUIRED", 0), ("reels", "reels", "EMPTY_NO_DATA", 0)],
    )
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    await _qualify_through_handlers(mcp_server, mission, _judgments_by_observation(held, items, "control_judgment"))

    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    assert analysis["analysis_status"] == "INSUFFICIENT_RELEVANT_EVIDENCE"
    assert analysis["market_opportunities"] == [] and analysis["opportunity_index_applies"] is False
    withheld = {t["topic"]: t for t in analysis["topic_sufficiency"]}
    assert withheld["AI cho cửa hàng bán lẻ"]["evidence_sufficiency"] == "MISSING_SUPPLY"
    assert withheld["AI quản lý cửa hàng"]["evidence_sufficiency"] == "MISSING_DEMAND"


@pytest.mark.asyncio
async def test_qualified_market_control_keeps_its_opportunity_index_with_qualified_citations_only(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    controls = CORPUS["semantic_controls"]
    positives = {c["case_id"]: c for c in controls["positive"]}
    # One extra sighting of an already qualified source: it may add an observation, never a source.
    repeat = dict(positives["ctl-dm-012"], case_id="ctl-dm-012-repeat")
    items = [*controls["positive"], repeat, *controls["negative"]]
    mission, revision, held = await _market_with(
        repository, store, workspace, items, CONTROL_KEYWORDS,
        outcomes=[("google", "google", "HEALTHY", 1), ("youtube", "youtube", "HEALTHY", 8),
                  ("tiktok_video_grid", "tiktok", "HEALTHY", 3), ("threads", "threads", "HEALTHY", 1)],
    )
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    judgments = _judgments_by_observation(held, items, key="control_judgment")
    await _qualify_through_handlers(mcp_server, mission, judgments)

    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id), limit=50))

    assert analysis["analysis_status"] == "READY"
    assert analysis["opportunity_index_applies"] is True
    assert [o["topic"] for o in analysis["market_opportunities"]] == ["AI cho cửa hàng bán lẻ"]
    opportunity = analysis["market_opportunities"][0]
    assert opportunity["evidence_sufficiency"] == "SUFFICIENT_POSITIVE_SUPPLY"
    assert (opportunity["qualified_demand_count"], opportunity["qualified_supply_count"],
            opportunity["independent_supply_sources"]) == (1, 3, 2)
    assert isinstance(opportunity["opportunity_index"], float)
    qualified = _qualified_ids(judgments)
    assert _unsupported(_conclusion_units(analysis), qualified) == []
    assert _conclusion_units(analysis), "a supported control must still produce conclusions"
    cited = {c["observation_id"] for _k, _s, cs in _conclusion_units(analysis) for c in cs}
    assert cited and cited <= qualified
    assert all(c["evidence_role"] == "MARKET_EVIDENCE" for c in opportunity["citations"])
    assert analysis["market_brief"]["brief_revision_id"] == str(revision.brief_revision_id)


@pytest.mark.asyncio
async def test_qualified_market_control_measured_zero_needs_two_completed_empty_supply_surfaces(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    demand = [c for c in CORPUS["semantic_controls"]["positive"] if c["case_id"] == "ctl-dm-038"]
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))

    async def analysed(outcomes):
        mission, _revision, held = await _market_with(
            repository, store, workspace, demand, ["AI cho cửa hàng bán lẻ"], outcomes=outcomes,
        )
        await _qualify_through_handlers(
            mcp_server, mission, _judgments_by_observation(held, demand, "control_judgment")
        )
        return json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    measured = await analysed([("google", "google", "HEALTHY", 1),
                               ("youtube", "youtube", "EMPTY_NO_DATA", 0),
                               ("tiktok_video_grid", "tiktok", "EMPTY_NO_DATA", 0)])
    one_failed = await analysed([("google", "google", "HEALTHY", 1),
                                 ("youtube", "youtube", "EMPTY_NO_DATA", 0),
                                 ("tiktok_video_grid", "tiktok", "RATE_LIMITED", 0)])

    assert measured["analysis_status"] == "READY"
    assert [o["evidence_sufficiency"] for o in measured["market_opportunities"]] == ["SUFFICIENT_ZERO_SUPPLY"]
    assert measured["market_opportunities"][0]["qualified_supply_count"] == 0
    assert one_failed["analysis_status"] == "INSUFFICIENT_RELEVANT_EVIDENCE"
    assert one_failed["market_opportunities"] == []


# --- User Story 2: stable history, revision isolation and evidence replacement -------------------


class ShiftingHealthRegistry:
    """Current connector health that changes between two reads of the same report."""

    def __init__(self):
        self.state = "CLOSED"

    def get_health_status(self):
        return {
            surface: {"platform": platform, "circuit_state": self.state, "consecutive_failures": 9}
            for surface, platform in (("google", "google"), ("youtube", "youtube"),
                                      ("tiktok_video_grid", "tiktok"))
        }


def _stable(analysis):
    """The parts of an analysis a reopen must reproduce exactly."""
    return {
        key: analysis.get(key)
        for key in ("analysis_status", "qualification", "topic_sufficiency", "market_opportunities",
                    "strategic_insights", "actionable_takeaways", "channel_summaries",
                    "opportunity_index_applies", "maturity_stage")
    }


@pytest.mark.asyncio
async def test_reopen_reads_the_same_persisted_judgments_and_outcomes_whatever_current_health_says(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    demand = [c for c in CORPUS["semantic_controls"]["positive"] if c["case_id"] == "ctl-dm-038"]
    mission, _revision, held = await _market_with(
        repository, store, workspace, demand, ["AI cho cửa hàng bán lẻ"],
        outcomes=[("google", "google", "HEALTHY", 1), ("youtube", "youtube", "EMPTY_NO_DATA", 0),
                  ("tiktok_video_grid", "tiktok", "EMPTY_NO_DATA", 0)],
    )
    registry = ShiftingHealthRegistry()
    components = {**_handler_components(repository, store), "registry": registry}
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)
    await _qualify_through_handlers(mcp_server, mission, _judgments_by_observation(held, demand, "control_judgment"))

    first = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))
    stored = [q.same_judgment for q in await store.list_evidence_qualifications(mission.id)]
    registry.state = "OPEN"  # every surface now looks broken; the completed run did not change
    reopened = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    assert first["analysis_status"] == "READY"
    assert _stable(reopened) == _stable(first)
    assert len(await store.list_evidence_qualifications(mission.id)) == len(stored)
    statuses = {c["connector_surface"]: c["status"] for c in reopened["channel_summaries"]}
    assert statuses == {"google": "HEALTHY", "tiktok_video_grid": "EMPTY_NO_DATA", "youtube": "EMPTY_NO_DATA"}


@pytest.mark.asyncio
async def test_reopen_keeps_the_measured_zero_of_the_last_completed_run_after_a_later_failed_run(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    demand = [c for c in CORPUS["semantic_controls"]["positive"] if c["case_id"] == "ctl-dm-038"]
    mission, _revision, held = await _market_with(
        repository, store, workspace, demand, ["AI cho cửa hàng bán lẻ"],
        outcomes=[("google", "google", "HEALTHY", 1), ("youtube", "youtube", "EMPTY_NO_DATA", 0),
                  ("tiktok_video_grid", "tiktok", "EMPTY_NO_DATA", 0)],
    )
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    await _qualify_through_handlers(mcp_server, mission, _judgments_by_observation(held, demand, "control_judgment"))
    before = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    failed = await _journal(store, workspace, mission, "FAILED", T0 + timedelta(hours=2), 2)
    await store.record_probe_outcomes(failed.run_id, [
        _outcome(failed.run_id, "youtube", "DEGRADED"),
        _outcome(failed.run_id, "tiktok_video_grid", "RATE_LIMITED", platform="tiktok"),
    ])
    after = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    assert [o["evidence_sufficiency"] for o in before["market_opportunities"]] == ["SUFFICIENT_ZERO_SUPPLY"]
    assert _stable(after) == _stable(before)


@pytest.mark.asyncio
async def test_revision_starts_with_zero_qualifications_and_cannot_reuse_the_prior_frame(
    repository_case, host_workspace, monkeypatch
):
    from ignis.application.use_cases.create_market_revision import CreateMarketRevisionUseCase
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    positives = CORPUS["semantic_controls"]["positive"]
    first, first_brief, held = await _market_with(repository, store, workspace, positives, CONTROL_KEYWORDS)
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    judgments = _judgments_by_observation(held, positives, "control_judgment")
    first_ready, _ = await _qualify_through_handlers(mcp_server, first, judgments)

    revised, revised_brief = await CreateMarketRevisionUseCase(
        repository, store, ConfirmMarketBriefUseCase(repository, store)
    ).execute(
        workspace_id=workspace.workspace_id, confirmed_by="requester", keywords=CONTROL_KEYWORDS,
        previous_mission_id=first.id,
        **{**MARKET_BRIEF, "target_user": "Managers of small Vietnamese pharmacies"},
    )
    await _hold(repository, revised, [_corpus_signal(item, T0 + timedelta(days=1)) for item in positives])

    batch = json.loads(await mcp_server.handle_get_mission_evidence_qualification_batch(str(revised.id)))
    stale = json.loads(await mcp_server.handle_submit_mission_evidence_qualifications(
        str(revised.id), first_ready["frame_fingerprint"],
        [{"observation_id": batch["evidence"][0]["observation_id"], "judged_by": "fixture-host",
          **positives[0]["control_judgment"]}],
    ))

    assert await store.list_evidence_qualifications(revised.id) == []
    assert batch["status"] == "QUALIFICATION_REQUIRED"
    assert batch["progress"]["unassessed"] == len(positives)
    assert batch["frame"]["brief_revision_id"] == str(revised_brief.brief_revision_id)
    assert batch["frame_fingerprint"] != first_ready["frame_fingerprint"]
    assert stale["status"] == "CONFLICT" and stale["reason_code"] == "STALE_FRAME"
    assert len(await store.list_evidence_qualifications(first.id)) == len(positives), (
        "the earlier revision's judgments are immutable history"
    )
    revised_analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(revised.id)))
    assert revised_analysis["analysis_status"] == "QUALIFICATION_REQUIRED"
    assert revised_analysis["market_opportunities"] == []
    assert first_brief.brief_revision_id != revised_brief.brief_revision_id


@pytest.mark.asyncio
async def test_evidence_replacement_prunes_only_its_judgment_and_new_evidence_requires_qualification(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission, _brief = await _market_mission(repository, store, workspace, keywords=CONTROL_KEYWORDS)
    positives = {c["case_id"]: c for c in CORPUS["semantic_controls"]["positive"]}
    supply, demand = positives["ctl-dm-012"], positives["ctl-dm-038"]
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))

    await _executor(repository, store, OutcomeRegistry(
        [_corpus_signal(supply), _corpus_signal(demand)],
        [_surface("youtube", "HEALTHY", 1), _surface("google", "HEALTHY", 1)],
    )).execute(mission.id)
    first_pass = {s.source_url: s for s in await repository.get_mission_signals(mission.id)}
    await _qualify_through_handlers(mission=mission, mcp_server=mcp_server, judgments=_judgments_by_observation(
        list(first_pass.values()), [supply, demand], "control_judgment"
    ))
    old_supply = first_pass[_corpus_signal(supply).source_url]
    old_demand = first_pass[_corpus_signal(demand).source_url]

    # The second pass reaches Google only. The YouTube observation is preserved as it was; the old
    # Google observation is replaced by the new sighting and its association is pruned.
    await _executor(repository, store, OutcomeRegistry(
        [_corpus_signal(demand, T0 + timedelta(hours=1))],
        [_surface("youtube", "RATE_LIMITED"), _surface("google", "HEALTHY", 1)],
    )).execute(mission.id)

    current = {str(s.observation_id): s for s in await repository.get_mission_signals(mission.id)}
    judged = {str(q.observation_id) for q in await store.list_evidence_qualifications(mission.id)}
    new_demand = [oid for oid, s in current.items() if oid not in (str(old_supply.observation_id),)]
    assert str(old_supply.observation_id) in current and str(old_supply.observation_id) in judged, (
        "a retained observation keeps its judgment: the frame and the observation are unchanged"
    )
    assert str(old_demand.observation_id) not in current
    assert str(old_demand.observation_id) not in judged, "the pruned association took its judgment"
    assert len(new_demand) == 1 and new_demand[0] not in judged
    batch = json.loads(await mcp_server.handle_get_mission_evidence_qualification_batch(str(mission.id)))
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))
    assert [e["observation_id"] for e in batch["evidence"]] == new_demand
    assert analysis["analysis_status"] == "QUALIFICATION_REQUIRED"
    assert analysis["market_opportunities"] == [] and analysis["opportunity_index_applies"] is False
    latest = {o.connector_surface: o.status.value for o in await store.get_latest_completed_probe_outcomes(mission.id)}
    assert latest == {"google": "HEALTHY", "youtube": "RATE_LIMITED"}


# --- User Story 3: Attention hands off only a qualified candidate --------------------------------


async def _attention_with(repository, store, workspace, clusters):
    """An Attention mission whose evidence is grouped into the given clusters of fixture items."""
    from ignis.domain.entities import TopicCluster

    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title=CORPUS["journeys"]["attention_only"]["title"],
        keywords=CORPUS["journeys"]["attention_only"]["keywords"],
    )
    items = [item for members in clusters.values() for item in members]
    held = await _hold(repository, mission, [_corpus_signal(item) for item in items])
    by_url = {s.source_url: s for s in held}
    for label, members in clusters.items():
        cluster = TopicCluster(canonical_name=f"{label} {mission.id}")
        grouped = [by_url[_corpus_signal(item).source_url] for item in members]
        for signal in grouped:
            signal.cluster_id = cluster.id
        cluster.signals = grouped
        await repository.save_clusters([cluster])
        await repository.assign_observation_clusters(grouped)
    return mission, await repository.get_mission_signals(mission.id), items


@pytest.mark.asyncio
async def test_attention_handoff_corpus_offers_no_candidate_and_selects_no_fallback(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    observations = CORPUS["journeys"]["attention_only"]["observations"]
    # The validation's three clusters are not recoverable from the redacted corpus, so the replay
    # groups by probe keyword: the grouping the recorded candidate ("ai xay website") shared.
    groups = {}
    for item in observations:
        groups.setdefault(item["probe_keyword"], []).append(item)
    mission, held, items = await _attention_with(repository, store, workspace, groups)
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))

    await _qualify_through_handlers(mcp_server, mission, _judgments_by_observation(held, items))
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id), limit=50))

    assert analysis["surface"] == "ATTENTION"
    assert analysis["opportunity_index_applies"] is False
    assert analysis["market_opportunities"] == []
    # Three replayed items are UNASSESSED, so the handoff answer stays pending -- and still no
    # cluster is offered as a fallback.
    assert analysis["handoff_status"] == "QUALIFICATION_REQUIRED"
    assert analysis["qualified_handoff_candidates"] == []
    assert analysis["qualification"]["reason_code"] == "UNASSESSED_EVIDENCE"
    assert len(analysis["cluster_qualification"]) == len(groups)
    assert not any(row["handoff_eligible"] for row in analysis["cluster_qualification"])


@pytest.mark.asyncio
async def test_attention_handoff_offers_only_the_directly_relevant_two_source_cluster(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    controls = CORPUS["semantic_controls"]
    positives = {c["case_id"]: c for c in controls["positive"]}
    supported = [positives["ctl-dm-012"], positives["ctl-supply-001"]]
    noise = controls["negative"][:3]
    mission, held, items = await _attention_with(
        repository, store, workspace, {"supported": supported, "noise": noise}
    )
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))

    await _qualify_through_handlers(
        mcp_server, mission, _judgments_by_observation(held, items, "control_judgment")
    )
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id), limit=50))

    assert analysis["handoff_status"] == "QUALIFIED_CANDIDATE_AVAILABLE"
    assert analysis["opportunity_index_applies"] is False and analysis["market_opportunities"] == []
    [candidate] = analysis["qualified_handoff_candidates"]
    supported_ids = {
        str(s.observation_id) for s in held
        if s.source_url in {_corpus_signal(i).source_url for i in supported}
    }
    assert {c["observation_id"] for c in candidate["citations"]} == supported_ids
    assert candidate["independent_sources"] == 2
    eligible = [row for row in analysis["cluster_qualification"] if row["handoff_eligible"]]
    assert [row["cluster_id"] for row in eligible] == [candidate["cluster_id"]]



# --- User Story 4: the MCP payload, the stored rows and the artifact say the same thing ----------


@pytest.mark.asyncio
async def test_artifact_parity_mcp_payload_canonical_rows_and_html_agree_field_for_field(
    repository_case, host_workspace, monkeypatch, tmp_path
):
    import re as regex

    from ignis.domain.research_workspace import QualificationRelation
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    controls = CORPUS["semantic_controls"]
    items = [*controls["positive"], *controls["negative"]]
    mission, _revision, held = await _market_with(
        repository, store, workspace, items, CONTROL_KEYWORDS,
        outcomes=[("google", "google", "HEALTHY", 1), ("youtube", "youtube", "HEALTHY", 5)],
    )
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(mcp_server, "_get_secure_reports_dir", lambda: reports_dir)
    judgments = _judgments_by_observation(held, items, "control_judgment")
    # Leave one observation unjudged, so every count is non-trivial and the state is withheld.
    pending = sorted(judgments)[-1]
    await mcp_server.handle_submit_mission_evidence_qualifications(
        str(mission.id),
        json.loads(await mcp_server.handle_get_mission_evidence_qualification_batch(str(mission.id)))[
            "frame_fingerprint"
        ],
        [{"observation_id": oid, "judged_by": "fixture-host", **j}
         for oid, j in judgments.items() if oid != pending],
    )

    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id), limit=50))
    artifact = json.loads(await mcp_server.handle_generate_mission_artifact(str(mission.id)))
    html = Path(artifact["artifact_file"]).read_text(encoding="utf-8")
    rows = await store.list_evidence_qualifications(mission.id)

    relations = [q.relation for q in rows]
    canonical = {
        "total_evidence": len(held),
        "qualified_support": relations.count(QualificationRelation.QUALIFIED_SUPPORT),
        "context_only": relations.count(QualificationRelation.CONTEXT_ONLY),
        "excluded_irrelevant": relations.count(QualificationRelation.EXCLUDED_IRRELEVANT),
        "unassessed": len(held) - len(rows) + relations.count(QualificationRelation.UNASSESSED),
    }
    block = analysis["qualification"]
    assert {k: block[k] for k in canonical} == canonical
    assert artifact["qualification"] == block
    assert artifact["analysis_status"] == analysis["analysis_status"] == "QUALIFICATION_REQUIRED"
    assert artifact["opportunity_index_applies"] is analysis["opportunity_index_applies"] is False
    assert artifact["quality_scorecard"]["confidence_level"] == analysis["quality_scorecard"]["confidence_level"] == "UNRELIABLE"
    for name in ("qualified_support", "context_only", "excluded_irrelevant", "unassessed"):
        assert f'data-count="{name}">{block[name]}<' in html
    relevance = regex.search(r'data-dimension="question_relevance">([0-9.]+)<', html).group(1)
    assert float(relevance) == block["question_relevance_score"]
    assert f'data-reason-code="{block["reason_code"]}"' in html
    assert 'id="demandSupplyBarChart"' not in html


# --- Review 0d70e9b: regressions for the four blocking findings -----------------------------------


@pytest.mark.parametrize(
    "reason, expected_status",
    [("INSUFFICIENT_CONTENT", "QUALIFICATION_REQUIRED"), ("EVALUATOR_UNAVAILABLE", "UNAVAILABLE")],
)
@pytest.mark.asyncio
async def test_explicit_unassessed_evidence_keeps_every_market_verdict_withheld(
    repository_case, host_workspace, monkeypatch, reason, expected_status
):
    """A sufficient control plus one explicitly UNASSESSED observation: no verdict of any kind."""
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    positives = CORPUS["semantic_controls"]["positive"]
    thin = dict(positives[1], case_id="ctl-thin", source_key="0123456789abcdef",
                title="AI cho cửa hàng bán lẻ ???")
    items = [*positives, thin]
    mission, _revision, held = await _market_with(
        repository, store, workspace, items, CONTROL_KEYWORDS,
        outcomes=[("google", "google", "HEALTHY", 1), ("youtube", "youtube", "HEALTHY", 3)],
    )
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    judgments = _judgments_by_observation(held, positives, "control_judgment") if False else {}
    by_url = {_corpus_signal(i).source_url: i for i in items}
    for signal in held:
        item = by_url[signal.source_url]
        judgments[str(signal.observation_id)] = (
            {"relation": "UNASSESSED", "purpose": "CONTEXT", "confidence": None, "reason_code": reason}
            if item is thin else item["control_judgment"]
        )
    final_batch, _ = await _qualify_through_handlers(mcp_server, mission, judgments)

    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id), limit=50))

    # Every observation carries a persisted row, and still nothing reads as ready: the batch and
    # the analysis give the same status, reason and recovery guidance.
    assert final_batch["evidence"] == [] and final_batch["status"] == expected_status
    assert final_batch["reason_code"] == analysis["qualification"]["reason_code"]
    assert final_batch["next_step"] == analysis["next_step"]
    assert analysis["qualification"]["unassessed"] == 1
    assert analysis["analysis_status"] == expected_status
    assert analysis["opportunity_index_applies"] is False
    assert analysis["market_opportunities"] == []
    assert analysis["strategic_insights"] == [] and analysis["actionable_takeaways"] == []
    assert analysis["maturity_stage"] is None
    assert all(t["evidence_sufficiency"] != "SUFFICIENT_POSITIVE_SUPPLY" for t in analysis["topic_sufficiency"])
    assert analysis["quality_scorecard"]["confidence_level"] == "UNRELIABLE"


@pytest.mark.asyncio
async def test_a_vocabulary_failure_behind_an_active_writer_is_a_conflict_that_changes_nothing(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission = await _attention_mission(repository, store, workspace)
    held = await _hold(repository, mission, [_signal("AI quản lý bán hàng")])
    holder = await _journal(store, workspace, mission, "STARTED", T0, 1)
    assert await store.claim_mission_writer(mission.id, holder.run_id)
    before = await repository.get_mission(mission.id)

    class FailingSynchronizer:
        calls = 0

        async def synchronize(self):
            FailingSynchronizer.calls += 1
            from ignis.domain.exceptions import VocabularySynchronizationError

            raise VocabularySynchronizationError("market_lexicons is unreadable")

    class NoConnector:
        async def search_with_outcomes(self, **_kwargs):
            raise AssertionError("a connector was called behind an active writer")

    components = {
        "repository": repository,
        "workspace_store": store,
        "execute_mission_use_case": _executor(repository, store, NoConnector(), FailingSynchronizer()),
    }
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)

    payload = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))

    assert payload["status"] == "CONFLICT"
    assert payload["active_run_id"] == str(holder.run_id)
    after = await repository.get_mission(mission.id)
    assert (after.status, after.summary) == (before.status, before.summary)
    assert [str(s.observation_id) for s in await repository.get_mission_signals(mission.id)] == [
        str(held[0].observation_id)
    ]
    assert [(j.run_id, j.status) for j in await store.list_run_journals(mission.id)] == [
        (holder.run_id, "STARTED")
    ]
    assert (await store.get_mission_writer_claim(mission.id)).run_id == holder.run_id



@pytest.mark.asyncio
async def test_a_measured_zero_never_covers_a_keyword_the_surfaces_did_not_query(
    repository_case, host_workspace, monkeypatch
):
    """Eleven mission keywords; the real Reels and TikTok search loops probe only the first ten."""
    from unittest.mock import AsyncMock, patch

    from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
    from ignis.interfaces.mcp import server as mcp_server

    keywords = [f"topic{index}" for index in range(1, 12)]

    class DemandFor:
        """Google demand for the first and the eleventh keyword only."""

        platform, name, plugin_id, supports_search = PlatformType.GOOGLE_TRENDS, "Google", "google", True

        async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=None, custom_timeframe=None, limit=20):
            return [
                _signal(f"Google Search Trends: {k}", PlatformType.GOOGLE_TRENDS, external=f"g-{k}", keyword=k,
                        connector_surface="google")
                for k in (keywords[0], keywords[10])
            ]

    class AnsweredEmptyTikTok(TikTokPlugin):
        """The real keyword loop; each page it reaches answers with an empty search response."""

        async def keyword_search_blocked_reason(self):
            return None

        async def _fetch_via_playwright(self, url, storage_state, geo, limit=30, keyword=None,
                                        seen_urls=None, attestation=None):
            attestation.executed(keyword)
            return []

    oauth, browser = AsyncMock(), AsyncMock()
    oauth.get_access_token.return_value = None
    browser.get_storage_state.return_value = {"cookies": [{"name": "sessionid", "value": "test"}]}
    registry = ConnectorPluginRegistry(repository=repository_case.repository)
    registry.register(DemandFor())
    registry.register(AnsweredEmptyTikTok())
    registry.register(ReelsPlugin(auth_manager=oauth, browser_auth_manager=browser))

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission, _brief = await _market_mission(repository, store, workspace, keywords=keywords)
    empty_page = {"data": {"recent": {"sections": []}}}
    with patch("ignis.infrastructure.connectors.reels.reels_plugin.collect_json_payloads",
               AsyncMock(return_value=[empty_page])):
        await _executor(repository, store, registry).execute(mission.id)

    outcomes = {o.connector_surface: o for o in await store.get_latest_completed_probe_outcomes(mission.id)}
    assert outcomes["reels"].status.value == outcomes["tiktok_video_grid"].status.value == "EMPTY_NO_DATA"
    assert outcomes["reels"].queried_keywords == tuple(keywords[:10])
    assert outcomes["tiktok_video_grid"].queried_keywords == tuple(keywords[:10])
    # Neither real search restricts results to a window, so neither measured the 7d frame.
    assert outcomes["reels"].queried_window is None
    assert outcomes["tiktok_video_grid"].queried_window is None

    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    held = await repository.get_mission_signals(mission.id)
    judgments = {
        str(s.observation_id): {"relation": "QUALIFIED_SUPPORT", "purpose": "DEMAND", "confidence": 0.9,
                                "reason_code": "DIRECT_TO_FRAME"}
        for s in held
    }
    await _qualify_through_handlers(mcp_server, mission, judgments)
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    topics = {t["topic"]: t for t in analysis["topic_sufficiency"]}
    assert topics["topic1"]["evidence_sufficiency"] == "MISSING_SUPPLY"
    assert topics["topic11"]["evidence_sufficiency"] == "MISSING_SUPPLY"
    assert topics["topic11"]["measured_zero_surfaces"] == topics["topic1"]["measured_zero_surfaces"] == []
    assert analysis["market_opportunities"] == []


@pytest.mark.asyncio
async def test_a_windowed_measured_zero_still_covers_only_the_ten_keywords_each_surface_queried(
    repository_case, host_workspace, monkeypatch
):
    """Surfaces that filter by the frame's window and probe ten keywords: topic11 is not covered."""
    from ignis.interfaces.mcp import server as mcp_server

    keywords = [f"topic{index}" for index in range(1, 12)]

    class DemandForFirstAndEleventh(DemandOnly):
        async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=None, custom_timeframe=None, limit=20):
            return [_signal(f"Google Search Trends: {k}", PlatformType.GOOGLE_TRENDS, external=f"g-{k}",
                            keyword=k, connector_surface="google") for k in (keywords[0], keywords[10])]

    registry = ConnectorPluginRegistry(repository=repository_case.repository)
    for plugin in (DemandForFirstAndEleventh(), WindowedSupply("reels", PlatformType.REELS),
                   WindowedSupply("tiktok_video_grid", PlatformType.TIKTOK)):
        registry.register(plugin)
    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission, _brief = await _market_mission(repository, store, workspace, keywords=keywords)
    await _executor(repository, store, registry).execute(mission.id)

    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    held = await repository.get_mission_signals(mission.id)
    await _qualify_through_handlers(mcp_server, mission, {
        str(s.observation_id): {"relation": "QUALIFIED_SUPPORT", "purpose": "DEMAND", "confidence": 0.9,
                                "reason_code": "DIRECT_TO_FRAME"}
        for s in held
    })
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    topics = {t["topic"]: t for t in analysis["topic_sufficiency"]}
    assert topics["topic1"]["evidence_sufficiency"] == "SUFFICIENT_ZERO_SUPPLY"
    assert topics["topic11"]["evidence_sufficiency"] == "MISSING_SUPPLY"
    assert topics["topic11"]["measured_zero_surfaces"] == []
    assert [o["topic"] for o in analysis["market_opportunities"]] == ["topic1"]


# --- Follow-up review of 1205030: the executed window is part of the measured query --------------


class WindowedSupply:
    """A supply surface that accepts only `timeframe`, as Reels and Threads do, and attests it."""

    supports_search = True

    def __init__(self, plugin_id, platform, fixed_window=None):
        self.plugin_id, self.name, self._platform, self.fixed_window = plugin_id, plugin_id, platform, fixed_window
        self.received = []

    @property
    def platform(self):
        return self._platform

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=None, limit=20, attestation=None):
        self.received.append(timeframe)
        window = self.fixed_window or (timeframe.value if hasattr(timeframe, "value") else timeframe)
        attestation.applied_window(window)
        for keyword in keywords[:10]:
            attestation.executed(keyword)
        return []


class DemandOnly:
    platform, name, plugin_id, supports_search = PlatformType.GOOGLE_TRENDS, "Google", "google", True

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=None, custom_timeframe=None, limit=20):
        return [_signal(f"Google Search Trends: {keywords[0]}", PlatformType.GOOGLE_TRENDS,
                        external=f"g-{keywords[0]}", keyword=keywords[0], connector_surface="google")]


@pytest.mark.parametrize("mismatch, expected", [(False, "SUFFICIENT_ZERO_SUPPLY"), (True, "MISSING_SUPPLY")])
@pytest.mark.asyncio
async def test_a_surface_that_executed_another_window_is_not_a_measured_zero_for_the_frame(
    repository_case, host_workspace, monkeypatch, mismatch, expected
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    mission, _brief = await _market_mission(repository, store, workspace, keywords=["ai cho cửa hàng"],
                                            timeframe="30d")
    reels = WindowedSupply("reels", PlatformType.REELS)
    tiktok = WindowedSupply("tiktok_video_grid", PlatformType.TIKTOK, fixed_window="24h" if mismatch else None)
    registry = ConnectorPluginRegistry(repository=repository)
    for plugin in (DemandOnly(), reels, tiktok):
        registry.register(plugin)

    await _executor(repository, store, registry).execute(mission.id)

    assert [str(getattr(t, "value", t)) for t in reels.received] == ["30d"], (
        "a connector that reads only `timeframe` must receive the mission's window"
    )
    outcomes = {o.connector_surface: o for o in await store.get_latest_completed_probe_outcomes(mission.id)}
    assert outcomes["reels"].queried_window == "30d"
    assert outcomes["tiktok_video_grid"].queried_window == ("24h" if mismatch else "30d")

    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    held = await repository.get_mission_signals(mission.id)
    await _qualify_through_handlers(mcp_server, mission, {
        str(s.observation_id): {"relation": "QUALIFIED_SUPPORT", "purpose": "DEMAND", "confidence": 0.9,
                                "reason_code": "DIRECT_TO_FRAME"}
        for s in held
    })
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    [topic] = analysis["topic_sufficiency"]
    assert topic["evidence_sufficiency"] == expected


# --- Review of ccd22fb: batch and analysis agree while evidence is still pending -----------------


@pytest.mark.asyncio
async def test_an_evaluator_failure_with_pending_evidence_gives_batch_and_analysis_one_answer(
    repository_case, host_workspace, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, workspace = await _workspace(repository, host_workspace)
    positives = CORPUS["semantic_controls"]["positive"]
    mission, _revision, held = await _market_with(repository, store, workspace, positives[:2], CONTROL_KEYWORDS)
    monkeypatch.setattr(mcp_server, "get_components", lambda: _handler_components(repository, store))
    first = json.loads(await mcp_server.handle_get_mission_evidence_qualification_batch(str(mission.id), limit=1))
    recorded = json.loads(await mcp_server.handle_submit_mission_evidence_qualifications(
        str(mission.id), first["frame_fingerprint"],
        [{"observation_id": first["evidence"][0]["observation_id"], "relation": "UNASSESSED",
          "purpose": "CONTEXT", "confidence": None, "reason_code": "EVALUATOR_UNAVAILABLE",
          "judged_by": "fixture-host"}],
    ))
    assert recorded["status"] == "RECORDED" and recorded["progress"]["unassessed"] == len(held)

    batch = json.loads(await mcp_server.handle_get_mission_evidence_qualification_batch(str(mission.id)))
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    assert batch["status"] == analysis["analysis_status"] == "UNAVAILABLE"
    assert batch["reason_code"] == analysis["qualification"]["reason_code"] == "EVALUATOR_UNAVAILABLE"
    assert batch["next_step"] == analysis["next_step"]
    assert batch["evidence"] == [], "no further evidence is handed out once the frame is unavailable"
    assert analysis["opportunity_index_applies"] is False and analysis["market_opportunities"] == []
