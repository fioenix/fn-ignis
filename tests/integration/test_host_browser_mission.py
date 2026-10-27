"""Host answers reuse the existing isolated storage, run writer and evidence frame."""

from datetime import datetime, timedelta, timezone
import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType
from ignis.domain.research_workspace import AuthorityBoundary, MissionManifest, MissionOutputType, InvalidMissionAuthorizationError
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.registry import SurfaceProbeResult
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


async def assignment(repository, tmp_path, *, market=False, budget=2, required=("tiktok_video",), optional=(), youtube_budget=1):
    root = tmp_path / "host"
    root.mkdir()
    store = WorkspaceRepository(repository=repository)
    creator = CreateResearchWorkspaceUseCase(store)
    workspace = await creator.confirm(await creator.propose(root, "Host search"), confirmation=True)
    manifest = MissionManifest(
        outcome="Collect bounded public evidence", decision_context="Choose initial category" if market else None,
        required_channels=required, optional_channels=optional,
        authority_boundary=AuthorityBoundary(public_http=True, official_api=True,
                                             browser_session=True, paid_quota=False),
        quota_budget={"queries": budget, "youtube_search_calls": youtube_budget},
        output_type=MissionOutputType.MARKET_ANALYSIS if market else MissionOutputType.COLLECTION_FRAME,
        stop_conditions=("one completed run",),
        analysis_policy="evidence-gated-v1", retention_policy="mission-only", created_by="fixture",
        confirmed_at=datetime.now(timezone.utc),
    )
    if market:
        mission, _ = await ConfirmMarketBriefUseCase(repository, store).execute(
            workspace_id=workspace.workspace_id, confirmed_by="fixture", manifest=manifest,
            keywords=["túi đi làm"], decision="Choose initial category", target_user="Office workers",
            problem="Carry laptop safely", geo="VN", timeframe="7d", hypothesis="Office bags solve carrying pain",
            falsifiers=["túi đi làm bất tiện"],
            alternative_hypotheses=["Backpacks solve the problem", "Existing bags are sufficient"],
            null_hypothesis="No unmet carrying pain", kill_criteria=["No independent carrying pain"],
            revision_rule="Reframe when counterevidence dominates",
        )
    else:
        mission = await CreateAttentionMissionUseCase(repository, store).execute(
            workspace.workspace_id, "Office bags", manifest, keywords=["túi đi làm"],
        )
    executor = ExecuteMissionUseCase(repository, ConnectorPluginRegistry(),
                                     AsyncMock(cluster_signals=AsyncMock(return_value=[])), store)
    return store, workspace, mission, executor


@pytest.mark.asyncio
async def test_existing_writer_seam_rechecks_before_any_ingress(repository_case, tmp_path):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    manifest = await store.get_mission_manifest(mission.id)
    ingress = AsyncMock()
    async def guard(journal):
        current = await repository_case.repository.get_mission(mission.id)
        assert current.status == "PENDING"
        raise ValueError("STALE_SCOPE")
    seam = getattr(executor, "_execute_authorized", None)
    assert seam is not None, "A host answer needs a shared writer/ingestion seam"
    with pytest.raises(ValueError, match="STALE_SCOPE"):
        await seam(mission, manifest, {}, scope_guard=guard, search_provider=ingress)
    ingress.assert_not_awaited()
    assert repository_case.counts()["observations"] == 0


def staged_answer(request):
    return dict(request_id=request["request_id"], host_task_ref="task", session_ref="chrome",
                extractor_version="tiktok-public-grid-v1", answers=[dict(
                    query_id=query["query_id"], query=query["query"], page_url=query["search_url"],
                    captured_at=datetime.now(timezone.utc).isoformat(), search_verified=True,
                    empty_state_visible=False, status="HEALTHY", records=[dict(
                        source_url="https://www.tiktok.com/@fixture/video/7417820067028536584",
                        excerpt="Túi đi làm", published_at=None,
                    )],
                ) for query in request["queries"]])


@pytest.mark.asyncio
async def test_real_host_deadline_marks_interrupted_mission_failed(repository_case, tmp_path):
    repo = repository_case.repository
    store, workspace, mission, executor = await assignment(repo, tmp_path)
    service = HostBrowserSearchService()

    async def blocked_clustering(signals):
        await asyncio.Event().wait()

    executor._clusterer.cluster_signals.side_effect = blocked_clustering
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 1, True)
        service.stage(request["request_id"], staged_answer(request))
        with pytest.raises(TimeoutError):
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
        assert (await repo.get_mission(mission.id)).status == "FAILED"
        assert (await store.list_run_journals(mission.id))[0].status == "FAILED"
        assert await store.get_mission_writer_claim(mission.id) is None
        assert repository_case.counts()["observations"] == 0
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellation", ["deadline", "repeated-cancel"])
async def test_sqlite_write_settles_before_writer_release(repository_case, tmp_path, monkeypatch, cancellation):
    if repository_case.name != "sqlite":
        pytest.skip("SQLite thread lifecycle regression")
    repo = repository_case.repository
    store, workspace, mission, executor = await assignment(repo, tmp_path)
    service = HostBrowserSearchService()
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = repo._record_observations

    def blocked_write(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("Test did not release the SQLite worker")
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, "_record_observations", blocked_write)
    submission = None
    try:
        lifetime = 1 if cancellation == "deadline" else 60
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", lifetime, True)
        service.stage(request["request_id"], staged_answer(request))
        submission = asyncio.create_task(service.submit_mission(executor, request["request_id"], "task", "chrome"))
        await asyncio.wait_for(entered.wait(), 2)
        if cancellation == "deadline":
            await asyncio.sleep(1.1)
        else:
            submission.cancel()
            await asyncio.sleep(0)
            submission.cancel()
            await asyncio.sleep(0)
        assert not submission.done(), "Cancellation returned while SQLite still held an active write"
        assert await store.get_mission_writer_claim(mission.id) is not None
        release.set()
        with pytest.raises(TimeoutError if cancellation == "deadline" else asyncio.CancelledError):
            await submission
        assert (await repo.get_mission(mission.id)).status == "FAILED"
        assert (await store.list_run_journals(mission.id))[0].status == "FAILED"
        assert await store.get_mission_writer_claim(mission.id) is None
        counts = repository_case.counts()
        assert counts["observations"] == 1
        await asyncio.sleep(0)
        assert repository_case.counts() == counts
    finally:
        release.set()
        if submission is not None:
            await asyncio.gather(submission, return_exceptions=True)
        service.close()


