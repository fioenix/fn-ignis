"""Cluster display labels are outside the evidence-frame identity."""
import sqlite3

import pytest

from copy import deepcopy
from uuid import uuid4

from ignis.domain.entities import TopicCluster
from ignis.domain.research_workspace import build_evidence_frame


def test_cluster_label_is_not_source_metadata_or_membership():
    cluster = TopicCluster(canonical_name="Synthetic topic", category="beauty")
    observation = {"observation_id": str(uuid4()), "cluster_id": str(cluster.id),
                   "metadata": {"category": "source-category"}, "raw_title": "Evidence"}
    kwargs = dict(mission_id=uuid4(), brief_revision_id=None, manifest_digest="a" * 64,
                  collection_plan_digest="b" * 64, observations=[observation],
                  qualifications=[], channel_outcomes=[], analysis_policy="test")
    before = build_evidence_frame(**kwargs)
    cluster.category = "unclassified"
    assert build_evidence_frame(**kwargs) == before
    changed = deepcopy(kwargs)
    changed["observations"][0]["metadata"]["category"] = "changed-source"
    assert build_evidence_frame(**changed).frame_digest != before.frame_digest
    changed = deepcopy(kwargs)
    changed["observations"][0]["cluster_id"] = str(uuid4())
    assert build_evidence_frame(**changed).frame_digest != before.frame_digest


@pytest.mark.asyncio
async def test_category_reset_preserves_permitted_claims_and_frame(tmp_path):
    from test_mission_claims import _eligible_mission, _observation_candidate, _signal_named
    from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
    from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    path = tmp_path / 'claims.sqlite3'
    repository = SqliteTrendRepository(str(path))
    repository, store, mission, signals, _ = await _eligible_mission(tmp_path, repository=repository)
    cluster = TopicCluster(canonical_name='Claim category control', category='beauty', signals=signals)
    await repository.save_clusters([cluster])
    for signal in signals:
        signal.cluster_id = cluster.id
    await repository.assign_observation_clusters(signals)
    frame = await load_current_evidence_frame(repository, store, mission)
    submitted = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id), frame.frame_digest,
        [_observation_candidate(_signal_named(signals, 'Demand evidence'))], created_by='test',
    )
    assert submitted['permitted'] == 1
    before = await GetMissionAnalysisUseCase(repository, store).execute(mission.id)
    snapshot = await store.load_mission_evidence_snapshot(mission.id)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE topic_clusters SET category = 'unclassified'")
    assert await GetMissionAnalysisUseCase(repository, store).execute(mission.id) == before
    assert await load_current_evidence_frame(repository, store, mission) == frame
    assert await store.load_mission_evidence_snapshot(mission.id) == snapshot
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE mission_claims SET wording = 'Changed claim content'")
    assert await GetMissionAnalysisUseCase(repository, store).execute(mission.id) != before
    await repository.close()
