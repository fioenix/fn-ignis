"""T012: content with no content reference is kept and counted as context, never as support (SC-010).

Without a profile link, some sightings carry nothing a reader could open. Ignis keeps them under
an `unverifiable_content` identity so they still count and stay visible, but a claim cannot rest
on what nobody outside Ignis can check: qualification admits only context or exclusion, and the
claim-binding trigger refuses a SUPPORT binding even if a support row was written around the
domain.
"""

from datetime import datetime, timezone

import pytest

from ignis.application.use_cases.get_evidence_qualification_batch import GetEvidenceQualificationBatchUseCase
from ignis.application.use_cases.submit_evidence_qualifications import SubmitEvidenceQualificationsUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from ignis.domain.entities import TrendSignal
from ignis.domain.research_workspace import (
    InvalidEvidenceQualificationError,
    QualificationRelation,
    require_verifiable_relation,
)
from ignis.domain.source_identity import IDENTITY_FROM_URL, IDENTITY_UNVERIFIABLE_CONTENT
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

from tests.unit.test_evidence_qualification import _assessment, _market, research  # noqa: F401
from tests.unit.test_mission_claims import _eligible_mission, _observation_candidate, _signal_named

NOW = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)
UNVERIFIABLE_TITLE = "Supply evidence one"


@pytest.mark.parametrize(
    "relation", [QualificationRelation.QUALIFIED_SUPPORT, QualificationRelation.QUALIFIED_CONTRADICTION]
)
def test_a_counting_relation_on_unverifiable_content_is_refused(relation):
    with pytest.raises(InvalidEvidenceQualificationError, match="context"):
        require_verifiable_relation(relation, IDENTITY_UNVERIFIABLE_CONTENT)


@pytest.mark.parametrize(
    "relation",
    [
        QualificationRelation.CONTEXT_ONLY,
        QualificationRelation.EXCLUDED_IRRELEVANT,
        QualificationRelation.UNASSESSED,
    ],
)
def test_context_exclusion_and_unassessed_stay_open_to_unverifiable_content(relation):
    require_verifiable_relation(relation, IDENTITY_UNVERIFIABLE_CONTENT)


def test_a_verifiable_source_keeps_every_relation():
    require_verifiable_relation(QualificationRelation.QUALIFIED_SUPPORT, IDENTITY_FROM_URL)


async def _unverifiable(repository, mission):
    signal = TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title="Áo khoác mặc mát, ai biết mua ở đâu không",
        captured_at=NOW,
        mission_id=mission.id,
        metadata={"keyword": "ai cho cửa hàng", "connector_surface": "tiktok_video"},
    )
    assert await repository.save_signals([signal]) == 1
    return signal


@pytest.mark.asyncio
async def test_unverifiable_content_is_kept_counted_and_visible(research):  # noqa: F811
    repository, store, workspace = research
    mission, _brief, _held = await _market(repository, store, workspace, titles=())
    signal = await _unverifiable(repository, mission)

    held = await repository.get_mission_signals(mission.id)
    batch = await GetEvidenceQualificationBatchUseCase(repository=repository, store=store).execute(str(mission.id))

    assert [s.identity_source for s in held] == [IDENTITY_UNVERIFIABLE_CONTENT]
    assert [item["observation_id"] for item in batch["evidence"]] == [str(signal.observation_id)]


@pytest.mark.asyncio
async def test_support_on_unverifiable_content_is_refused_and_context_is_recorded(research):  # noqa: F811
    repository, store, workspace = research
    mission, brief, _held = await _market(repository, store, workspace, titles=())
    signal = await _unverifiable(repository, mission)
    batch = await GetEvidenceQualificationBatchUseCase(repository=repository, store=store).execute(str(mission.id))
    submit = SubmitEvidenceQualificationsUseCase(repository=repository, store=store)

    refused = await submit.execute(str(mission.id), batch["frame_fingerprint"], [_assessment(signal.observation_id)])
    recorded = await submit.execute(
        str(mission.id),
        batch["frame_fingerprint"],
        [_assessment(signal.observation_id, relation="CONTEXT_ONLY", purpose="CONTEXT", evidence_role="CONTEXT")],
    )

    assert (refused["status"], refused["reason_code"]) == ("INVALID", "UNVERIFIABLE_SOURCE")
    assert recorded["status"] == "RECORDED", recorded
    assert [q.relation for q in await store.list_evidence_qualifications(mission.id)] == [
        QualificationRelation.CONTEXT_ONLY
    ]


async def _eligible_with_unverifiable_support(tmp_path, repository):
    """The claim fixture with one supporting sighting that names no object anyone can open.

    Its QUALIFIED_SUPPORT row is written straight through the store, around the domain refusal,
    so the claim-binding trigger is the only thing left to stop it.
    """
    save = repository.save_signals

    async def save_without_reference(signals):
        for signal in signals:
            if signal.raw_title == UNVERIFIABLE_TITLE:
                signal.source_url = None
        return await save(signals)

    repository.save_signals = save_without_reference
    _repository, store, mission, signals, frame = await _eligible_mission(tmp_path, repository=repository)
    unverifiable = _signal_named(signals, UNVERIFIABLE_TITLE)
    assert unverifiable.identity_source == IDENTITY_UNVERIFIABLE_CONTENT
    return store, mission, signals, frame, unverifiable


@pytest.mark.asyncio
async def test_a_claim_resting_only_on_unverifiable_content_is_never_permitted(tmp_path):
    repository = SqliteTrendRepository(str(tmp_path / "unverifiable.sqlite"))
    await repository._ensure_schema()
    store, mission, signals, frame, unverifiable = await _eligible_with_unverifiable_support(tmp_path, repository)

    result = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id), frame.frame_digest, [_observation_candidate(unverifiable)], created_by="host-agent"
    )

    assert result.get("permitted", 0) == 0, result
    assert not [c for c in await store.list_mission_claims(mission.id) if c.status.value == "PERMITTED"]
    # The sighting is still evidence the mission holds and shows.
    held = {str(s.observation_id) for s in await repository.get_mission_signals(mission.id)}
    assert str(unverifiable.observation_id) in held
    await repository.close()