@pytest.mark.asyncio
async def test_cancelled_writer_acquisition_releases_committed_claim(repository_case, tmp_path, monkeypatch):
    repo = repository_case.repository
    store, workspace, mission, executor = await assignment(repo, tmp_path)
    acquired = asyncio.Event()
    resume = asyncio.Event()
    original = store.require_mission_writer

    async def pause_after_claim(*args):
        await original(*args)
        acquired.set()
        # Setup is settled, not abandoned, on cancellation: the committed claim returns only
        # after the caller's cancellation arrives, and setup must then give the claim back.
        await resume.wait()

    monkeypatch.setattr(store, "require_mission_writer", pause_after_claim)

    async def run():
        async with store.mission_run(workspace, mission.id):
            pytest.fail("Cancelled acquisition entered the mission body")

    task = asyncio.create_task(run())
    await asyncio.wait_for(acquired.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    resume.set()
    done, _ = await asyncio.wait({task}, timeout=2)
    assert done, "Cancelled acquisition did not settle after its claim committed"
    with pytest.raises(asyncio.CancelledError):
        task.result()
    assert await store.get_mission_writer_claim(mission.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_stage", ["mission", "journal"])
async def test_repeated_cancellation_settles_terminal_cleanup(repository_case, tmp_path, monkeypatch, cleanup_stage):
    repo = repository_case.repository
    store, workspace, mission, executor = await assignment(repo, tmp_path)
    service = HostBrowserSearchService()
    clustering = asyncio.Event()
    cleanup = asyncio.Event()
    release = asyncio.Event()

    async def blocked_clustering(signals):
        clustering.set()
        await asyncio.Event().wait()

    if cleanup_stage == "mission":
        # Run-bound cleanup now uses the atomic state writer; gate the actual
        # consumer boundary without restoring a silent legacy state write.
        original = repo.commit_collection_state

        async def blocked_cleanup(value, run_id):
            if value.status == "FAILED":
                cleanup.set()
                await release.wait()
            return await original(value, run_id)

        monkeypatch.setattr(repo, "commit_collection_state", blocked_cleanup)
    else:
        original = store._finish_run_journal

        async def blocked_cleanup(value, status):
            cleanup.set()
            await release.wait()
            return await original(value, status)

        monkeypatch.setattr(store, "_finish_run_journal", blocked_cleanup)

    executor._clusterer.cluster_signals.side_effect = blocked_clustering
    task = None
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        service.stage(request["request_id"], staged_answer(request))
        task = asyncio.create_task(service.submit_mission(executor, request["request_id"], "task", "chrome"))
        await asyncio.wait_for(clustering.wait(), 2)
        task.cancel()
        await asyncio.wait_for(cleanup.wait(), 2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await repo.get_mission(mission.id)).status == "FAILED"
        assert (await store.list_run_journals(mission.id))[0].status == "FAILED"
        assert await store.get_mission_writer_claim(mission.id) is None
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", [None, "2026-01-01T00:00:00+00:00"])
async def test_host_mission_uses_canonical_writer_and_never_rewrites_replayed_evidence(repository_case, tmp_path, publication):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    try:
        prepare = getattr(service, "prepare_mission", None)
        assert prepare is not None, "Mission preparation is not implemented"
        request = await prepare(executor, mission.id, "task", "chrome", 60, True)
        assert request["mode"] == "MISSION"
        assert (await repository_case.repository.get_mission(mission.id)).status == "PENDING"
        assert repository_case.counts()["observations"] == 0
        payload = staged_answer(request)
        payload["answers"][0]["records"][0]["published_at"] = publication
        service.stage(request["request_id"], payload)
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
        assert receipt["mission"]["status"] == "COMPLETED"
        assert receipt["mission"]["channel_outcomes"][0]["queried_window"] is None
        assert receipt["mission"]["evidence_frame"]["frame_digest"]
        held = await repository_case.repository.get_mission_signals(mission.id)
        assert held[0].published_at == (datetime.fromisoformat(publication) if publication else None)
        assert held[0].metadata["metric_known"] is False
        from ignis.application.use_cases.get_evidence_qualification_batch import _metric_highlight
        assert _metric_highlight(held[0]) == "Metric unmeasured"
        from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
        assert StrategicMarketReasoner()._format_metric_highlight(held[0]) == "Metric unmeasured"
        from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
        analysis = await GetMissionAnalysisUseCase(repository_case.repository, store).execute(mission.id)
        assert analysis["top_signals"][0]["metric_value"] is None
        assert analysis["top_signals"][0]["metadata"]["metric_known"] is False
        from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder
        from ignis.domain.harness_models import QualityScorecard
        html = HtmlArtifactBuilder().build_mission_report_artifact(
            mission=mission, signals=held, platform_breakdown={"tiktok": 1},
            scorecard_override=QualityScorecard(),
        )
        assert "Metric unmeasured" in html
        assert "Interest: 0.0" not in html
        counts = repository_case.counts()
        assert counts["observations"] == 1
        assert await service.submit_mission(executor, request["request_id"], "task", "chrome") == receipt
        assert repository_case.counts() == counts
    finally:
        service.close()


@pytest.mark.asyncio
async def test_unavailable_optional_source_does_not_block_required_host_collection(repository_case, tmp_path):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path, optional=("threads",))
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        service.stage(request["request_id"], staged_answer(request))
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
        outcomes = {item["connector_surface"]: item for item in receipt["mission"]["channel_outcomes"]}
        assert set(outcomes) == {"threads", "tiktok_video"}
        assert outcomes["threads"]["status"] == "NOT_REQUESTED"
        assert outcomes["tiktok_video"]["status"] == "HEALTHY"
        assert repository_case.counts()["observations"] == 1
    finally:
        service.close()


@pytest.mark.asyncio
async def test_host_excerpt_is_masked_in_persisted_evidence_and_analysis(repository_case, tmp_path):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        payload = staged_answer(request)
        payload["answers"][0]["records"][0]["excerpt"] = "Túi đi làm: seller@example.test; 0931.405.002"
        payload["answers"][0]["records"][0]["source_url"] = "https://www.tiktok.com/@fixture/video/7492034084227599623"
        service.stage(request["request_id"], payload)
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
        assert receipt["observations"][0]["excerpt"] == "Túi đi làm: [REDACTED_EMAIL]; [REDACTED_PHONE]"
        held = await repository_case.repository.get_mission_signals(mission.id)
        assert held[0].raw_title == "Túi đi làm: [REDACTED_EMAIL]; [REDACTED_PHONE]"
        assert held[0].metadata["excerpt"] == "Túi đi làm: [REDACTED_EMAIL]; [REDACTED_PHONE]"
        # The handle is the poster's; the stored link is rebuilt from the content id (Spec 015).
        assert held[0].source_url == "https://www.tiktok.com/share/video/7492034084227599623"
        from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
        analysis = await GetMissionAnalysisUseCase(repository_case.repository, store).execute(mission.id)
        assert analysis["top_signals"][0]["url"] == "https://www.tiktok.com/share/video/7492034084227599623"
        assert "@fixture" not in str(analysis)
        assert "seller@example.test" not in str(analysis)
        assert "0931.405.002" not in str(analysis)
    finally:
        service.close()


class LocalYouTube(IConnectorPlugin):
    """No external I/O; use the real registry and mission writer for quota admission."""
    platform = PlatformType.YOUTUBE
    name = "Local YouTube fixture"
    http_authority = "official_api"

    async def is_healthy(self):
        return True

    async def fetch_signals(self, **kwargs):
        return []

    async def search_signals(self, keywords, geo, timeframe, limit=20, attestation=None, **kwargs):
        if attestation is not None:
            for query in keywords:
                attestation.executed(query)
        return [TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Túi đi làm",
                            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                            metric_value=100, geo_code=geo)]


