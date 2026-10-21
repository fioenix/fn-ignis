"""T038 review findings 12 and 14: both backends hold the same author and support rules."""

import sqlite3
from uuid import uuid4

import psycopg
import pytest

from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase

from tests.unit.test_mission_claims import _observation_candidate, _signal_named
from tests.unit.test_unverifiable_source import _eligible_with_unverifiable_support

pytestmark = pytest.mark.asyncio


def _execute(case, sqlite_text, postgres_text, params):
    if case.name.startswith("sqlite"):
        with sqlite3.connect(case.repository._db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(sqlite_text, params)
        return
    with psycopg.connect(case.dsn, autocommit=True) as conn:
        conn.execute(postgres_text, params)


async def test_a_marker_without_an_author_state_is_refused_on_both_backends(repository_case, tmp_path):
    store, mission, signals, _frame, _ = await _eligible_with_unverifiable_support(tmp_path, repository_case.repository)
    observation = str(signals[0].observation_id)
    _execute(repository_case, "DELETE FROM mission_evidence WHERE observation_id = ?",
             "DELETE FROM mission_evidence WHERE observation_id = %s", (observation,))

    with pytest.raises((sqlite3.IntegrityError, psycopg.errors.CheckViolation)):
        _execute(
            repository_case,
            "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at, author_state, author_marker)"
            " VALUES (?, ?, ?, '2026-10-21T00:00:00+00:00', NULL, 'aaaaaaaaaaaaaaaa')",
            "INSERT INTO mission_evidence (mission_id, observation_id, author_state, author_marker)"
            " VALUES (%s, %s, NULL, 'aaaaaaaaaaaaaaaa')",
            ((str(uuid4()), str(mission.id), observation) if repository_case.name.startswith("sqlite")
             else (str(mission.id), observation)),
        )


async def test_moving_a_support_binding_onto_unverifiable_content_is_refused(repository_case, tmp_path):
    repository = repository_case.repository
    store, mission, signals, frame, unverifiable = await _eligible_with_unverifiable_support(tmp_path, repository)
    result = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id), frame.frame_digest, [_observation_candidate(_signal_named(signals, "Demand evidence"))],
        created_by="host-agent",
    )
    assert result["permitted"] == 1, repository_case.name
    claim_id = result["claims"][0]["claim_id"]

    with pytest.raises((sqlite3.IntegrityError, psycopg.errors.CheckViolation)):
        _execute(
            repository_case,
            "UPDATE mission_claim_evidence SET observation_id = ? WHERE claim_id = ? AND role = 'SUPPORT'",
            "UPDATE mission_claim_evidence SET observation_id = %s WHERE claim_id = %s AND role = 'SUPPORT'",
            (str(unverifiable.observation_id), claim_id),
        )
