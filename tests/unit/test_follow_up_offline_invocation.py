"""Durable offline command controls; synthetic bindings never represent owner consent."""
from hashlib import sha256
import json
from pathlib import Path
import runpy

import pytest
import ignis.config as config
from ignis.domain.follow_up_admission import digest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'verify_follow_up_root_offline.py'


def test_offline_consumer_refuses_nonisolated_config_before_provider_import(monkeypatch):
    consumer = runpy.run_path(str(SCRIPT))
    monkeypatch.setattr(config, '_ENV_ISOLATED', False)
    with pytest.raises(ValueError, match='ISOLATED_IN_MEMORY_SQLITE_REQUIRED'):
        consumer['require_isolated_config']()


@pytest.mark.parametrize('candidate_mode', ['none', 'invalid'])
@pytest.mark.asyncio
async def test_durable_offline_consumer_exercises_original_scope_and_persistent_retention(tmp_path, monkeypatch, candidate_mode):
    import tempfile
    consumer = runpy.run_path(str(SCRIPT))
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(config, '_ENV_ISOLATED', True)
    monkeypatch.setattr(config.settings, 'DATABASE_URL', 'sqlite:///:memory:')
    fixtures = Path(__file__).parents[1] / 'fixtures'
    brief = json.loads((fixtures / 'follow_up_tutorial_brief.json').read_text())
    instruction = json.loads((fixtures / 'follow_up_root_scope.json').read_text())
    packet = tmp_path / 'synthetic-packet.json'
    packet.write_text(json.dumps({'payload': brief, 'collection_instruction': instruction}))
    confirmation = tmp_path / 'synthetic-confirmation.json'
    confirmation.write_text(json.dumps({'packet_sha256': sha256(packet.read_bytes()).hexdigest(),
        'authority_kind': 'SYNTHETIC_OFFLINE_TEST_BINDING_ONLY', 'receipt': {
            'status': 'CONFIRMED', 'reference': 'SYNTHETIC_ONLY_COMMAND_CONTROL',
            'owner_reference': instruction['reference'], 'confirmed_by': 'synthetic-test-owner',
            'payload_digest': digest(brief), 'collection_scope_digest': digest(instruction)}}))
    from ignis.infrastructure import follow_up_root_composition as composition
    captured = {}
    original_bootstrap = composition.bootstrap_confirmed_parent
    async def capture(**kwargs):
        result = await original_bootstrap(**kwargs)
        captured.update(result)
        return result
    monkeypatch.setattr(composition, 'bootstrap_confirmed_parent', capture)
    original_finish = composition.finish_canonical_parent_analysis
    async def finish(result, **kwargs):
        if candidate_mode == 'invalid':
            kwargs['candidates'] = [{'text': 'Synthetic unbound candidate'}]
        answer = await original_finish(result, **kwargs)
        if candidate_mode == 'invalid':
            assert answer['claim_submission']['status'] == 'INVALID'
            assert answer['claim_submission']['reason_code'] == 'INVALID_CLAIM_BATCH'
        assert answer['claim_ledger']['counts']['permitted'] == 0
        return answer
    monkeypatch.setattr(composition, 'finish_canonical_parent_analysis', finish)
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.application.use_cases.submit_evidence_qualifications import SubmitEvidenceQualificationsUseCase
    from ignis.application.use_cases.get_mission_claims import GetMissionClaimsUseCase
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
    events = []
    original_serializer = ExecuteMissionUseCase._probe_outcome_payload
    def serialize(outcome):
        events.append('serialized')
        return original_serializer(outcome)
    monkeypatch.setattr(ExecuteMissionUseCase, '_probe_outcome_payload', staticmethod(serialize))
    for cls, label in ((SubmitEvidenceQualificationsUseCase, 'qualified'),
                       (GetMissionClaimsUseCase, 'ledger'), (GetMissionAnalysisUseCase, 'analysis')):
        original = cls.execute
        async def observe(self, *args, _original=original, _label=label, **kwargs):
            repository = getattr(self, '_repo', getattr(self, '_repository', None))
            assert captured['host']._revoked
            assert not repository.enrollment.closed
            events.append(_label)
            return await _original(self, *args, **kwargs)
        monkeypatch.setattr(cls, 'execute', observe)
    summary = await consumer['verify'](packet, confirmation)
    assert events == ['serialized', 'serialized', 'qualified', 'ledger', 'analysis']
    assert summary['analysis_status'] == 'INSUFFICIENT_EVIDENCE'
    assert summary['claim_render_status'] == 'WITHHELD'
    assert summary['source_revoked_before_analysis'] is True
    assert summary['status'] == 'OFFLINE_PRODUCTION_COMPOSITION_VERIFIED'
    assert summary['description_state'] == 'RETAINED'
    assert summary['qualification'] == 'EXPLICIT_CURRENT_FRAME_CONTEXT_ONLY'
    assert summary['permitted_claims'] == 0
    assert summary['retention'] == 'UNTIL_EXPLICIT_USER_DELETION'
    assert summary['accounting_close'] == 'CLOSED' and summary['shutdown'] == 'REVOKED_CLOSED'
    assert summary['expiry_purge'] == 'REFUSED_WITH_ORIGINAL_DATA_RETAINED' and summary['foreign_preserved']
    assert Path(summary['temporary_root']).parent.parent == tmp_path
    assert summary['native_installation'] == 'NOT_ESTABLISHED'
    assert summary['live_provider_execution'] == 'NOT_EXECUTED'


