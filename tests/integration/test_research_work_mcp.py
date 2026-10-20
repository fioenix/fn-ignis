"""Synthetic native stdio recording to coherent HTTP and isolated Chromium.

Fixture composition initializes disposable storage before server startup. It never
stands in for a host specialist, collection execution or live-market research.
"""
from copy import deepcopy
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pytest

from tests.integration.test_mission_relay_read_boundary import relay_case as _relay_case, _state

from tests.integration.test_research_work_persistence import _arrange
from tests.integration.test_research_work_command_service import CLOCK_SKEW_MARGIN, command
from tests.integration.test_research_recording_mcp_boundary import RUNNER, public_handoff

relay_case = _relay_case

EVIDENCE = Path(__file__).resolve().parents[2] / '.handoff/spec014/us4/t056'


@asynccontextmanager
async def native_client(tmp_path, case):
    """Pass private storage settings by mode0600 file, never command-line DSN."""
    root = Path(__file__).resolve().parents[2]
    descriptor = tmp_path / 'storage.json'
    descriptor.write_text(json.dumps({'backend': case.name,
        'location': case.dsn if case.name == 'postgres' else case.repository._db_path}))
    descriptor.chmod(0o600)
    runner = tmp_path / 'native_stdio.py'
    source = RUNNER.replace('repository = SqliteTrendRepository(sys.argv[1])', '''storage = json.loads(Path(sys.argv[1]).read_text())
    if storage["backend"] == "postgres":
        from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
        repository = PostgresTimescaleRepository(storage["location"], min_pool_size=1, max_pool_size=2)
        await repository._get_pool()
    else:
        repository = SqliteTrendRepository(storage["location"])''')
    source = source.replace('await repository._ensure_schema()', '''if storage["backend"] != "postgres":
        await repository._ensure_schema()''')
    runner.write_text(source)
    env = tmp_path / 'isolated.env'
    env.write_text('DATABASE_URL=sqlite:///:memory:\nYOUTUBE_API_KEY=\nIGNIS_ENCRYPTION_KEY=\n')
    (tmp_path / '.fnignis').mkdir(exist_ok=True)
    client = Client(StdioTransport(command=sys.executable,
        args=[str(runner), str(descriptor), str(tmp_path / 'transport-proof.json'), str(tmp_path)],
        cwd=str(tmp_path), keep_alive=False,
        env={'IGNIS_ENV_FILE': str(env), 'IGNIS_ENV_ISOLATED': '1', 'PYTHONPATH': str(root / 'src')},
        log_file=tmp_path / 'stdio.log'), timeout=20, roots=[tmp_path.as_uri()], mode='legacy')
    try:
        async with client:
            yield client
    finally:
        descriptor.unlink(missing_ok=True)


async def record(client, mission, body):
    return (await client.call_tool('record_mission_research_work',
        {'mission_id': str(mission.id), 'command': body})).data


async def snapshot(client, mission, run_id=None):
    return (await client.call_tool('get_mission_relay_snapshot',
        {'mission_id': str(mission.id), 'run_id': str(run_id) if run_id else None, 'page_size': 100})).data


