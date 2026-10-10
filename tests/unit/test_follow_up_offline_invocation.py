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


@pytest.mark.asyncio
async def test_durable_offline_consumer_exercises_original_scope_and_physical_expiry(tmp_path, monkeypatch):
    consumer = runpy.run_path(str(SCRIPT))
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
    summary = await consumer['verify'](packet, confirmation)
    assert summary['status'] == 'OFFLINE_PRODUCTION_COMPOSITION_VERIFIED'
    assert summary['description_state'] == 'RETAINED'
    assert summary['qualification'] == 'EXPLICIT_CURRENT_FRAME_CONTEXT_ONLY'
    assert summary['permitted_claims'] == 0
    assert summary['before_expiry_cleanup'] == 'REFUSED_WITH_ORIGINAL_INODE_PRESERVED'
    assert summary['owned_expiry'] == 'PHYSICAL_PURGE_VERIFIED' and summary['foreign_preserved']
    assert summary['native_installation'] == 'NOT_ESTABLISHED'
    assert summary['live_provider_execution'] == 'NOT_EXECUTED'