@pytest.mark.asyncio
async def test_ordinary_execution_and_shared_writer_seam_preserve_ingress_contract(repository_case, tmp_path):
    repo = repository_case.repository
    results = []
    for route in ("ordinary", "shared_seam"):
        root = tmp_path / route
        root.mkdir()
        store, workspace, mission, executor = await assignment(repo, root, required=("youtube",))
        executor._registry.register(LocalYouTube())
        if route == "ordinary":
            result = await executor.execute(mission.id)
        else:
            manifest, requirements = await executor._require_manifest_authority(mission)
            await executor._require_confirmed_brief(mission)
            result = await executor._execute_authorized(mission, manifest, requirements)
        signals = await repo.get_mission_signals(mission.id)
        assert (await repo.get_mission(mission.id)).status == "COMPLETED"
        assert len(signals) == 1
        assert result["run"]["journal_status"] == "COMPLETED"
        assert result["evidence_frame"]["frame_digest"]
        results.append((signals[0].raw_title, signals[0].metric_value,
                        result["channel_outcomes"][0]["status"],
                        result["channel_outcomes"][0]["connector_surface"]))
    assert results == [("Túi đi làm", 100.0, "HEALTHY", "youtube")] * 2
    assert repository_case.counts()["observations"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("youtube_required", [True, False])
async def test_host_does_not_consume_other_surface_quota(repository_case, tmp_path, youtube_required):
    required = ("tiktok_video", "youtube") if youtube_required else ("tiktok_video",)
    optional = () if youtube_required else ("youtube",)
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path,
                                                           required=required, optional=optional)
    executor._registry.register(LocalYouTube())
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        service.stage(request["request_id"], staged_answer(request))
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
        outcomes = {item["connector_surface"]: item for item in receipt["mission"]["channel_outcomes"]}
        assert set(outcomes) == {"youtube", "tiktok_video"}
        assert outcomes["youtube"]["status"] == "HEALTHY"
        assert outcomes["tiktok_video"]["status"] == "HEALTHY"
        assert repository_case.counts()["observations"] == 2
    finally:
        service.close()


@pytest.mark.asyncio
async def test_market_preparation_preserves_falsifiers_and_refuses_query_budget_overrun(repository_case, tmp_path):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path, market=True, budget=1)
    service = HostBrowserSearchService()
    try:
        with pytest.raises(InvalidMissionAuthorizationError):
            await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        assert repository_case.counts()["observations"] == 0
        assert (await repository_case.repository.get_mission(mission.id)).status == "PENDING"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_market_query_union_and_unknown_window_do_not_bypass_qualification(repository_case, tmp_path):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path, market=True)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        assert [query["query"] for query in request["queries"]] == ["túi đi làm", "túi đi làm bất tiện"]
        service.stage(request["request_id"], staged_answer(request))
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
        from ignis.application.use_cases.get_evidence_qualification_batch import GetEvidenceQualificationBatchUseCase
        batch = await GetEvidenceQualificationBatchUseCase(repository_case.repository, store).execute(str(mission.id))
        assert batch["status"] == "QUALIFICATION_REQUIRED"
        assert receipt["mission"]["channel_outcomes"][0]["queried_window"] is None
        assert not await store.list_mission_claims(mission.id)
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("attestation", [{}, {"query_outcomes": []}])
async def test_partial_outcome_preserves_the_provided_attestation(repository_case, tmp_path, attestation):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    async with store.mission_run(workspace, mission.id) as journal:
        await executor._record_probe_outcomes(
            mission, journal, [SurfaceProbeResult(
                platform="tiktok", connector_surface="tiktok_video", status=ChannelHealthStatus.DEGRADED,
                signals_collected=1, note="Partial results", scope_attestation=attestation,
            )], collection_plan_digest="p" * 64,
        )
    outcomes = await store.get_latest_completed_probe_outcomes(mission.id)
    assert outcomes[0].scope_attestation == attestation
    assert not outcomes[0].measures_zero


