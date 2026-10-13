"""Recorded public content reaches the judgment and relay projections without changing any frame.

YouTube retains a public video description in observation metadata. The qualification batch and the
relay snapshot must show it as the excerpt when no excerpt or top comment was recorded, masked like
every public text, while frame fingerprints, evidence-frame digests and prior judgments stay unchanged.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.application.use_cases.get_mission_relay_snapshot import _observation
from ignis.domain.entities import TrendSignal
from ignis.domain.research_workspace import ResearchSurface
from ignis.domain.value_objects import PlatformType
from tests.unit.test_evidence_qualification import NOW, _assessment, _market, _use_cases, research  # noqa: F401

DESCRIPTION = "Hướng dẫn n8n từng bước. Liên hệ 0912345678 hoặc demo@example.com để nhận tài liệu."


def _signal(metadata):
    return TrendSignal(platform=PlatformType.YOUTUBE, raw_title="n8n tutorial", metric_value=10.0,
                       source_url="https://www.youtube.com/watch?v=q0000000001", captured_at=NOW,
                       mission_id=uuid4(), observation_id=uuid4(), source_id=uuid4(),
                       time_provenance="exact_ingestion", metadata=metadata)


async def _record_run(store, mission, workspace):
    """One completed YouTube run with one collection plan, so the canonical evidence frame exists."""
    from pathlib import Path
    from ignis.application.ports.research_workspace_port import RunJournal
    from ignis.domain.research_workspace import MissionProbeOutcome, compute_query_fingerprint
    from ignis.domain.value_objects import GeoCode
    run_id = uuid4()
    await store.record_run_journal(RunJournal(
        run_id=run_id, mission_id=mission.id, workspace_id=workspace.workspace_id,
        journal_path=Path(f"/tmp/{run_id}.md"), sequence=1, status="COMPLETED", started_at=NOW, completed_at=NOW))
    await store.record_probe_outcomes(run_id, [MissionProbeOutcome(
        run_id=run_id, platform="youtube", connector_surface="youtube", status="HEALTHY", signals_collected=1,
        queried_keywords=("ai cho cửa hàng",), queried_window="7d",
        query_fingerprint=compute_query_fingerprint(("ai cho cửa hàng",), GeoCode.VN, "7d"),
        scope_attestation={"geo": "VN", "timeframe": "7d"}, collection_plan_digest="p" * 64, completed_at=NOW)])


async def _with_description(repository, mission, metadata):
    await repository.save_signals([TrendSignal(
        platform=PlatformType.YOUTUBE, raw_title="n8n tutorial", metric_value=10.0,
        source_url="https://www.youtube.com/watch?v=q0000000001", captured_at=NOW, mission_id=mission.id,
        metadata={"keyword": "ai cho cửa hàng", "connector_surface": "youtube", **metadata})])
    return await repository.get_mission_signals(mission.id)


@pytest.mark.asyncio
async def test_batch_shows_a_recorded_description_masked_when_no_excerpt_was_recorded(research):
    repository, store, workspace = research
    mission, _brief, _held = await _market(repository, store, workspace, titles=())
    await _with_description(repository, mission, {"description": DESCRIPTION})
    batch, _submit = _use_cases(repository, store)
    excerpt = (await batch.execute(str(mission.id)))["evidence"][0]["excerpt"]
    assert excerpt is not None, "The recorded public description was lost at the batch projection"
    assert excerpt.startswith("Hướng dẫn n8n từng bước.")
    assert "0912345678" not in excerpt and "demo@example.com" not in excerpt


@pytest.mark.parametrize("metadata, expected", [
    ({"top_comment": "comment text", "excerpt": "excerpt text", "description": DESCRIPTION}, "comment text"),
    ({"excerpt": "excerpt text", "description": DESCRIPTION}, "excerpt text"),
    ({"description": "   "}, None),
    ({"description": 42}, None),
])
@pytest.mark.asyncio
async def test_batch_keeps_recorded_excerpt_precedence(research, metadata, expected):
    repository, store, workspace = research
    mission, _brief, _held = await _market(repository, store, workspace, titles=())
    await _with_description(repository, mission, metadata)
    batch, _submit = _use_cases(repository, store)
    assert (await batch.execute(str(mission.id)))["evidence"][0]["excerpt"] == expected


def test_relay_snapshot_shows_a_recorded_description_masked():
    row = _observation(_signal({"description": DESCRIPTION}), SimpleNamespace(qualifications=(), outcomes=()),
                       ResearchSurface.MARKET, NOW)
    assert row.excerpt is not None and row.excerpt.startswith("Hướng dẫn n8n từng bước.")
    assert "0912345678" not in row.excerpt and "demo@example.com" not in row.excerpt
    recorded = _observation(_signal({"excerpt": "excerpt text", "description": DESCRIPTION}),
                            SimpleNamespace(qualifications=(), outcomes=()), ResearchSurface.MARKET, NOW)
    assert recorded.excerpt == "excerpt text"
    with pytest.raises(ValueError):
        _observation(_signal({"excerpt": 42, "description": DESCRIPTION}), SimpleNamespace(qualifications=(), outcomes=()),
                     ResearchSurface.MARKET, NOW)


@pytest.mark.asyncio
async def test_restored_excerpt_changes_no_frame_and_relabels_no_prior_judgment(research):
    repository, store, workspace = research
    mission, _brief, _held = await _market(repository, store, workspace, titles=())
    signals = await _with_description(repository, mission, {"description": DESCRIPTION})
    await _record_run(store, mission, workspace)
    batch, submit = _use_cases(repository, store)
    first = await batch.execute(str(mission.id))
    recorded = await submit.execute(str(mission.id), first["frame_fingerprint"], [
        _assessment(signals[0].observation_id, relation="CONTEXT_ONLY", purpose="CONTEXT",
                    reason_code="INSUFFICIENT_CONTENT")])
    assert recorded["status"] == "RECORDED"
    before_digest = (await load_current_evidence_frame(repository, store, mission)).frame_digest
    before = [(q.observation_id, q.relation, q.frame_fingerprint) for q in await store.list_evidence_qualifications(mission.id)]
    after_batch = await batch.execute(str(mission.id))
    assert after_batch["frame_fingerprint"] == first["frame_fingerprint"]
    assert after_batch["status"] == "READY" and after_batch["evidence"] == []
    assert (await load_current_evidence_frame(repository, store, mission)).frame_digest == before_digest
    assert [(q.observation_id, q.relation, q.frame_fingerprint)
            for q in await store.list_evidence_qualifications(mission.id)] == before