@pytest.mark.parametrize('failure', ['exception', 'cancellation'])
@pytest.mark.asyncio
async def test_analysis_failure_closes_original_owner_and_retains_data_without_another_source_call(tmp_path, monkeypatch, failure):
    import asyncio
    import tempfile
    from datetime import timedelta
    from ignis.infrastructure import follow_up_root_composition as composition
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    consumer = runpy.run_path(str(SCRIPT))
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(config, '_ENV_ISOLATED', True)
    monkeypatch.setattr(config.settings, 'DATABASE_URL', 'sqlite:///:memory:')
    fixtures = Path(__file__).parents[1] / 'fixtures'
    brief = json.loads((fixtures / 'follow_up_tutorial_brief.json').read_text())
    instruction = json.loads((fixtures / 'follow_up_root_scope.json').read_text())
    packet = tmp_path / 'synthetic-packet.json'
    packet.write_text(json.dumps({'payload': brief, 'collection_instruction': instruction}))
    confirmation = tmp_path / 'synthetic-confirmation.json'
    confirmation.write_text(json.dumps({'packet_sha256': sha256(packet.read_bytes()).hexdigest(),
        'authority_kind': 'SYNTHETIC_OFFLINE_TEST_BINDING_ONLY', 'receipt': {
            'status': 'CONFIRMED', 'reference': 'SYNTHETIC_ONLY_COMMAND_CONTROL',
            'owner_reference': instruction['reference'], 'confirmed_by': 'synthetic-test-owner',
            'payload_digest': digest(brief), 'collection_scope_digest': digest(instruction)}}))
    captured, provider_calls = {}, []
    original = composition.bootstrap_confirmed_parent
    async def capture(**kwargs):
        original_response = kwargs['transport'].handler
        async def record(request):
            provider_calls.append(request.url.path.rsplit('/', 1)[-1])
            return await original_response(request)
        import httpx
        kwargs['transport'] = httpx.MockTransport(record)
        result = await original(**kwargs)
        captured.update(result)
        return result
    monkeypatch.setattr(composition, 'bootstrap_confirmed_parent', capture)
    async def fail(self, *args, **kwargs):
        assert captured['host']._revoked and not captured['canonical'].closed
        assert provider_calls == ['search', 'videos']
        if failure == 'cancellation':
            raise asyncio.CancelledError()
        raise ValueError('SYNTHETIC_ANALYSIS_FAILURE')
    monkeypatch.setattr(GetMissionAnalysisUseCase, 'execute', fail)
    expected = asyncio.CancelledError if failure == 'cancellation' else composition.CanonicalAnalysisRetentionFailure
    with pytest.raises(expected) as caught:
        await consumer['verify'](packet, confirmation)
    recovery = caught.value.recovery
    canonical = captured['canonical']
    assert canonical.closed and canonical.generated_metadata.closed
    assert captured['host']._revoked and not captured['host']._tokens and not captured['host']._tasks
    assert recovery.confirmation is captured['host'].confirmation
    assert provider_calls == ['search', 'videos']
    bounds = recovery.confirmation.bounds
    assert bounds.retention_until is None
    metadata = canonical.generated_metadata
    paths = [captured['accounting'].path] + [metadata.root / key for key in metadata._load()['files']]
    assert canonical.path in paths and any(path.name == 'workspace.json' for path in paths) and len(paths) >= 4
    retained = [(path.stat().st_ino, path.read_bytes()) for path in paths]
    with pytest.raises(FollowUpExecutionBoundaryError):
        await recovery.purge(now=bounds.deadline + timedelta(days=8))
    assert [(path.stat().st_ino, path.read_bytes()) for path in paths] == retained
    with pytest.raises(FollowUpExecutionBoundaryError):
        await captured['repository'].get_mission(captured['mission_id'])
    foreign = canonical.root.parent / 'unregistered-foreign.txt'
    assert foreign.exists()
    assert canonical.path.exists() and not (canonical.root / 'deletion.json').exists()
    accounting = captured['accounting']
    assert accounting.counts(bounds) == {'search': 1, 'other': 1}
    with pytest.raises(FollowUpExecutionBoundaryError):
        accounting.current(bounds)
    assert provider_calls == ['search', 'videos']