@pytest.mark.asyncio
async def test_partial_host_search_persists_degraded_frame_and_withholds_market_verdict(repository_case, tmp_path):
    repo = repository_case.repository
    store, workspace, mission, executor = await assignment(repo, tmp_path, market=True)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        answer = staged_answer(request)
        answer["answers"][0].update(status="DEGRADED", search_verified=False, records=[])
        service.stage(request["request_id"], answer)
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
        assert receipt["mission"]["status"] == "COMPLETED"
        outcomes = await store.get_latest_completed_probe_outcomes(mission.id)
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.status.value == "DEGRADED"
        assert outcome.signals_collected == 1
        assert outcome.measures_zero is False
        assert [item["status"] for item in outcome.scope_attestation["query_outcomes"]] == ["DEGRADED", "HEALTHY"]
        assert len(await repo.get_mission_signals(mission.id)) == 1
        from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
        analysis = await GetMissionAnalysisUseCase(repo, store).execute(mission.id)
        assert analysis["analysis_status"] == "INSUFFICIENT_EVIDENCE"
        assert "REQUIRED_CHANNEL_NOT_MEASURED:tiktok_video:DEGRADED" in analysis["gap_report"]["failed_gates"]
        assert not await store.list_mission_claims(mission.id)
    finally:
        service.close()


@pytest.mark.asyncio
async def test_writer_conflict_terminates_ticket_without_overwriting_evidence(repository_case, tmp_path):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        service.stage(request["request_id"], staged_answer(request))
        async with store.mission_run(workspace, mission.id):
            with pytest.raises(Exception) as caught:
                await service.submit_mission(executor, request["request_id"], "task", "chrome")
            assert "writer" in str(caught.value).lower() or "active" in str(caught.value).lower()
        assert repository_case.counts()["observations"] == 0
        with pytest.raises(ValueError):
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
    finally:
        service.close()


