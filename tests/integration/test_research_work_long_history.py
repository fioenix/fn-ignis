"""Long event histories cannot disable bounded reads or research cessation."""
from uuid import uuid4
from dataclasses import replace
from datetime import timedelta

import psycopg
import pytest

from tests.integration.test_mission_relay_read_boundary import (
    NOW, _reader, _request, relay_case as _relay_case, _observe_sqlite, _observe_postgres,
)
from tests.integration.test_research_work_persistence import _arrange, _commit

from ignis.application.use_cases.record_mission_research_work import RecordMissionResearchWorkUseCase

relay_case = _relay_case

async def _grow(case, mission, work, revision, activity_history):
    def write(conn, placeholder):
        statement = ('INSERT INTO mission_progress_events '
            '(id,mission_id,revision,ordinal,kind,provenance,causation_key,evidence_references,work_id,reason) '
            'VALUES (?,?,?,1,?,?,?,?,?,?)').replace('?', placeholder)
        rows = [(str(uuid4()), str(mission.id), revision + i, 'WORK_ACTIVITY_RECORDED',
            'HARNESS_OBSERVED', f'long-history:{i}', '[]', str(work.work_id) if i <= 2 else None,
            'CANCELLATION_PENDING' if i == 1 else 'INPUT_REVISION_MISMATCH' if i == 2 else None) for i in range(1, 10002)]
        conn.cursor().executemany(statement, rows)
        conn.execute('UPDATE mission_progress_revisions SET revision=? WHERE mission_id=?'.replace('?', placeholder),
            (revision + 10001, str(mission.id)))
        if activity_history:
            from datetime import datetime, timezone
            if placeholder == '?':
                now = datetime.now(timezone.utc).isoformat()
                conn.create_function('research_transaction_time', 0, lambda: now)
            conn.execute('UPDATE research_work_items SET version=? WHERE work_id=?'.replace('?', placeholder),
                (work.version + 10001, str(work.work_id)))
            conn.cursor().executemany(('INSERT INTO research_recorded_metadata '
                "(mission_id,record_kind,record_id,record_version,mission_revision) VALUES (?,'WORK',?,?,?)")
                .replace('?', placeholder), [(str(mission.id), str(work.work_id), work.version + i,
                revision + i) for i in range(1, 10002)])
        conn.commit()
    if case.name == 'postgres':
        with psycopg.connect(case.dsn) as conn:
            write(conn, '%s')
    else:
        def sqlite_write():
            conn = case.repository._get_connection()
            try:
                write(conn, '?')
            finally:
                if case.repository._mem_conn is None:
                    conn.close()
        await case.repository._run_write(sqlite_write)
    return revision + 10001


@pytest.mark.asyncio
@pytest.mark.parametrize('activity_history', (False, True))
@pytest.mark.parametrize('operation', ('read', 'end', 'history'))
async def test_long_history_preserves_reads_cessation_and_full_history(relay_case, tmp_path, operation, monkeypatch, activity_history):
    case, mission, domain, port, work, _, revision = await _arrange(relay_case, tmp_path)
    if activity_history:
        before = await case.repository.load_research_work(mission.id)
        activity = domain.ResearchActivityReceipt(work_id=work.work_id, epoch=1,
            ownership_fence=work.ownership_fence, execution_ref='long-history-activity',
            occurred_at=NOW + timedelta(seconds=1), fresh_until=NOW + timedelta(days=300),
            provenance='HOST_REPORTED')
        admitted = await _commit(case.repository, port, mission, 'RECORD_ACTIVITY',
            port.ResearchWorkStartAdmission(work_id=work.work_id, expected_version=work.version,
                ownership_fence=work.ownership_fence, receipt=activity), revision=revision)
        assert admitted.disposition == 'APPLIED'
        work = replace(work, version=admitted.work_version)
        revision = admitted.revision
        after = await case.repository.load_research_work(mission.id)
        assert len(after.events) == len(before.events) + 1
        assert len(after.recorded_metadata) == len(before.recorded_metadata) + 1
        assert any(m.record_id == work.work_id and m.record_version == work.version
            and m.mission_revision == revision for m in after.recorded_metadata)
    original = await case.repository.load_research_work(mission.id)
    latest = await _grow(case, mission, work, revision, activity_history)
    observer = _observe_postgres(monkeypatch) if case.name == 'postgres' else _observe_sqlite(monkeypatch, case.repository)
    with observer as observed:
        if operation == 'read':
            read = await _reader(case.repository).load_snapshot(_request(mission, None))
            from ignis.application.ports.mission_relay_port import MissionRelayRead
            assert isinstance(read, MissionRelayRead)
            assert len(read.events.events) <= read.request.page_size
            reasons = [event for event in read.research.events if event.work_id == work.work_id and event.reason]
            assert len(reasons) == 1 and reasons[0].reason == 'INPUT_REVISION_MISMATCH'
            assert reasons[0].cursor.revision == revision + 2
            assert len(read.research.events) == 1
            if activity_history:
                metadata = [m for m in read.research.recorded_metadata if m.record_id == work.work_id]
                assert len(metadata) == 1 and metadata[0].record_version == work.version + 10001
        elif operation == 'history':
            history = await case.repository.load_research_work(mission.id)
            assert history.events[:len(original.events)] == original.events
            assert len(history.events) == len(original.events) + 10001
            assert history.events[-1].cursor.revision == latest
            if activity_history:
                assert len(history.recorded_metadata) == len(original.recorded_metadata) + 10001
        else:
            assignment = original.assignments[0]
            result = await RecordMissionResearchWorkUseCase(case.repository).execute(str(mission.id), {
                'operation': 'END_RESEARCH', 'idempotency_key': 'end-long-history',
                'expected_revision': latest, 'expected_epoch': 1, 'payload': {
                    'assignment_id': str(assignment.assignment_id), 'expected_version': assignment.version,
                    'disposition': 'CANCELLED', 'reason': 'CANCELLATION_PENDING'}}, host_authorized=True)
            assert result['disposition'] == 'APPLIED'
            assert result['revision'] == latest + 1
        if operation != 'history':
            statements = observed[0] if case.name == 'postgres' else observed.statements
            full_history_reads = [statement for statement in statements
                if statement.lstrip().upper().startswith('SELECT * FROM MISSION_PROGRESS_EVENTS WHERE')
                and 'LIMIT' not in statement.upper()]
            assert full_history_reads == [], 'Projection/admission decoded the entire audit history'
            metadata_reads = [statement for statement in statements
                if statement.lstrip().upper().startswith('SELECT M.* FROM RESEARCH_RECORDED_METADATA')]
            assert metadata_reads and all('EXISTS' in statement.upper() for statement in metadata_reads)