def assert_transport(tmp_path):
    assert json.loads((tmp_path / 'transport-proof.json').read_text()) == {
        'transport': 'stdio', 'lifespan_transport': 'stdio', 'request_session': True,
        'exact_server': True, 'owner_loop': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_native_record_read_back_and_original_receipt(relay_case, tmp_path):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    malicious = '<img src=x onerror="window.untrustedExecuted=true">'
    handoff = replace(handoff, result=malicious, findings=(replace(handoff.findings[0], statement=malicious),))
    body = public_handoff(handoff, revision)
    async with native_client(tmp_path, case) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert set(tools['record_mission_research_work'].input_schema['properties']) == {'mission_id', 'command'}
        first = await record(client, mission, body)
        assert first['disposition'] == 'APPLIED' and first['handoff_id'] == str(handoff.handoff_id)
        ack = command('ACK_HANDOFF', {'handoff_id': str(handoff.handoff_id),
            'consumer_ref': handoff.consumer_ref, 'expected_version': first['work_version'],
            'disposition': 'ACCEPTED', 'reason_code': None, 'inputs': work.inputs.to_payload()}, first['revision'])
        accepted = await record(client, mission, ack)
        assert accepted['disposition'] == 'APPLIED'
        initial = await snapshot(client, mission)
        assert initial['research']['availability'] == 'AVAILABLE'
        assert initial['counts'] == {'observations': 6, 'sources': 6}
        before = _state(case)
        assert await record(client, mission, deepcopy(body)) == first
        assert _state(case) == before
        actual = await snapshot(client, mission)
        assert actual['high_water'] == initial['high_water']
        assert actual['research'] == initial['research']
        assert _state(case) == before
        assert_transport(tmp_path)
        # No capability URL or private storage descriptor enters retained evidence.
        # .handoff/ is gitignored, so a fresh checkout such as CI does not have it yet.
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / f'native-{case.name}-receipt.json').write_text(json.dumps({
            'transport': json.loads((tmp_path / 'transport-proof.json').read_text()),
            'record': first, 'ack': accepted, 'mission_id': str(mission.id),
            'high_water': actual['high_water'], 'counts': actual['counts']}, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_native_finite_lifecycle_stop_after_end_and_nonretained_refusal(relay_case, tmp_path):
    case, mission, _, _, template, _, revision = await _arrange(relay_case, tmp_path)
    identity = str(uuid4())
    now = datetime.now(timezone.utc)
    async with native_client(tmp_path, case) as client:
        initial = await snapshot(client, mission)
        assigned_body = command('ASSIGN_WORK', {'assignment_id': str(template.assignment_id),
            'work_id': identity, 'question': 'Contact person@example.com', 'expertise': 'Synthesis',
            'assignee_ref': 'synthetic-worker', 'inputs': template.inputs.to_payload(),
            'dependencies': [], 'ownership_fence': 'new-fence'}, revision)
        assigned = await record(client, mission, assigned_body)
        assert assigned['disposition'] == 'APPLIED' and assigned['work_version'] == 1
        activity = {'work_id': identity, 'expected_version': 1, 'ownership_fence': 'new-fence',
            'execution_ref': 'synthetic-new-execution', 'occurred_at': (now - CLOCK_SKEW_MARGIN).isoformat(),
            'fresh_until': (now + timedelta(minutes=3)).isoformat()}
        last = await record(client, mission, command('START_WORK', activity, assigned['revision']))
        assert last['disposition'] == 'APPLIED' and last['work_version'] == 2
        for operation, version, state in [('WAIT_WORK', 2, 'WAITING'), ('RESUME_WORK', 3, 'RUNNING')]:
            last = await record(client, mission, command(operation,
                {'work_id': identity, 'expected_version': version, 'ownership_fence': 'new-fence',
                 'reason': 'DEPENDENCY_NOT_READY'}, last['revision']))
            assert last['disposition'] == 'APPLIED' and last['work_version'] == version + 1
            stored = await case.repository.load_research_work(mission.id)
            assert next(w for w in stored.work_items if str(w.work_id) == identity).state == state
        activity['expected_version'] = 4
        last = await record(client, mission, command('RECORD_ACTIVITY', activity, last['revision']))
        assert last['disposition'] == 'APPLIED' and last['work_version'] == 5
        fresh = await snapshot(client, mission)
        assert fresh['frame_digest'] == initial['frame_digest']
        assert fresh['counts'] == initial['counts'] == {'observations': 6, 'sources': 6}
        assert 'person@example.com' not in json.dumps(fresh)
        invalid = command('WAIT_WORK', {'work_id': identity, 'expected_version': 5,
            'ownership_fence': 'new-fence', 'reason': 'private-body-sentinel'}, last['revision'])
        before = _state(case)
        refusal = await record(client, mission, invalid)
        assert refusal['disposition'] == 'REFUSED' and refusal['reason_code'] == 'INVALID_REASON_CODE'
        assert refusal['receipt_id'] is None and refusal['revision'] is None
        assert 'private-body-sentinel' not in json.dumps(refusal)
        assert _state(case) == before
        pending = await record(client, mission, command('REQUEST_CANCEL', {'work_id': identity,
            'expected_version': 5, 'ownership_fence': 'new-fence', 'reason': 'INVALID_INPUT'}, last['revision']))
        assert pending['disposition'] == 'APPLIED' and pending['work_version'] == 6
        stored = await case.repository.load_research_work(mission.id)
        assert next(w for w in stored.work_items if str(w.work_id) == identity).state == 'CANCEL_PENDING'
        assignment = stored.assignments[0]
        ended = await record(client, mission, command('END_RESEARCH', {
            'assignment_id': str(assignment.assignment_id), 'expected_version': assignment.version,
            'disposition': 'CANCELLED', 'reason': 'INVALID_INPUT'}, pending['revision']))
        assert ended['disposition'] == 'APPLIED'
        stopped = await record(client, mission, command('ACK_STOP', {'work_id': identity,
            'expected_version': 6, 'ownership_fence': 'new-fence',
            'execution_ref': 'synthetic-new-execution', 'reason': 'INVALID_INPUT'}, ended['revision']))
        assert stopped['disposition'] == 'APPLIED' and stopped['work_version'] == 7
        stored = await case.repository.load_research_work(mission.id)
        assert next(w for w in stored.work_items if str(w.work_id) == identity).state == 'CANCELLED'
        assert stored.assignments[0].state == 'CANCELLED'
        before = _state(case)
        assert await record(client, mission, deepcopy(assigned_body)) == assigned
        assert _state(case) == before
        assert 'private-body-sentinel' not in repr(before)
        assert 'person@example.com' not in repr(before)
        assert_transport(tmp_path)
    assert 'private-body-sentinel' not in (tmp_path / 'stdio.log').read_text()


async def durable_refusal(client, case, mission, body, reason):
    """Exact no-fact/no-event control, allowing only safe immutable audit receipt."""
    before = _state(case)
    result = await record(client, mission, body)
    assert result['disposition'] == 'REFUSED' and result['reason_code'] == reason
    assert result['event_ids'] == [] and result['receipt_id'] is not None
    after = _state(case)
    assert after[0] == before[0]
    for table in before[1]:
        if table != 'research_work_commands':
            assert after[1][table] == before[1][table]
    assert len(after[1]['research_work_commands']) == len(before[1]['research_work_commands']) + 1
    assert 'REJECTED_PRIVATE_SENTINEL' not in repr(after)
    assert await record(client, mission, deepcopy(body)) == result
    assert _state(case) == after
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_native_expired_authority_completion_requires_result_and_original_refusal(relay_case, tmp_path):
    from tests.integration.test_research_work_lifecycle import bound, activity
    from tests.integration.test_research_work_persistence import _sql
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    async with native_client(tmp_path, case) as client:
        completion = command('END_WORK', {**bound(work), 'disposition': 'COMPLETED'}, revision)
        missing = await durable_refusal(client, case, mission, completion, 'RESULT_REQUIRED')
        submitted = await record(client, mission, public_handoff(handoff, revision))
        assert submitted['disposition'] == 'APPLIED'
        completed = await record(client, mission, command('END_WORK',
            {**bound(work, submitted['work_version']), 'disposition': 'COMPLETED'}, submitted['revision']))
        assert completed['disposition'] == 'APPLIED'
        before = _state(case)
        assert await record(client, mission, completion) == missing
        assert _state(case) == before
        stored = await case.repository.load_research_work(mission.id)
        assert stored.work_items[0].state == 'COMPLETED' and stored.acknowledgements == ()
    # A distinct mission has a genuinely expired persisted authority, not a projected clock.
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    await _sql(case, 'UPDATE research_assignments SET deadline=? WHERE assignment_id=?',
        ((datetime.now(timezone.utc) - CLOCK_SKEW_MARGIN).isoformat(), str(work.assignment_id)))
    async with native_client(tmp_path, case) as client:
        for operation, payload in [('START_WORK', activity(work)), ('RESUME_WORK', bound(work)),
            ('RECORD_ACTIVITY', activity(work)), ('SUBMIT_HANDOFF', public_handoff(handoff, revision)['payload'])]:
            if operation == 'SUBMIT_HANDOFF':
                payload['result'] = 'REJECTED_PRIVATE_SENTINEL'
            await durable_refusal(client, case, mission, command(operation, payload, revision), 'AUTHORITY_EXPIRED')
        stopped = await record(client, mission, command('END_WORK',
            {**bound(work), 'disposition': 'INTERRUPTED'}, revision))
        assert stopped['disposition'] == 'APPLIED'
        stored = await case.repository.load_research_work(mission.id)
        assert stored.work_items[0].state == 'INTERRUPTED'
        assert_transport(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_native_new_epoch_independent_research_after_collection_complete_and_old_stop(relay_case, tmp_path):
    from tests.integration.test_research_work_lifecycle import bound, activity
    from tests.integration.test_research_work_persistence import _sql
    from tests.unit.test_record_mission_research_work import assignment_command
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    async with native_client(tmp_path, case) as client:
        pending_body = command('REQUEST_CANCEL', bound(work), revision)
        pending = await record(client, mission, pending_body)
        assert pending['disposition'] == 'APPLIED'
        stored = await case.repository.load_research_work(mission.id)
        assignment = stored.assignments[0]
        end_body = command('END_RESEARCH', {'assignment_id': str(assignment.assignment_id),
            'expected_version': assignment.version, 'disposition': 'INTERRUPTED', 'reason': 'INVALID_INPUT'}, pending['revision'])
        ended = await record(client, mission, end_body)
        assert ended['disposition'] == 'APPLIED'
        await durable_refusal(client, case, mission, command('RECORD_ACTIVITY',
            activity(work, pending['work_version']), ended['revision']), 'ASSIGNMENT_TERMINAL')
        await _sql(case, 'UPDATE research_missions SET status=? WHERE id=?', ('COMPLETED', str(mission.id)))
        evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
        grant_body = assignment_command()
        grant_body['expected_epoch'] = 2
        grant_body['expected_revision'] = ended['revision']
        grant_body['payload']['expected_manifest_digest'] = evidence.manifest.manifest_digest
        grant_body['payload']['expected_brief_revision_id'] = str(evidence.brief.brief_revision_id)
        grant_body['payload']['authority']['deadline'] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        granted = await record(client, mission, grant_body)
        assert granted['disposition'] == 'APPLIED'
        await durable_refusal(client, case, mission, command('SUBMIT_HANDOFF',
            public_handoff(replace(handoff, result='REJECTED_PRIVATE_SENTINEL'), granted['revision'])['payload'],
            granted['revision']), 'STALE_EPOCH')
        stop = {**bound(work, pending['work_version']), 'execution_ref': 'synthetic-execution'}
        for field, value, reason in [('expected_version', 1, 'STALE_VERSION'),
            ('ownership_fence', 'foreign-fence', 'STALE_FENCE'),
            ('execution_ref', 'foreign-execution', 'EXECUTION_RECEIPT_NOT_CURRENT')]:
            await durable_refusal(client, case, mission, command('ACK_STOP', {**stop, field: value},
                granted['revision']), reason)
        stopped = await record(client, mission, command('ACK_STOP', stop, granted['revision']))
        assert stopped['disposition'] == 'APPLIED'
        identity = str(uuid4())
        assign = command('ASSIGN_WORK', {'assignment_id': granted['assignment_id'], 'work_id': identity,
            'question': 'Bounded post-collection research', 'expertise': 'Synthesis', 'assignee_ref': 'synthetic-worker',
            'inputs': work.inputs.to_payload(), 'dependencies': [], 'ownership_fence': 'epoch2-fence'}, stopped['revision'])
        assign['expected_epoch'] = 2
        assigned = await record(client, mission, assign)
        assert assigned['disposition'] == 'APPLIED'
        receipt = {**activity(work, 1), 'work_id': identity, 'ownership_fence': 'epoch2-fence',
            'execution_ref': 'epoch2-execution'}
        start = command('START_WORK', receipt, assigned['revision'])
        start['expected_epoch'] = 2
        started = await record(client, mission, start)
        assert started['disposition'] == 'APPLIED', started['reason_code']
        stored = await case.repository.load_research_work(mission.id)
        assert stored.current_epoch == 2 and stored.assignments[1].state == 'ACTIVE'
        assert stored.work_items[0].state == 'CANCELLED'
        current = await snapshot(client, mission)
        assert current['collection_state'] == 'COMPLETED'
        before = _state(case)
        for body, original in [(pending_body, pending), (end_body, ended), (grant_body, granted)]:
            assert await record(client, mission, deepcopy(body)) == original
            assert _state(case) == before
        assert_transport(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_native_collection_completion_keeps_assigned_analysis_until_research_end(relay_case, tmp_path):
    from tests.integration.test_research_work_lifecycle import bound, activity
    from tests.integration.test_research_work_persistence import _sql
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    assert (await case.repository.get_mission(mission.id)).status != 'COMPLETED'
    async with native_client(tmp_path, case) as client:
        # Collection completes while the separately authorized assignment and its work are still live.
        await _sql(case, 'UPDATE research_missions SET status=? WHERE id=?', ('COMPLETED', str(mission.id)))
        assert (await snapshot(client, mission))['collection_state'] == 'COMPLETED'
        observed = await record(client, mission, command('RECORD_ACTIVITY', activity(work), revision))
        assert observed['disposition'] == 'APPLIED', observed['reason_code']
        submitted = await record(client, mission, public_handoff(
            replace(handoff, expected_version=observed['work_version']), observed['revision']))
        assert submitted['disposition'] == 'APPLIED', submitted['reason_code']
        completed = await record(client, mission, command('END_WORK',
            {**bound(work, submitted['work_version']), 'disposition': 'COMPLETED'}, submitted['revision']))
        assert completed['disposition'] == 'APPLIED', completed['reason_code']
        queued_id = str(uuid4())
        queued = await record(client, mission, command('ASSIGN_WORK', {'assignment_id': str(work.assignment_id),
            'work_id': queued_id, 'question': 'In-scope analysis queued after collection', 'expertise': 'Synthesis',
            'assignee_ref': 'synthetic-worker', 'inputs': work.inputs.to_payload(), 'dependencies': [],
            'ownership_fence': 'queued-fence'}, completed['revision']))
        assert queued['disposition'] == 'APPLIED', queued['reason_code']
        stored = await case.repository.load_research_work(mission.id)
        assert stored.assignments[0].state == 'ACTIVE' and stored.current_epoch == 1
        assert next(w for w in stored.work_items if w.work_id == work.work_id).state == 'COMPLETED'
        assert stored.handoffs == (replace(handoff, expected_version=observed['work_version']),)
        # Research end, not collection completion, is what stops admission of any further work.
        ended = await record(client, mission, command('END_RESEARCH', {
            'assignment_id': str(work.assignment_id), 'expected_version': stored.assignments[0].version,
            'disposition': 'INTERRUPTED', 'reason': 'INVALID_INPUT'}, queued['revision']))
        assert ended['disposition'] == 'APPLIED', ended['reason_code']
        queued_work = next(w for w in stored.work_items if str(w.work_id) == queued_id)
        start = {**activity(queued_work), 'work_id': queued_id, 'ownership_fence': 'queued-fence'}
        await durable_refusal(client, case, mission, command('START_WORK', start, ended['revision']),
            'ASSIGNMENT_TERMINAL')
        await durable_refusal(client, case, mission, command('ASSIGN_WORK', {'assignment_id': str(work.assignment_id),
            'work_id': str(uuid4()), 'question': 'REJECTED_PRIVATE_SENTINEL', 'expertise': 'Synthesis',
            'assignee_ref': None, 'inputs': work.inputs.to_payload(), 'dependencies': [],
            'ownership_fence': 'late-fence'}, ended['revision']), 'ASSIGNMENT_TERMINAL')
        stored = await case.repository.load_research_work(mission.id)
        assert stored.assignments[0].state == 'INTERRUPTED'
        assert next(w for w in stored.work_items if str(w.work_id) == queued_id).state == 'ASSIGNED'
        assert len(stored.work_items) == 2
        assert (await case.repository.get_mission(mission.id)).status == 'COMPLETED'
        assert_transport(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_native_permitted_narration_withdrawal_and_history(relay_case, tmp_path):
    from tests.unit.test_mission_claims import _observation_candidate
    from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from tests.integration.test_research_work_persistence import _sql
    from tests.integration.test_research_work_lifecycle import activity
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    store = WorkspaceRepository(repository=case.repository)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    signal = next(s for s in evidence.signals if s.raw_title == 'Demand evidence')
    claims = await SubmitMissionClaimsUseCase(case.repository, store).execute(str(mission.id),
        work.inputs.frame_digest, [_observation_candidate(signal)], created_by='synthetic-t056')
    assert claims['permitted'] == 1
    claim = (await store.load_mission_evidence_snapshot(mission.id)).claims[0]
    inputs = replace(work.inputs, observation_ids=(signal.observation_id,))
    identity = str(uuid4())
    async with native_client(tmp_path, case) as client:
        state = await case.repository.load_research_work(mission.id)
        assigned = await record(client, mission, command('ASSIGN_WORK', {
            'assignment_id': str(work.assignment_id), 'work_id': identity,
            'question': 'Bounded strategic comparison', 'expertise': 'Synthesis', 'assignee_ref': 'synthetic-worker',
            'inputs': inputs.to_payload(), 'dependencies': [], 'ownership_fence': 'strategic-fence'}, state.revision))
        assert assigned['disposition'] == 'APPLIED'
        started = await record(client, mission, command('START_WORK', {**activity(work, 1),
            'work_id': identity, 'ownership_fence': 'strategic-fence',
            'execution_ref': 'strategic-execution'}, assigned['revision']))
        assert started['disposition'] == 'APPLIED', started['reason_code']
        from uuid import UUID
        finding = replace(handoff.findings[0], finding_id=uuid4(), handoff_id=uuid4(), work_id=UUID(identity),
            inputs=inputs, result_type='STRATEGIC_CANDIDATE', claim_id=claim.claim_id,
            statement='UNLICENSED_CANDIDATE_PROSE', supporting_observation_ids=(signal.observation_id,),
            contradicting_observation_ids=(), context_observation_ids=())
        strategic = replace(handoff, handoff_id=finding.handoff_id, work_id=UUID(identity),
            expected_version=started['work_version'], ownership_fence='strategic-fence', inputs=inputs,
            observation_sources=((signal.observation_id, signal.source_id),), claim_ids=(claim.claim_id,),
            result='UNLICENSED_AGGREGATE_PROSE', findings=(finding,))
        strategic_body = public_handoff(strategic, started['revision'])
        recorded = await record(client, mission, strategic_body)
        assert recorded['disposition'] == 'APPLIED'
        run = (await store.list_run_journals(mission.id))[0]
        initial = await snapshot(client, mission, run.run_id)
        assert initial['claim_gate']['state'] == 'CURRENT'
        assert claim.wording in json.dumps(initial['research'])
        assert 'UNLICENSED_CANDIDATE_PROSE' not in json.dumps(initial['research'])
        assert 'UNLICENSED_AGGREGATE_PROSE' not in json.dumps(initial['research'])
        # Actual owner fixture pruning changes canonical frame; the earlier read is never reused.
        await _sql(case, 'DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?',
            (str(mission.id), str(signal.observation_id)))
        changed = await snapshot(client, mission, run.run_id)
        assert claim.wording not in json.dumps(changed['research'])
        findings = changed['research']['findings']
        assert findings and not any(row['current_eligible'] for row in findings)
        assert any(row['text_withheld'] for row in findings)
        # Original result replay cannot restore its obsolete permission or membership.
        before = _state(case)
        assert await record(client, mission, deepcopy(strategic_body)) == recorded
        assert _state(case) == before
        fresh = await snapshot(client, mission)
        assert claim.wording not in json.dumps(fresh['research'])
        assert fresh['counts'] == {'observations': 5, 'sources': 5}
        assert_transport(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_native_scope_bindings_and_json_flags_cannot_widen_authority(relay_case, tmp_path):
    from tests.unit.test_record_mission_research_work import assignment_command
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    original = public_handoff(handoff, revision)
    evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
    widening = assignment_command()
    widening['expected_revision'] = revision
    widening['expected_epoch'] = 2
    widening['payload']['expected_manifest_digest'] = evidence.manifest.manifest_digest
    widening['payload']['expected_brief_revision_id'] = str(evidence.brief.brief_revision_id)
    widening['payload']['authority']['actions'] = ['COLLECT']
    controls = [(widening, 'AUTHORITY_WIDENING')]
    wrong_source = deepcopy(original)
    wrong_source['payload']['observation_sources'][0]['source_id'] = str(uuid4())
    controls.append((wrong_source, 'INPUT_IDENTITY_MISMATCH'))
    unknown_claim = deepcopy(original)
    unknown_claim['payload']['claim_ids'] = [str(uuid4())]
    controls.append((unknown_claim, 'INPUT_IDENTITY_MISMATCH'))
    stale = deepcopy(original)
    stale['payload']['inputs']['frame_digest'] = 'b' * 64
    for finding in stale['payload']['findings']:
        finding['inputs'] = deepcopy(stale['payload']['inputs'])
    controls.append((stale, 'STALE_INPUT_FRAME'))
    async with native_client(tmp_path, case) as client:
        for body, reason in controls:
            body['idempotency_key'] = uuid4().hex
            if body['operation'] == 'SUBMIT_HANDOFF':
                body['payload']['result'] = 'REJECTED_PRIVATE_SENTINEL'
            await durable_refusal(client, case, mission, body, reason)
        before = _state(case)
        for location in ('top', 'payload', 'finding', 'inputs', 'source'):
            body = deepcopy(original)
            target = {'top': body, 'payload': body['payload'], 'finding': body['payload']['findings'][0],
                'inputs': body['payload']['inputs'], 'source': body['payload']['observation_sources'][0]}[location]
            target['host_authorized'] = 'private-json-flag'
            result = await record(client, mission, body)
            assert result['disposition'] == 'REFUSED' and result['reason_code'] == 'INVALID_COMMAND'
            assert result['receipt_id'] is None and result['revision'] is None
            assert 'private-json-flag' not in json.dumps(result)
            assert _state(case) == before
        assert_transport(tmp_path)
    log = (tmp_path / 'stdio.log').read_text()
    assert 'private-json-flag' not in log and 'REJECTED_PRIVATE_SENTINEL' not in log