@pytest.mark.asyncio
async def test_changed_mission_scope_rejects_staged_answer_before_evidence_write(repository_case, tmp_path):
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    try:
        prepare = getattr(service, "prepare_mission", None)
        assert prepare is not None, "Mission preparation is not implemented"
        request = await prepare(executor, mission.id, "task", "chrome", 60, True)
        service.stage(request["request_id"], staged_answer(request))
        mission.keywords.append("different scope")
        await repository_case.repository.update_mission(mission)
        with pytest.raises(ValueError, match="STALE_SCOPE") as caught:
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
        failure = getattr(caught.value, "host_search_failure", None)
        assert failure is None, "A preflight refusal never started an ingestion run"
        assert not await store.list_run_journals(mission.id)
        assert repository_case.counts()["observations"] == 0
        with pytest.raises(ValueError):
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_scope", ["manifest", "brief", "evidence_frame"])
async def test_persisted_scope_changes_reject_host_answer_before_ingress(repository_case, tmp_path, changed_scope):
    repo = repository_case.repository
    store, workspace, mission, executor = await assignment(repo, tmp_path, market=True)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        service.stage(request["request_id"], staged_answer(request))
        if changed_scope == "manifest":
            # Simulate an out-of-band persisted change; the normal API is immutable.
            repository_case.query_one(
                "UPDATE mission_manifests SET outcome = ? WHERE mission_id = ? RETURNING mission_id",
                "UPDATE mission_manifests SET outcome = %s WHERE mission_id = %s RETURNING mission_id",
                ("Different assigned outcome", str(mission.id)),
            )
        elif changed_scope == "brief":
            repository_case.query_one(
                "UPDATE market_brief_revisions SET hypothesis = ? WHERE mission_id = ? RETURNING mission_id",
                "UPDATE market_brief_revisions SET hypothesis = %s WHERE mission_id = %s RETURNING mission_id",
                ("Different business hypothesis", str(mission.id)),
            )
        else:
            await repo.save_signals([TrendSignal(
                platform=PlatformType.TIKTOK, raw_title="Existing independently collected evidence",
                metric_value=0.0, source_url="https://www.tiktok.com/share/video/123",
                mission_id=mission.id,
            )])
        counts_before_submit = repository_case.counts()
        with pytest.raises(ValueError, match="STALE_SCOPE"):
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
        assert repository_case.counts()["observations"] == counts_before_submit["observations"]
        assert (await repo.get_mission(mission.id)).status == "PENDING"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_concurrent_submit_and_cancel_cannot_claim_running_host_ingestion(repository_case, tmp_path, monkeypatch):
    import ignis.application.use_cases.host_browser_mission as module
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    entered, release = asyncio.Event(), asyncio.Event()
    async def ingress(executor, binding, receipt, **kwargs):
        entered.set()
        await release.wait()
        return dict(status="COMPLETED")
    monkeypatch.setattr(module, "ingest_scope", ingress)
    request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
    service.stage(request["request_id"], staged_answer(request))
    first = asyncio.create_task(service.submit_mission(executor, request["request_id"], "task", "chrome"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(ValueError):
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
        with pytest.raises(ValueError):
            service.cancel(request["request_id"], "task", "chrome")
        release.set()
        assert (await first)["status"] == "ACCEPTED"
    finally:
        release.set()
        await first
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("delay_at", ["workspace", "vocabulary", "clustering"])
async def test_expiry_during_mission_await_refuses_evidence_write(repository_case, tmp_path, monkeypatch, delay_at):
    import ignis.application.use_cases.host_browser_search as tickets
    import ignis.application.use_cases.host_browser_mission as ingress
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        service.stage(request["request_id"], staged_answer(request))
        current = datetime.now(timezone.utc)
        class Clock(datetime):
            @classmethod
            def now(cls, zone=None):
                return current
        monkeypatch.setattr(tickets, "datetime", Clock)
        monkeypatch.setattr(ingress, "datetime", Clock)
        async def delay(*args):
            nonlocal current
            current = datetime.fromisoformat(request["expires_at"]) + timedelta(seconds=1)
            return workspace if delay_at == "workspace" else []
        if delay_at == "workspace":
            monkeypatch.setattr(executor, "_run_workspace", delay)
        elif delay_at == "vocabulary":
            monkeypatch.setattr(executor, "_synchronize_vocabulary", delay)
        else:
            monkeypatch.setattr(executor._clusterer, "cluster_signals", delay)
        with pytest.raises(ValueError, match="expired"):
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
        assert repository_case.counts()["observations"] == 0
        assert await store.get_mission_writer_claim(mission.id) is None
        with pytest.raises(ValueError):
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
    finally:
        service.close()


@pytest.mark.asyncio
async def test_prepare_does_not_evict_submitting_receipt_and_retention_is_finite(repository_case, tmp_path, monkeypatch):
    import ignis.application.use_cases.host_browser_search as tickets
    import ignis.application.use_cases.host_browser_mission as ingress
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    entered, release = asyncio.Event(), asyncio.Event()
    async def hold(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"status": "COMPLETED"}
    monkeypatch.setattr(ingress, "ingest_scope", hold)
    request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
    service.stage(request["request_id"], staged_answer(request))
    current = datetime.now(timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, zone=None):
            return current
    monkeypatch.setattr(tickets, "datetime", Clock)
    first = asyncio.create_task(service.submit_mission(executor, request["request_id"], "task", "chrome"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        current = datetime.fromisoformat(request["expires_at"]) + timedelta(seconds=1)
        service.prepare("other", "chrome", ["túi laptop"], 3, 60, True)
        assert request["request_id"] in service._tickets
        release.set()
        receipt = await first
        service.prepare("other", "chrome", ["túi laptop"], 3, 60, True)
        assert await service.submit_mission(executor, request["request_id"], "task", "chrome") == receipt
        current += timedelta(seconds=61)
        service.prepare("other", "chrome", ["túi laptop"], 3, 60, True)
        with pytest.raises(ValueError, match="UNKNOWN_REQUEST"):
            await service.submit_mission(executor, request["request_id"], "task", "chrome")
    finally:
        release.set()
        await first
        service.close()


@pytest.mark.asyncio
async def test_host_mission_stores_no_poster_attribution(repository_case, tmp_path):
    """Constitution VII: the poster's display name in TikTok's image label never reaches storage."""
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        payload = staged_answer(request)
        payload["answers"][0]["records"][0]["excerpt"] = (
            "Túi đi làm siêu gọn do Fixture Poster tạo với bản nhạc âm thanh gốc - Fixture Poster"
        )
        service.stage(request["request_id"], payload)
        await service.submit_mission(executor, request["request_id"], "task", "chrome")
        held = await repository_case.repository.get_mission_signals(mission.id)
        assert [signal.raw_title for signal in held] == ["Túi đi làm siêu gọn"]
        assert "Fixture Poster" not in repr([signal.metadata for signal in held])
    finally:
        service.close()


@pytest.mark.asyncio
async def test_host_mission_applies_attribution_wording_added_in_the_database(repository_case, tmp_path):
    """A locale an operator registered must clean the ticket before it is frozen (PR #79 review)."""
    repo = repository_case.repository
    if repository_case.dsn:
        # The shared PostgreSQL fixture holds the evidence schema only; the vocabulary tables come
        # from the lexicon migrations, applied here as the full chain would.
        import psycopg
        from pathlib import Path
        sql = Path(__file__).resolve().parents[2] / "sql"
        with psycopg.connect(repository_case.dsn) as conn:
            for migration in ("003_market_lexicons.sql", "034_tiktok_attribution.sql"):
                conn.execute((sql / migration).read_text(encoding="utf-8"))
    await repo.register_lexicon_terms("tiktok_attribution", ["created by {author} with"], "ui_attribution")
    store, workspace, mission, executor = await assignment(repo, tmp_path)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        payload = staged_answer(request)
        payload["answers"][0]["records"][0]["excerpt"] = "Work bag review created by Fixture Poster with original sound"
        service.stage(request["request_id"], payload)
        await service.submit_mission(executor, request["request_id"], "task", "chrome")
        held = await repo.get_mission_signals(mission.id)
        assert [signal.raw_title for signal in held] == ["Work bag review"]
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["tiktok", "threads"])
async def test_composed_host_sources_share_one_canonical_run_and_source_outcomes(repository_case, tmp_path, monkeypatch, first):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from ignis.application.use_cases import host_browser_search as module
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    store, _, mission, executor = await assignment(repository_case.repository, tmp_path, market=True,
        required=("tiktok_video", "threads", "youtube"), youtube_budget=2)
    executor._registry.register(LocalYouTube())
    service = HostBrowserSearchService()
    try:
        descriptors = {source: await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source=source)
                       for source in ("tiktok", "threads")}
        for request in descriptors.values():
            assert [q["query"] for q in request["queries"]] == ["túi đi làm", "túi đi làm bất tiện"]
            service.stage(request["request_id"], host_answer(request))
        a, b = descriptors[first], descriptors["threads" if first == "tiktok" else "tiktok"]
        receipts = await asyncio.gather(service.submit_mission(executor, a["request_id"], "task", "chrome"),
                                        service.submit_mission(executor, b["request_id"], "task", "chrome"))
        assert receipts[0]["request_id"] == a["request_id"]
        assert receipts[1]["request_id"] == b["request_id"]
        assert {k: v for k, v in receipts[0].items() if k != "request_id"} == {k: v for k, v in receipts[1].items() if k != "request_id"}
        assert await service.submit_mission(executor, b["request_id"], "task", "chrome") == receipts[1]
        journals = await store.list_run_journals(mission.id)
        assert len(journals) == 1 and journals[0].status == "COMPLETED"
        probes = {p.connector_surface: p for p in await store.get_latest_completed_probe_outcomes(mission.id)}
        assert set(probes) == {"tiktok_video", "threads", "youtube"}
        assert all(len(probes[s].scope_attestation["query_outcomes"]) == 2 for s in ("tiktok_video", "threads"))
        signals = await repository_case.repository.get_mission_signals(mission.id)
        assert sum(s.platform is PlatformType.THREADS for s in signals) == 2
        assert all(s.metadata["connector_surface"] == "threads" for s in signals if s.platform is PlatformType.THREADS)
        assert await store.get_mission_writer_claim(mission.id) is None
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "duplicate", "frame", "caller", "cancel", "expiry", "rejection"])
async def test_group_faults_never_collect_a_sibling_or_fallback(repository_case, tmp_path, monkeypatch, fault):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from ignis.application.use_cases import host_browser_search as module
    from ignis.infrastructure.caller_storage import current_caller_storage
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    store, _, mission, executor = await assignment(repository_case.repository, tmp_path,
                                                   required=("tiktok_video", "threads"))
    service = HostBrowserSearchService()
    token = current_caller_storage.set(object())
    try:
        a = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        service.stage(a["request_id"], host_answer(a))
        if fault == "duplicate":
            with pytest.raises(ValueError):
                await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
            assert repository_case.counts()["observations"] == 0
            return
        b = None
        if fault != "missing":
            b = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
            service.stage(b["request_id"], host_answer(b))
        if fault == "frame":
            mission.keywords[0] = "changed scope"
            await repository_case.repository.update_mission(mission)
        elif fault == "caller":
            current_caller_storage.set(object())
        elif fault == "cancel":
            service.cancel(a["request_id"], "task", "chrome")
        elif fault == "expiry":
            class Clock(datetime):
                @classmethod
                def now(cls, zone=None):
                    return datetime.fromisoformat(a["expires_at"]) + timedelta(seconds=1)
            monkeypatch.setattr(module, "datetime", Clock)
        elif fault == "rejection":
            with pytest.raises(ValueError):
                service.stage(a["request_id"], {"invalid": "fixture"})
        target = b if fault in {"cancel", "expiry", "rejection"} else a
        with pytest.raises(ValueError):
            await service.submit_mission(executor, target["request_id"], "task", "chrome")
        assert repository_case.counts()["observations"] == 0
        assert not await store.list_run_journals(mission.id)
    finally:
        current_caller_storage.reset(token)
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["cancel", "expiry", "uncertain", "shutdown"])
async def test_composed_sqlite_commit_drains_and_readback_never_retries_a_sibling(repository_case, tmp_path, monkeypatch, event):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from ignis.application.use_cases import host_browser_search as module
    if repository_case.name != "sqlite":
        pytest.skip("SQLite worker fault injection; normal host contracts run on both backends")
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    store, _, mission, executor = await assignment(repository_case.repository, tmp_path,
                                                   required=("tiktok_video", "threads"))
    repo = repository_case.repository
    service = HostBrowserSearchService()
    release, entered = threading.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    original_connection = repo._get_connection
    armed = True
    class CommitBoundary:
        def __init__(self, conn):
            self.conn = conn
        def __getattr__(self, name):
            return getattr(self.conn, name)
        def __enter__(self):
            self.conn.__enter__()
            return self
        def __exit__(self, *args):
            return self.conn.__exit__(*args)
        def commit(self):
            nonlocal armed
            self.conn.commit()
            if armed and self.conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 2:
                armed = False
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(8):
                    raise RuntimeError("Worker fixture was not released")
                if event == "uncertain":
                    raise RuntimeError("Synthetic lost acknowledgement after commit")
    first, stopping = None, None
    try:
        a = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        b = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
        for request in (a, b):
            service.stage(request["request_id"], host_answer(request))
        monkeypatch.setattr(repo, "_get_connection", lambda: CommitBoundary(original_connection()))
        first = asyncio.create_task(service.submit_mission(executor, a["request_id"], "task", "chrome"))
        await asyncio.wait_for(entered.wait(), 3)
        assert repository_case.counts()["observations"] == 2
        assert await store.get_mission_writer_claim(mission.id) is not None
        if event == "shutdown":
            stopping = asyncio.create_task(service.aclose())
        elif event == "cancel":
            stopping = asyncio.create_task(service.cancel_mission(b["request_id"], "task", "chrome"))
            first.cancel()
            await asyncio.sleep(0)
            first.cancel()
        elif event == "expiry":
            class Clock(datetime):
                @classmethod
                def now(cls, zone=None):
                    return datetime.fromisoformat(a["expires_at"]) + timedelta(seconds=1)
            monkeypatch.setattr(module, "datetime", Clock)
        await asyncio.sleep(0)
        assert not first.done()
        assert await store.get_mission_writer_claim(mission.id) is not None
        release.set()
        await asyncio.gather(first, *([stopping] if stopping else []), return_exceptions=True)
        if event == "shutdown":
            assert not service._tickets and not service._groups
            assert await store.get_mission_writer_claim(mission.id) is None
            assert repository_case.counts()["observations"] == 2
            journals = await store.list_run_journals(mission.id)
            assert len(journals) == 1 and journals[0].status == "FAILED"
            return
        with pytest.raises(ValueError) as retry:
            await service.submit_mission(executor, b["request_id"], "task", "chrome")
        failure = retry.value.host_search_failure
        assert failure["readback"]["observations"] == 2 and failure["readback"]["writer_active"] is False
        journals = await store.list_run_journals(mission.id)
        assert len(journals) == 1 and journals[0].status == "FAILED"
        assert await store.get_mission_writer_claim(mission.id) is None
        assert repository_case.counts()["observations"] == 2
    finally:
        release.set()
        if first:
            await asyncio.gather(first, *([stopping] if stopping else []), return_exceptions=True)
        service.close()


