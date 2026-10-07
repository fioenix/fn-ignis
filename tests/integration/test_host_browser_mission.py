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


async def assignment(repository, tmp_path, *, market=False, budget=2, required=("tiktok_video",), optional=()):
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
        quota_budget={"queries": budget, "youtube_search_calls": 1},
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
    original = store.require_mission_writer

    async def pause_after_claim(*args):
        await original(*args)
        acquired.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(store, "require_mission_writer", pause_after_claim)

    async def run():
        async with store.mission_run(workspace, mission.id):
            pytest.fail("Cancelled acquisition entered the mission body")

    task = asyncio.create_task(run())
    await asyncio.wait_for(acquired.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
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
        assert held[0].source_url == "https://www.tiktok.com/@fixture/video/7492034084227599623"
        from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
        analysis = await GetMissionAnalysisUseCase(repository_case.repository, store).execute(mission.id)
        assert analysis["top_signals"][0]["url"] == "https://www.tiktok.com/@fixture/video/7492034084227599623"
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
        assert failure is not None, "Failed ingestion needs a journal identity for readback"
        assert failure["run"]["run_id"]
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
                metric_value=0.0, source_url="https://www.tiktok.com/@fixture/video/123",
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
    async def ingress(executor, binding, receipt):
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
    async def hold(*args):
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