@pytest.mark.asyncio
async def test_composed_nonhost_budget_cannot_be_bypassed(repository_case, tmp_path, monkeypatch):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay
    from ignis.application.use_cases import host_browser_search as module
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    store, _, mission, executor = await assignment(repository_case.repository, tmp_path, market=True,
        required=("tiktok_video", "threads", "youtube"), youtube_budget=1)
    executor._registry.register(LocalYouTube())
    service = HostBrowserSearchService()
    try:
        with pytest.raises(InvalidMissionAuthorizationError):
            await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
        assert not await store.list_run_journals(mission.id)
        assert repository_case.counts()["observations"] == 0
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "concurrent"])
async def test_group_preflight_is_owned_before_writer_entry(repository_case, tmp_path, monkeypatch, action):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from ignis.application.use_cases import host_browser_search as module
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    store, _, mission, executor = await assignment(repository_case.repository, tmp_path,
                                                   required=("tiktok_video", "threads"))
    service = HostBrowserSearchService()
    entered, release, second_read = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = store.load_mission_evidence_snapshot
    calls = 0
    async def gated_snapshot(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        else:
            second_read.set()
        return await original(*args)
    tasks = []
    try:
        a = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        b = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
        for request in (a, b):
            service.stage(request["request_id"], host_answer(request))
        monkeypatch.setattr(store, "load_mission_evidence_snapshot", gated_snapshot)
        first = asyncio.create_task(service.submit_mission(executor, a["request_id"], "task", "chrome"))
        tasks.append(first)
        await asyncio.wait_for(entered.wait(), 3)
        if action == "cancel":
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert service._tickets[b["request_id"]]["state"] == "CANCELLED"
            with pytest.raises(ValueError):
                await service.submit_mission(executor, b["request_id"], "task", "chrome")
            assert not await store.list_run_journals(mission.id)
        else:
            second = asyncio.create_task(service.submit_mission(executor, b["request_id"], "task", "chrome"))
            tasks.append(second)
            await asyncio.sleep(0)
            assert not second_read.is_set(), "A sibling entered preflight before group admission was claimed"
            release.set()
            receipts = await asyncio.gather(first, second)
            assert receipts[0]["request_id"] == a["request_id"]
            assert receipts[1]["request_id"] == b["request_id"]
            assert {k: v for k, v in receipts[0].items() if k != "request_id"} == {k: v for k, v in receipts[1].items() if k != "request_id"}
            assert len(await store.list_run_journals(mission.id)) == 1
    finally:
        release.set()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["tiktok", "threads"])
async def test_prepared_optional_host_sibling_joins_one_run_without_internal_collection(repository_case, tmp_path, monkeypatch, first):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from ignis.application.use_cases import host_browser_search as module
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    store, _, mission, executor = await assignment(repository_case.repository, tmp_path, optional=("threads",))
    attempts = []
    class ForbiddenInternalThreads(LocalYouTube):
        platform = PlatformType.THREADS
        async def search_signals(self, *args, **kwargs):
            attempts.append("internal collection")
            raise AssertionError("A staged host source reached the internal Threads collector")
    executor._registry.register(ForbiddenInternalThreads())
    service = HostBrowserSearchService()
    try:
        sources = (first, "threads" if first == "tiktok" else "tiktok")
        requests = [await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source=s) for s in sources]
        for request in requests:
            service.stage(request["request_id"], host_answer(request))
        receipts = await asyncio.gather(*(service.submit_mission(executor, r["request_id"], "task", "chrome") for r in requests))
        assert [r["request_id"] for r in receipts] == [r["request_id"] for r in requests]
        assert {k: v for k, v in receipts[0].items() if k != "request_id"} == {k: v for k, v in receipts[1].items() if k != "request_id"}
        assert len(await store.list_run_journals(mission.id)) == 1
        assert repository_case.counts()["observations"] == 2
        assert attempts == []
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["tiktok", "threads"])
async def test_host_exact_publication_survives_pre_strip_self_exclusion(repository_case, tmp_path, monkeypatch, source):
    from copy import deepcopy
    from ignis.application.use_cases import host_browser_search as module
    from ignis.domain.self_content import SelfIdentity
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    _, _, mission, executor = await assignment(repository_case.repository, tmp_path, required=("tiktok_video" if source == "tiktok" else source,))
    executor._registry.register_self_identities([SelfIdentity(source, username="synthetic.header")])
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source=source)
        payload = host_answer(request)
        own = payload["answers"][0]["records"][0]
        public = deepcopy(own)
        public["source_url"] = public["source_url"].replace("synthetic.header", "synthetic.other").replace("Synthetic020Q0", "Synthetic027")
        if source == "tiktok":
            prefix, identifier = public["source_url"].rsplit("/", 1)
            public["source_url"] = prefix + "/" + str(int(identifier) + 1)
        payload["answers"][0]["records"].append(public)
        service.stage(request["request_id"], payload)
        await service.submit_mission(executor, request["request_id"], "task", "chrome")
        signals = await repository_case.repository.get_mission_signals(mission.id)
        assert len(signals) == 1
        assert signals[0].published_at.microsecond == 123456
        assert signals[0].published_at != signals[0].captured_at
        assert "synthetic.header" not in repr(signals) and "synthetic.other" not in repr(signals)
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["cancel", "accepted", "stale", "rejected", "expired"])
async def test_review_terminal_or_stale_group_never_blocks_repreparation(repository_case, tmp_path, monkeypatch, terminal):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from ignis.application.use_cases import host_browser_search as module
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    store, workspace, mission, executor = await assignment(repository_case.repository, tmp_path, required=("threads",))
    service = HostBrowserSearchService()
    try:
        first = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
        old = service._tickets[first["request_id"]]["group"]
        if terminal == "cancel":
            await service.cancel_mission(first["request_id"], "task", "chrome")
        elif terminal == "accepted":
            service.stage(first["request_id"], host_answer(first))
            accepted = await service.submit_mission(executor, first["request_id"], "task", "chrome")
        elif terminal == "rejected":
            invalid = host_answer(first)
            invalid["answers"][0]["query"] = "unapproved synthetic query"
            with pytest.raises(ValueError):
                service.stage(first["request_id"], invalid)
        elif terminal == "expired":
            deadline = service._tickets[first["request_id"]]["request"].expires_at
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return deadline + timedelta(seconds=1)
            monkeypatch.setattr(module, "datetime", Clock)
        else:
            mission.keywords = ["new synthetic scope"]
            await repository_case.repository.update_mission(mission)
        target = mission
        if terminal == "accepted":
            # Collection completion is terminal. The supported flow creates a fresh mission,
            # just as each watchlist run does; do not reopen the completed mission by editing it.
            from dataclasses import replace
            with pytest.raises(ValueError, match="not pending collection"):
                await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
            assert old.key not in service._groups
            manifest = replace(await store.get_mission_manifest(mission.id), mission_id=None)
            target = await CreateAttentionMissionUseCase(repository_case.repository, store).execute(
                workspace.workspace_id, "Replacement host run", manifest, keywords=["túi đi làm"])
        replacement = await service.prepare_mission(executor, target.id, "task", "chrome", 60, True, source="threads")
        assert replacement["request_id"] != first["request_id"]
        assert service._tickets[replacement["request_id"]]["group"] is not old
        assert old.state == {"cancel": "CANCELLED", "accepted": "ACCEPTED", "stale": "REJECTED", "rejected": "REJECTED", "expired": "EXPIRED"}[terminal]
        assert first["request_id"] in service._tickets
        if terminal == "accepted":
            assert await service.submit_mission(executor, first["request_id"], "task", "chrome") == accepted
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["tiktok", "threads"])
@pytest.mark.parametrize("empty", [False, True])
async def test_review_mission_vocabulary_never_mutates_tactical_source_snapshots(repository_case, tmp_path, monkeypatch, source, empty):
    from types import SimpleNamespace
    from ignis.application.use_cases import host_browser_search as module
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    from ignis.infrastructure.caller_storage import current_caller_storage
    token = current_caller_storage.set(object())
    service = HostBrowserSearchService()
    before = {s: service.attribution_templates_for(s) for s in ("tiktok", "threads")}
    async def vocabulary(repo):
        return SimpleNamespace(tiktok_attribution=[] if empty else ["Synthetic custom {author}"],
                               threads_attribution=[] if empty else ["Synthetic caller {author}"])
    monkeypatch.setattr(module, "load_market_vocabulary", vocabulary)
    _, _, mission, executor = await assignment(repository_case.repository, tmp_path, required=("threads",))
    try:
        if empty:
            with pytest.raises(module.AttributionVocabularyMissing):
                await service.refresh_attribution_templates(executor._repo, source=source)
        else:
            request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
            assert service._tickets[request["request_id"]]["attribution_templates"] == ("Synthetic caller {author}",)
        current_caller_storage.set(object())
        for selected in ("tiktok", "threads"):
            assert service.attribution_templates_for(selected) == before[selected]
            request = service.prepare("other-caller", "chrome", ["synthetic"], 3, 60, True, source=selected)
            assert service._tickets[request["request_id"]]["attribution_templates"] == before[selected]
    finally:
        service.close()
        current_caller_storage.reset(token)


@pytest.mark.asyncio
async def test_review_group_failure_receipts_keep_each_callers_request_id(repository_case, tmp_path, monkeypatch):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from ignis.application.use_cases import host_browser_search as module
    from ignis.application.use_cases import host_browser_mission
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    _, _, mission, executor = await assignment(repository_case.repository, tmp_path, required=("tiktok_video", "threads"))
    service = HostBrowserSearchService()
    async def fail(*args, **kwargs):
        raise RuntimeError("Synthetic ingestion failure")
    monkeypatch.setattr(host_browser_mission, "ingest_scope", fail)
    try:
        requests = [await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source=s)
                    for s in ("tiktok", "threads")]
        for request in requests:
            service.stage(request["request_id"], host_answer(request))
        errors = await asyncio.gather(*(service.submit_mission(executor, request["request_id"], "task", "chrome")
                                        for request in requests), return_exceptions=True)
        assert [error.host_search_failure["request_id"] for error in errors] == [request["request_id"] for request in requests]
        for request in reversed(requests):
            with pytest.raises(Exception) as caught:
                await service.submit_mission(executor, request["request_id"], "task", "chrome")
            assert caught.value.host_search_failure["request_id"] == request["request_id"]
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", ["vocabulary", "scope", "identity", "relay"])
async def test_review_second_prepare_failure_closes_the_first_sibling(repository_case, tmp_path, monkeypatch, failure_at):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay
    from ignis.application.use_cases import host_browser_search as module
    from ignis.application.use_cases import host_browser_mission
    from ignis.infrastructure.auth.self_identity import SelfIdentityRegistry
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    _, _, mission, executor = await assignment(repository_case.repository, tmp_path, required=("tiktok_video", "threads"))
    service = HostBrowserSearchService()
    async def fail(*args, **kwargs):
        raise ValueError("Synthetic second preparation failure")
    def relay_failure(*args):
        raise ValueError("Synthetic second preparation failure")
    try:
        first = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        ticket = service._tickets[first["request_id"]]
        if failure_at == "vocabulary":
            monkeypatch.setattr(service, "refresh_attribution_templates", fail)
        elif failure_at == "scope":
            monkeypatch.setattr(host_browser_mission, "prepare_scope", fail)
        elif failure_at == "identity":
            monkeypatch.setattr(SelfIdentityRegistry, "load", fail)
        else:
            monkeypatch.setattr(module, "LoopbackRelay", relay_failure)
        with pytest.raises(ValueError, match="Synthetic second"):
            await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
        assert ticket["state"] == "REJECTED"
        # The public await returns only after the sibling's transport has closed.
        assert ticket["relay"].closed
    finally:
        service.close()
