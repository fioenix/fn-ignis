"""Finite local YouTube pilot command; offline subprocess controls with synthetic transport only."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from ignis.domain.follow_up_admission import digest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / 'tests' / 'fixtures'
SECRET = 'synthetic-secret-value-never-printed'

RUNNER = r'''
import asyncio, json, sys
import httpx
from datetime import datetime, timezone
from ignis.interfaces.cli import caller_youtube_pilot as cli
calls = []
async def handler(request):
    calls.append(request.url.path.rsplit('/', 1)[-1])
    if request.url.path.endswith('/search'):
        return httpx.Response(200, json={'items': [{'id': {'videoId': 'cli-video'}}]})
    return httpx.Response(200, json={'items': [{'id': 'cli-video', 'snippet': {
        'title': 'Hướng dẫn n8n qua CLI', 'description': 'Synthetic CLI description.',
        'publishedAt': datetime.now(timezone.utc).isoformat()}, 'statistics': {'viewCount': '3'}}]})
code = cli.main(sys.argv[2:], transport=httpx.MockTransport(handler), resolve_credential=lambda: sys.argv[1])
print(json.dumps({'calls': calls}), file=sys.stderr)
raise SystemExit(code)
'''


def _env(tmp_path):
    isolated = tmp_path / 'isolated.env'
    if not isolated.exists():
        isolated.write_text('DATABASE_URL=sqlite:///:memory:\nYOUTUBE_API_KEY=\nIGNIS_ENCRYPTION_KEY=\n')
    return {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONPATH': os.pathsep.join((str(REPO / 'src'), str(REPO))),
            'IGNIS_ENV_ISOLATED': '1', 'IGNIS_ENV_FILE': str(isolated)}


def _packet(tmp_path):
    brief = json.loads((FIXTURES / 'follow_up_tutorial_brief.json').read_text())
    instruction = json.loads((FIXTURES / 'follow_up_root_scope.json').read_text())
    packet = tmp_path / 'packet.json'
    packet.write_text(json.dumps({'payload': brief, 'collection_instruction': instruction}, ensure_ascii=False))
    import hashlib
    confirmation = tmp_path / 'confirmation.json'
    confirmation.write_text(json.dumps({'packet_sha256': hashlib.sha256(packet.read_bytes()).hexdigest(), 'receipt': {
        'status': 'CONFIRMED', 'reference': 'SYNTHETIC_ONLY_CLI_BINDING', 'owner_reference': instruction['reference'],
        'payload_digest': digest(brief), 'collection_scope_digest': digest(instruction),
        'confirmed_by': 'synthetic-test-owner'}}))
    return packet, confirmation


def _caller_store(tmp_path, *, progress=True):
    """Disposable caller root with one confirmed, unexecuted parent in its own canonical store.

    progress=True adds the parent progress tables the writer requires; False models a store
    with a compatible core schema but no parent progress schema.
    """
    import asyncio
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from tests.unit.test_follow_up_caller_activation import _confirmed_caller_parent
    root = tmp_path / 'caller'
    (root / '.fnignis').mkdir(parents=True)
    async def build():
        repository = SqliteTrendRepository(str(root / '.fnignis' / 'canonical.sqlite3'))
        await repository._ensure_schema()
        mission = await _confirmed_caller_parent({'repository': repository,
            'workspace_store': WorkspaceRepository(repository=repository)}, root / '.fnignis' / 'research')
        if progress:
            await repository._ensure_progress_schema()
        await repository.close()
        return mission.id
    return root, asyncio.run(build())


def _run(args, tmp_path, *, injected=True, timeout=60):
    command = ([sys.executable, '-c', RUNNER, SECRET, *args] if injected
               else [sys.executable, '-m', 'ignis.interfaces.cli.caller_youtube_pilot', *args])
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=_env(tmp_path), cwd=str(REPO))


def test_help_is_packaged_and_takes_no_query_budget_or_secret_flags(tmp_path):
    result = _run(['--help'], tmp_path, injected=False)
    assert result.returncode == 0, result.stderr
    for forbidden in ('--query', '--budget', '--api-key', '--key', '--approve', '--max'):
        assert forbidden not in result.stdout


def test_missing_caller_store_refuses_without_side_effects(tmp_path):
    packet, confirmation = _packet(tmp_path)
    root = tmp_path / 'empty-caller'
    root.mkdir()
    result = _run(['--caller-root', str(root), '--mission-id', str(uuid4()),
                   '--packet', str(packet), '--confirmation', str(confirmation)], tmp_path, injected=False)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {'status': 'REFUSED', 'reason_code': 'CALLER_STORE_REQUIRED'}
    assert list(root.iterdir()) == []


def test_changed_packet_refuses_before_any_resolution_or_run_allocation(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    packet.write_text(packet.read_text().replace('n8n tự động hóa', 'n8n mở rộng'))
    result = _run(['--caller-root', str(root), '--mission-id', str(mission_id),
                   '--packet', str(packet), '--confirmation', str(confirmation)], tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)['reason_code'] == 'EXACT_CONFIRMED_PACKET_REQUIRED'
    assert json.loads(result.stderr.strip().splitlines()[-1])['calls'] == []
    assert not (root / '.fnignis' / 'follow-up').exists()


def test_parent_runs_once_on_caller_store_and_retry_never_starts_a_new_run(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    args = ['--caller-root', str(root), '--mission-id', str(mission_id),
            '--packet', str(packet), '--confirmation', str(confirmation)]
    first = _run(args, tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    summary = json.loads(first.stdout)
    assert summary['status'] == 'PARENT_EXECUTION_RETURNED' and summary['observations'] == 1
    assert summary['child_status'] == 'NOT_ADMITTED_NO_RECORDED_GENUINE_GAP'
    assert summary['accounting'] == {'search': 1, 'other': 1} and summary['accounting_close'] == 'CLOSED'
    assert summary['bounds'] == {'search_calls': 2, 'other_calls': 4, 'video_limit': 5, 'run_minutes': 15,
                                 'queries': ['n8n Việt Nam', 'n8n tự động hóa'], 'retention': 'UNTIL_EXPLICIT_USER_DELETION'}
    assert json.loads(first.stderr.strip().splitlines()[-1])['calls'] == ['search', 'videos']
    assert SECRET not in first.stdout and SECRET not in first.stderr
    databases = sorted(str(p.relative_to(root)) for p in root.rglob('*.sqlite3'))
    assert databases == ['.fnignis/canonical.sqlite3', f'.fnignis/follow-up/{mission_id}/accounting/private-run.sqlite3']
    with sqlite3.connect((root / '.fnignis' / 'canonical.sqlite3').as_uri() + '?mode=ro', uri=True) as connection:
        assert connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 1
        assert connection.execute('SELECT status FROM research_missions WHERE id=?', (str(mission_id),)).fetchone()[0] == 'COMPLETED'
    retry = _run(args, tmp_path)
    assert retry.returncode == 2
    assert json.loads(retry.stdout) == {'status': 'REFUSED', 'reason_code': 'ORIGINAL_RUN_ALREADY_ALLOCATED'}
    assert json.loads(retry.stderr.strip().splitlines()[-1])['calls'] == []
    with sqlite3.connect((root / '.fnignis' / 'canonical.sqlite3').as_uri() + '?mode=ro', uri=True) as connection:
        assert connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 1


BLOCKING_RUNNER = r'''
import asyncio, json, sys
from pathlib import Path
import httpx
from ignis.interfaces.cli import caller_youtube_pilot as cli
marker, mode = Path(sys.argv[2]), sys.argv[3]
async def handler(request):
    if mode == 'fail':
        raise httpx.ConnectError('synthetic failure with key=' + sys.argv[1])
    marker.write_text('entered')
    await asyncio.sleep(3600)
raise SystemExit(cli.main(sys.argv[4:], transport=httpx.MockTransport(handler), resolve_credential=lambda: sys.argv[1]))
'''


def _ledger(root, mission_id):
    path = root / '.fnignis' / 'follow-up' / str(mission_id) / 'accounting' / 'private-run.sqlite3'
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
        return connection.execute('SELECT searches,others,closed,purged FROM runs').fetchone()


def test_provider_failure_is_redacted_charged_closed_and_not_retryable(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    args = ['--caller-root', str(root), '--mission-id', str(mission_id), '--packet', str(packet), '--confirmation', str(confirmation)]
    result = subprocess.run([sys.executable, '-c', BLOCKING_RUNNER, SECRET, str(tmp_path / 'marker'), 'fail', *args],
        capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=str(REPO))
    assert SECRET not in result.stdout and SECRET not in result.stderr
    assert _ledger(root, mission_id) == (1, 0, 1, 0), 'A failed attempt stays charged and the run is durably closed'
    retry = _run(args, tmp_path)
    assert json.loads(retry.stdout) == {'status': 'REFUSED', 'reason_code': 'ORIGINAL_RUN_ALREADY_ALLOCATED'}


def test_interrupted_run_closes_original_ledger_and_retains_data(tmp_path):
    import signal
    import time
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    args = ['--caller-root', str(root), '--mission-id', str(mission_id), '--packet', str(packet), '--confirmation', str(confirmation)]
    marker = tmp_path / 'marker'
    process = subprocess.Popen([sys.executable, '-c', BLOCKING_RUNNER, SECRET, str(marker), 'block', *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env(tmp_path), cwd=str(REPO), start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), 'Synthetic provider was never reached'
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    assert SECRET not in stdout and SECRET not in stderr
    assert _ledger(root, mission_id) == (1, 0, 1, 0)
    assert (root / '.fnignis' / 'canonical.sqlite3').is_file()
    retry = _run(args, tmp_path)
    assert json.loads(retry.stdout) == {'status': 'REFUSED', 'reason_code': 'ORIGINAL_RUN_ALREADY_ALLOCATED'}


def _args(root, mission_id, packet, confirmation):
    return ['--caller-root', str(root), '--mission-id', str(mission_id), '--packet', str(packet), '--confirmation', str(confirmation)]


def _digest_file(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_incomplete_existing_schema_is_refused_without_mutating_bytes(tmp_path):
    root = tmp_path / 'caller'
    (root / '.fnignis').mkdir(parents=True)
    store = root / '.fnignis' / 'canonical.sqlite3'
    with sqlite3.connect(store) as connection:
        connection.execute('CREATE TABLE research_workspaces (id TEXT PRIMARY KEY)')
    before = _digest_file(store)
    packet, confirmation = _packet(tmp_path)
    result = _run(_args(root, uuid4(), packet, confirmation), tmp_path)
    assert json.loads(result.stdout) == {'status': 'REFUSED', 'reason_code': 'CALLER_SCHEMA_INCOMPLETE'}
    assert _digest_file(store) == before, 'Refusal initialized or migrated the existing caller store'
    assert sorted(p.name for p in (root / '.fnignis').iterdir()) == ['canonical.sqlite3']


def test_aliased_fnignis_directory_is_refused(tmp_path):
    real, mission_id = _caller_store(tmp_path)
    alias = tmp_path / 'alias-caller'
    alias.mkdir()
    (alias / '.fnignis').symlink_to(real / '.fnignis', target_is_directory=True)
    packet, confirmation = _packet(tmp_path)
    result = _run(_args(alias, mission_id, packet, confirmation), tmp_path)
    assert json.loads(result.stdout) == {'status': 'REFUSED', 'reason_code': 'CALLER_SCOPE_REFUSED'}
    assert json.loads(result.stderr.strip().splitlines()[-1])['calls'] == []
    assert not (real / '.fnignis' / 'follow-up').exists()


def test_any_brief_field_drift_refuses_before_allocation(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    store = root / '.fnignis' / 'canonical.sqlite3'
    with sqlite3.connect(store) as connection:
        connection.execute("UPDATE market_brief_revisions SET target_user='Drifted user' WHERE mission_id=?", (str(mission_id),))
    before = _digest_file(store)
    packet, confirmation = _packet(tmp_path)
    result = _run(_args(root, mission_id, packet, confirmation), tmp_path)
    assert json.loads(result.stdout) == {'status': 'REFUSED', 'reason_code': 'CONFIRMED_BRIEF_MISMATCH'}
    assert json.loads(result.stderr.strip().splitlines()[-1])['calls'] == []
    assert _digest_file(store) == before and not (root / '.fnignis' / 'follow-up').exists()


FAILING_CONSTRUCTION_RUNNER = r'''
import sys
import httpx
from ignis.infrastructure.follow_up_provider_bridge import HostBoundYouTubePlugin
def broken(self, **kwargs):
    raise RuntimeError('synthetic construction failure ' + sys.argv[1])
HostBoundYouTubePlugin.__init__ = broken
from ignis.interfaces.cli import caller_youtube_pilot as cli
raise SystemExit(cli.main(sys.argv[2:], transport=httpx.MockTransport(lambda request: None), resolve_credential=lambda: sys.argv[1]))
'''


def test_partial_construction_failure_closes_the_original_ledger(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    result = subprocess.run([sys.executable, '-c', FAILING_CONSTRUCTION_RUNNER, SECRET, *_args(root, mission_id, packet, confirmation)],
        capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=str(REPO))
    assert json.loads(result.stdout) == {'status': 'FAILED', 'error_type': 'RuntimeError'}
    assert SECRET not in result.stdout and SECRET not in result.stderr
    run_root = root / '.fnignis' / 'follow-up' / str(mission_id)
    assert _ledger(root, mission_id) == (0, 0, 1, 0), 'Partially constructed run left its original ledger open'
    assert json.loads((run_root / 'closure.json').read_text())['disposition'] == 'CLOSED'


DEFAULT_TRANSPORT_RUNNER = r'''
import json, sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
events = Path(sys.argv[2])
async def handler(request):
    if request.url.path.endswith('/search'):
        return httpx.Response(200, json={'items': [{'id': {'videoId': 'default-video'}}]})
    return httpx.Response(200, json={'items': [{'id': 'default-video', 'snippet': {'title': 'Hướng dẫn n8n mặc định',
        'description': 'Default transport', 'publishedAt': datetime.now(timezone.utc).isoformat()}, 'statistics': {'viewCount': '1'}}]})
class RecordedOfficialTransport(httpx.MockTransport):
    def __init__(self, *args, **kwargs):
        super().__init__(handler)
        with events.open('a') as stream: stream.write('created\n')
    async def aclose(self):
        with events.open('a') as stream: stream.write('closed\n')
httpx.AsyncHTTPTransport = RecordedOfficialTransport
from ignis.interfaces.cli import caller_youtube_pilot as cli
raise SystemExit(cli.main(sys.argv[3:], resolve_credential=lambda: sys.argv[1]))
'''


def test_default_run_owns_and_closes_the_official_http_transport_after_preflight(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    events = tmp_path / 'transport-events'
    refused = subprocess.run([sys.executable, '-c', DEFAULT_TRANSPORT_RUNNER, SECRET, str(events),
        *_args(root, uuid4(), packet, confirmation)], capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=str(REPO))
    assert json.loads(refused.stdout)['status'] == 'REFUSED' and not events.exists()
    result = subprocess.run([sys.executable, '-c', DEFAULT_TRANSPORT_RUNNER, SECRET, str(events),
        *_args(root, mission_id, packet, confirmation)], capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=str(REPO))
    assert json.loads(result.stdout)['status'] == 'PARENT_EXECUTION_RETURNED', result.stdout + result.stderr
    assert events.read_text().splitlines() == ['created', 'closed']
    assert SECRET not in result.stdout and SECRET not in result.stderr


def test_concurrent_invocations_allocate_exactly_one_original_run(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    command = [sys.executable, '-c', RUNNER, SECRET, *_args(root, mission_id, packet, confirmation)]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  env=_env(tmp_path), cwd=str(REPO)) for _ in range(2)]
    outputs = [process.communicate(timeout=60) for process in processes]
    statuses = sorted(json.loads(stdout)['status'] for stdout, _ in outputs)
    assert statuses == ['PARENT_EXECUTION_RETURNED', 'REFUSED'], outputs
    assert len(list((root / '.fnignis' / 'follow-up').iterdir())) == 1
    assert _ledger(root, mission_id)[:2] == (1, 1)


LOCKING_RUNNER = r'''
import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
from ignis.interfaces.cli import caller_youtube_pilot as cli
ledger = Path(sys.argv[2])
locks = []
async def handler(request):
    if request.url.path.endswith('/search'):
        return httpx.Response(200, json={'items': [{'id': {'videoId': 'locked-video'}}]})
    # After the last charged attempt, hold the original ledger so cleanup closure cannot commit.
    lock = sqlite3.connect(ledger, timeout=0)
    lock.execute('BEGIN IMMEDIATE')
    locks.append(lock)
    return httpx.Response(200, json={'items': [{'id': 'locked-video', 'snippet': {'title': 'Hướng dẫn n8n khóa',
        'description': 'Locked ledger', 'publishedAt': datetime.now(timezone.utc).isoformat()}, 'statistics': {'viewCount': '1'}}]})
raise SystemExit(cli.main(sys.argv[3:], transport=httpx.MockTransport(handler), resolve_credential=lambda: sys.argv[1]))
'''


def _ledger_path(root, mission_id):
    return root / '.fnignis' / 'follow-up' / str(mission_id) / 'accounting' / 'private-run.sqlite3'


def test_locked_cleanup_reports_pending_then_close_only_recovery_closes_original(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    result = subprocess.run([sys.executable, '-c', LOCKING_RUNNER, SECRET, str(_ledger_path(root, mission_id)),
        *_args(root, mission_id, packet, confirmation)], capture_output=True, text=True, timeout=90, env=_env(tmp_path), cwd=str(REPO))
    run_root = root / '.fnignis' / 'follow-up' / str(mission_id)
    closure = json.loads((run_root / 'closure.json').read_text())
    assert closure['accounting_close'] == 'PENDING', result.stdout + result.stderr
    assert SECRET not in result.stdout and SECRET not in result.stderr
    assert _ledger(root, mission_id) == (1, 1, 0, 0)
    canonical = _digest_file(root / '.fnignis' / 'canonical.sqlite3')
    ledger_identity = _ledger_path(root, mission_id).stat().st_ino
    recovery_args = ['--caller-root', str(root), '--mission-id', str(mission_id), '--close-only']
    for _ in range(2):
        recovered = _run(recovery_args, tmp_path, injected=False)
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr
        assert json.loads(recovered.stdout) == {'status': 'CLOSED', 'run_id': json.loads((run_root / 'run.json').read_text())['run_id'],
            'phases': {'host': 'CLOSED', 'transport': 'NOT_ALLOCATED', 'repository': 'CLOSED', 'accounting': 'CLOSED'},
            'accounting': {'search': 1, 'other': 1}}
    assert _ledger(root, mission_id) == (1, 1, 1, 0)
    assert _ledger_path(root, mission_id).stat().st_ino == ledger_identity
    assert _digest_file(root / '.fnignis' / 'canonical.sqlite3') == canonical
    assert json.loads((run_root / 'closure.json').read_text())['accounting_close'] == 'CLOSED'
    assert len(list((root / '.fnignis' / 'follow-up').iterdir())) == 1


def test_close_only_refuses_a_replaced_ledger_copy(tmp_path):
    import shutil
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    subprocess.run([sys.executable, '-c', LOCKING_RUNNER, SECRET, str(_ledger_path(root, mission_id)),
        *_args(root, mission_id, packet, confirmation)], capture_output=True, text=True, timeout=90, env=_env(tmp_path), cwd=str(REPO))
    ledger = _ledger_path(root, mission_id)
    copy = tmp_path / 'ledger-copy.sqlite3'
    shutil.copy2(ledger, copy)
    copy.replace(ledger)
    recovered = _run(['--caller-root', str(root), '--mission-id', str(mission_id), '--close-only'], tmp_path, injected=False)
    assert recovered.returncode == 2
    assert json.loads(recovered.stdout) == {'status': 'REFUSED', 'reason_code': 'ORIGINAL_LEDGER_IDENTITY_MISMATCH'}
    assert _ledger(root, mission_id) == (1, 1, 0, 0)


EXPIRY_RUNNER = r'''
import asyncio, json, sys
from datetime import datetime, timedelta, timezone
import httpx
from ignis.infrastructure import follow_up_root_composition as composition
original = composition.confirmation_at_approved_invocation
def near_deadline(record, **kwargs):
    kwargs['started_at'] = datetime.now(timezone.utc) - timedelta(minutes=15) + timedelta(seconds=1)
    return original(record, **kwargs)
composition.confirmation_at_approved_invocation = near_deadline
from ignis.interfaces.cli import caller_youtube_pilot as cli
resolutions = []
async def handler(request):
    if request.url.path.endswith('/search'):
        await asyncio.sleep(1.5)
        return httpx.Response(200, json={'items': [{'id': {'videoId': 'expiring-video'}}]})
    return httpx.Response(200, json={'items': []})
def resolve():
    resolutions.append(1)
    return sys.argv[1]
code = cli.main(sys.argv[2:], transport=httpx.MockTransport(handler), resolve_credential=resolve)
print(json.dumps({'resolutions': len(resolutions)}), file=sys.stderr)
raise SystemExit(code)
'''


def test_midrun_deadline_expiry_refuses_further_attempts_and_retry(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    args = _args(root, mission_id, packet, confirmation)
    result = subprocess.run([sys.executable, '-c', EXPIRY_RUNNER, SECRET, *args], capture_output=True, text=True,
        timeout=90, env=_env(tmp_path), cwd=str(REPO))
    assert json.loads(result.stderr.strip().splitlines()[-1])['resolutions'] == 1, result.stdout + result.stderr
    assert _ledger(root, mission_id) == (1, 0, 1, 0)
    assert SECRET not in result.stdout and SECRET not in result.stderr
    retry = _run(args, tmp_path)
    assert json.loads(retry.stdout) == {'status': 'REFUSED', 'reason_code': 'ORIGINAL_RUN_ALREADY_ALLOCATED'}


CLEANUP_CANCEL_RUNNER = r'''
import asyncio, sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
from ignis.infrastructure.follow_up_host_activation import RootHostController
marker = Path(sys.argv[2])
original_revoke = RootHostController.revoke
async def slow_revoke(self, **kwargs):
    marker.write_text('cleanup')
    await asyncio.sleep(1.5)
    return await original_revoke(self, **kwargs)
RootHostController.revoke = slow_revoke
from ignis.interfaces.cli import caller_youtube_pilot as cli
async def handler(request):
    if request.url.path.endswith('/search'):
        return httpx.Response(200, json={'items': [{'id': {'videoId': 'cleanup-video'}}]})
    return httpx.Response(200, json={'items': [{'id': 'cleanup-video', 'snippet': {'title': 'Hướng dẫn n8n dọn dẹp',
        'description': 'Cleanup', 'publishedAt': datetime.now(timezone.utc).isoformat()}, 'statistics': {'viewCount': '1'}}]})
raise SystemExit(cli.main(sys.argv[3:], transport=httpx.MockTransport(handler), resolve_credential=lambda: sys.argv[1]))
'''


def test_interrupt_during_cleanup_still_settles_original_closure(tmp_path):
    import signal
    import time
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    marker = tmp_path / 'cleanup-marker'
    process = subprocess.Popen([sys.executable, '-c', CLEANUP_CANCEL_RUNNER, SECRET, str(marker),
        *_args(root, mission_id, packet, confirmation)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=_env(tmp_path), cwd=str(REPO), start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    run_root = root / '.fnignis' / 'follow-up' / str(mission_id)
    assert SECRET not in stdout and SECRET not in stderr
    assert (run_root / 'closure.json').exists(), 'Interrupted cleanup left no closure receipt'
    assert json.loads((run_root / 'closure.json').read_text())['accounting_close'] == 'CLOSED'
    assert _ledger(root, mission_id) == (1, 1, 1, 0)


def test_manifest_retention_drift_refuses_before_allocation(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    store = root / '.fnignis' / 'canonical.sqlite3'
    with sqlite3.connect(store) as connection:
        connection.execute("UPDATE mission_manifests SET retention_policy='exclusive-owned-seven-day-host-disposition' WHERE mission_id=?",
                           (str(mission_id),))
    before = _digest_file(store)
    packet, confirmation = _packet(tmp_path)
    result = _run(_args(root, mission_id, packet, confirmation), tmp_path)
    assert json.loads(result.stdout) == {'status': 'REFUSED', 'reason_code': 'CONFIRMED_SCOPE_MISMATCH'}
    assert _digest_file(store) == before and not (root / '.fnignis' / 'follow-up').exists()


def test_aliased_research_directory_refuses_before_allocation(tmp_path):
    import shutil
    root, mission_id = _caller_store(tmp_path)
    research = root / '.fnignis' / 'research'
    foreign = tmp_path / 'foreign-research'
    shutil.move(str(research), foreign)
    research.symlink_to(foreign, target_is_directory=True)
    foreign_state = sorted((str(p.relative_to(foreign)), p.stat().st_ino) for p in foreign.rglob('*'))
    packet, confirmation = _packet(tmp_path)
    result = _run(_args(root, mission_id, packet, confirmation), tmp_path)
    assert json.loads(result.stdout)['status'] == 'REFUSED', result.stdout
    assert json.loads(result.stderr.strip().splitlines()[-1])['calls'] == []
    assert not (root / '.fnignis' / 'follow-up').exists()
    assert sorted((str(p.relative_to(foreign)), p.stat().st_ino) for p in foreign.rglob('*')) == foreign_state


REPLACEMENT_RUNNER = r'''
import json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
from ignis.infrastructure.follow_up_caller_activation import CallerSourceActivation
store = Path(sys.argv[2])
original = CallerSourceActivation.run_parent
async def replaced_then_run(self, mission_id):
    copy = store.with_name('replacement.sqlite3')
    shutil.copy2(store, copy)
    copy.replace(store)
    return await original(self, mission_id)
CallerSourceActivation.run_parent = replaced_then_run
from ignis.interfaces.cli import caller_youtube_pilot as cli
calls = []
async def handler(request):
    calls.append(request.url.path)
    return httpx.Response(200, json={'items': []})
code = cli.main(sys.argv[3:], transport=httpx.MockTransport(handler), resolve_credential=lambda: sys.argv[1])
print(json.dumps({'calls': calls}), file=sys.stderr)
raise SystemExit(code)
'''


def test_canonical_store_replaced_after_admission_refuses_before_any_source_call(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    store = root / '.fnignis' / 'canonical.sqlite3'
    result = subprocess.run([sys.executable, '-c', REPLACEMENT_RUNNER, SECRET, str(store), *_args(root, mission_id, packet, confirmation)],
        capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=str(REPO))
    assert json.loads(result.stderr.strip().splitlines()[-1])['calls'] == [], result.stdout + result.stderr
    assert json.loads(result.stdout)['status'] in ('REFUSED', 'FAILED')
    assert result.returncode != 0
    with sqlite3.connect(store.as_uri() + '?mode=ro', uri=True) as connection:
        assert connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0


@pytest.mark.parametrize('leaf', ['closure.json', 'run.json'])
def test_close_only_refuses_symlinked_recovery_files_without_touching_foreign_bytes(tmp_path, leaf):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    subprocess.run([sys.executable, '-c', LOCKING_RUNNER, SECRET, str(_ledger_path(root, mission_id)),
        *_args(root, mission_id, packet, confirmation)], capture_output=True, text=True, timeout=90, env=_env(tmp_path), cwd=str(REPO))
    run_root = root / '.fnignis' / 'follow-up' / str(mission_id)
    foreign = tmp_path / 'foreign.json'
    foreign.write_bytes((run_root / leaf).read_bytes())
    original = foreign.read_bytes()
    (run_root / leaf).unlink()
    (run_root / leaf).symlink_to(foreign)
    result = _run(['--caller-root', str(root), '--mission-id', str(mission_id), '--close-only'], tmp_path, injected=False)
    assert json.loads(result.stdout)['status'] == 'REFUSED', result.stdout
    assert foreign.read_bytes() == original
    assert _ledger(root, mission_id) == (1, 1, 0, 0)


def test_cancellation_first_seen_during_cleanup_exits_nonzero_after_settlement(tmp_path):
    import signal
    import time
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    marker = tmp_path / 'cleanup-marker'
    process = subprocess.Popen([sys.executable, '-c', CLEANUP_CANCEL_RUNNER, SECRET, str(marker),
        *_args(root, mission_id, packet, confirmation)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=_env(tmp_path), cwd=str(REPO), start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    assert process.returncode != 0, 'Cancellation received during cleanup was reported as success'
    receipt = json.loads((root / '.fnignis' / 'follow-up' / str(mission_id) / 'closure.json').read_text())
    assert receipt['accounting_close'] == 'CLOSED' and _ledger(root, mission_id) == (1, 1, 1, 0)


REVOKE_FAILURE_RUNNER = r'''
import sys
import httpx
from ignis.infrastructure.follow_up_host_activation import RootHostController
from ignis.infrastructure.follow_up_provider_bridge import HostBoundYouTubePlugin
def broken(self, **kwargs):
    raise RuntimeError('construction failure ' + sys.argv[1])
async def failing_revoke(self, **kwargs):
    raise RuntimeError('revoke failure ' + sys.argv[1])
HostBoundYouTubePlugin.__init__ = broken
RootHostController.revoke = failing_revoke
from ignis.interfaces.cli import caller_youtube_pilot as cli
raise SystemExit(cli.main(sys.argv[2:], transport=httpx.MockTransport(lambda request: None), resolve_credential=lambda: sys.argv[1]))
'''


def test_revoke_failure_still_runs_later_cleanup_phases_and_keeps_original_error(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    result = subprocess.run([sys.executable, '-c', REVOKE_FAILURE_RUNNER, SECRET, *_args(root, mission_id, packet, confirmation)],
        capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=str(REPO))
    assert json.loads(result.stdout) == {'status': 'FAILED', 'error_type': 'RuntimeError'}
    assert SECRET not in result.stdout and SECRET not in result.stderr
    assert _ledger(root, mission_id) == (0, 0, 1, 0), 'Accounting closure was skipped after a revoke failure'
    receipt = json.loads((root / '.fnignis' / 'follow-up' / str(mission_id) / 'closure.json').read_text())
    assert receipt['disposition'] == 'PENDING' and receipt['phases']['host'] == 'PENDING'
    assert receipt['phases']['accounting'] == 'CLOSED' and receipt['phases']['repository'] in ('CLOSED', 'NOT_ALLOCATED')


TRANSPORT_CLOSE_FAILURE_RUNNER = r'''
import sys
from datetime import datetime, timezone
import httpx
async def handler(request):
    if request.url.path.endswith('/search'):
        return httpx.Response(200, json={'items': [{'id': {'videoId': 'close-video'}}]})
    return httpx.Response(200, json={'items': [{'id': 'close-video', 'snippet': {'title': 'Hướng dẫn n8n đóng',
        'description': 'Close failure', 'publishedAt': datetime.now(timezone.utc).isoformat()}, 'statistics': {'viewCount': '1'}}]})
class FailingClose(httpx.MockTransport):
    def __init__(self, *args, **kwargs):
        super().__init__(handler)
    async def aclose(self):
        raise RuntimeError('transport close failure ' + sys.argv[1])
httpx.AsyncHTTPTransport = FailingClose
from ignis.interfaces.cli import caller_youtube_pilot as cli
raise SystemExit(cli.main(sys.argv[2:], resolve_credential=lambda: sys.argv[1]))
'''


def test_transport_close_failure_is_pending_but_repository_and_receipt_settle(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    result = subprocess.run([sys.executable, '-c', TRANSPORT_CLOSE_FAILURE_RUNNER, SECRET, *_args(root, mission_id, packet, confirmation)],
        capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=str(REPO))
    assert SECRET not in result.stdout and SECRET not in result.stderr
    assert result.returncode != 0, 'Incomplete cleanup was reported as full success'
    receipt = json.loads((root / '.fnignis' / 'follow-up' / str(mission_id) / 'closure.json').read_text())
    assert receipt['phases'] == {**receipt['phases'], 'transport': 'PENDING', 'accounting': 'CLOSED', 'repository': 'CLOSED', 'host': 'CLOSED'}
    assert receipt['disposition'] == 'PENDING'


PROGRESS_TABLES = ('mission_progress_commands', 'mission_progress_events', 'mission_progress_revisions')


def _tables(store):
    with sqlite3.connect(store.as_uri() + '?mode=ro', uri=True) as connection:
        return sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))


def test_core_compatible_store_without_parent_progress_schema_refuses_before_writer(tmp_path):
    root, mission_id = _caller_store(tmp_path, progress=False)
    store = root / '.fnignis' / 'canonical.sqlite3'
    assert not set(PROGRESS_TABLES) & set(_tables(store))
    before, tables = _digest_file(store), _tables(store)
    packet, confirmation = _packet(tmp_path)
    result = _run(_args(root, mission_id, packet, confirmation), tmp_path)
    assert json.loads(result.stdout) == {'status': 'REFUSED', 'reason_code': 'CALLER_PARENT_PROGRESS_SCHEMA_REQUIRED'}, result.stdout
    assert json.loads(result.stderr.strip().splitlines()[-1])['calls'] == []
    assert _digest_file(store) == before and _tables(store) == tables, 'Refusal created parent progress schema'
    assert not (root / '.fnignis' / 'follow-up').exists()


def test_parent_only_run_does_not_require_optional_child_workflow_tables(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    store = root / '.fnignis' / 'canonical.sqlite3'
    assert set(PROGRESS_TABLES) <= set(_tables(store))
    assert not any(name.startswith('mission_follow_up') for name in _tables(store))
    packet, confirmation = _packet(tmp_path)
    result = _run(_args(root, mission_id, packet, confirmation), tmp_path)
    assert json.loads(result.stdout)['status'] == 'PARENT_EXECUTION_RETURNED', result.stdout + result.stderr


WORKSPACE_ALIAS_RUNNER = r'''
import json, shutil, sys
from pathlib import Path
import httpx
from ignis.infrastructure.follow_up_caller_activation import CallerSourceActivation
workspace, foreign = Path(sys.argv[2]), Path(sys.argv[3])
original = CallerSourceActivation.run_parent
async def aliased_then_run(self, mission_id):
    shutil.move(str(workspace), foreign)
    workspace.symlink_to(foreign, target_is_directory=True)
    return await original(self, mission_id)
CallerSourceActivation.run_parent = aliased_then_run
from ignis.interfaces.cli import caller_youtube_pilot as cli
calls = []
async def handler(request):
    calls.append(request.url.path)
    return httpx.Response(200, json={'items': []})
code = cli.main(sys.argv[4:], transport=httpx.MockTransport(handler), resolve_credential=lambda: sys.argv[1])
print(json.dumps({'calls': calls}), file=sys.stderr)
raise SystemExit(code)
'''


def _workspace_root(root, mission_id):
    with sqlite3.connect((root / '.fnignis' / 'canonical.sqlite3').as_uri() + '?mode=ro', uri=True) as connection:
        return Path(connection.execute('SELECT w.root_path FROM research_workspaces w JOIN research_missions m '
            'ON m.workspace_id = w.id WHERE m.id=?', (str(mission_id),)).fetchone()[0])


def test_workspace_replaced_by_alias_after_admission_refuses_before_source_and_journal(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    workspace = _workspace_root(root, mission_id)
    foreign = tmp_path / 'foreign-workspace'
    packet, confirmation = _packet(tmp_path)
    result = subprocess.run([sys.executable, '-c', WORKSPACE_ALIAS_RUNNER, SECRET, str(workspace), str(foreign),
        *_args(root, mission_id, packet, confirmation)], capture_output=True, text=True, timeout=60, env=_env(tmp_path), cwd=str(REPO))
    assert json.loads(result.stderr.strip().splitlines()[-1])['calls'] == [], result.stdout + result.stderr
    assert result.returncode != 0
    assert sorted(p.name for p in foreign.rglob('*') if p.is_file()) == ['workspace.json'], 'A journal was written through the alias'
    assert SECRET not in result.stdout and SECRET not in result.stderr


def _locked_run(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    packet, confirmation = _packet(tmp_path)
    subprocess.run([sys.executable, '-c', LOCKING_RUNNER, SECRET, str(_ledger_path(root, mission_id)),
        *_args(root, mission_id, packet, confirmation)], capture_output=True, text=True, timeout=90, env=_env(tmp_path), cwd=str(REPO))
    return root, mission_id, root / '.fnignis' / 'follow-up' / str(mission_id) / 'closure.json'


def test_close_only_keeps_pending_when_another_phase_is_pending(tmp_path):
    root, mission_id, closure = _locked_run(tmp_path)
    receipt = json.loads(closure.read_text())
    receipt['phases']['host'] = 'PENDING'
    closure.write_text(json.dumps(receipt))
    result = _run(['--caller-root', str(root), '--mission-id', str(mission_id), '--close-only'], tmp_path, injected=False)
    assert result.returncode != 0, result.stdout
    assert json.loads(result.stdout)['status'] == 'PENDING'
    assert _ledger(root, mission_id) == (1, 1, 1, 0)
    final = json.loads(closure.read_text())
    assert final['disposition'] == 'PENDING' and final['phases']['accounting'] == 'CLOSED' and final['phases']['host'] == 'PENDING'


def test_close_only_without_phase_record_never_infers_global_closure(tmp_path):
    root, mission_id, closure = _locked_run(tmp_path)
    receipt = json.loads(closure.read_text())
    receipt.pop('phases')
    closure.write_text(json.dumps(receipt))
    result = _run(['--caller-root', str(root), '--mission-id', str(mission_id), '--close-only'], tmp_path, injected=False)
    assert result.returncode != 0, result.stdout
    assert json.loads(result.stdout)['status'] == 'PENDING'
    final = json.loads(closure.read_text())
    assert final['disposition'] == 'PENDING' and final['phases']['host'] == 'UNKNOWN'
    assert _ledger(root, mission_id) == (1, 1, 1, 0)


TRACED_RUNNER = r'''
import json, sys
from pathlib import Path
import httpx
from datetime import datetime, timezone
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
entered = []
for name in ('_create_tables_and_seed', '_create_progress_tables', '_ensure_research_schema'):
    original = getattr(SqliteTrendRepository, name)
    def traced(self, *args, _original=original, _name=name):
        entered.append([_name, str(Path(self._db_path).absolute())])
        return _original(self, *args)
    setattr(SqliteTrendRepository, name, traced)
from ignis.interfaces.cli import caller_youtube_pilot as cli
calls = []
async def handler(request):
    calls.append(request.url.path.rsplit('/', 1)[-1])
    if request.url.path.endswith('/search'):
        return httpx.Response(200, json={'items': [{'id': {'videoId': 'ready-video'}}]})
    return httpx.Response(200, json={'items': [{'id': 'ready-video', 'snippet': {
        'title': 'Hướng dẫn n8n ready', 'description': 'Synthetic ready description.',
        'publishedAt': datetime.now(timezone.utc).isoformat()}, 'statistics': {'viewCount': '2'}}]})
code = cli.main(sys.argv[2:], transport=httpx.MockTransport(handler), resolve_credential=lambda: sys.argv[1])
print(json.dumps({'calls': calls, 'entered': entered}), file=sys.stderr)
raise SystemExit(code)
'''

_PRESERVED = ('market_lexicons', 'industry_taxonomies', 'runtime_configs', 'platform_credentials', 'research_workspaces')


def _traced(args, tmp_path):
    result = subprocess.run([sys.executable, '-c', TRACED_RUNNER, SECRET, *args], capture_output=True, text=True,
                            timeout=90, env=_env(tmp_path), cwd=str(REPO))
    return result, json.loads(result.stderr.strip().splitlines()[-1])


def _snapshot(store):
    with sqlite3.connect(store.as_uri() + '?mode=ro', uri=True) as connection:
        return (connection.execute('SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY 1, 2').fetchall(),
                {table: connection.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in _PRESERVED})


def test_full_parent_runs_through_ready_writer_without_bootstrap_seed_or_ddl(tmp_path):
    root, mission_id = _caller_store(tmp_path)
    store = root / '.fnignis' / 'canonical.sqlite3'
    schema, preserved = _snapshot(store)
    packet, confirmation = _packet(tmp_path)
    result, trace = _traced(_args(root, mission_id, packet, confirmation), tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['observations'] == 1 and trace['calls'] == ['search', 'videos']
    touched = [name for name, path in trace['entered'] if path == str(store)]
    assert touched == [], f'Caller store re-entered bootstrap, seed or DDL: {touched}'
    assert _snapshot(store) == (schema, preserved), 'Schema objects or preserved vocabulary/config/workspace rows changed'


@pytest.mark.parametrize('drift', [
    'CREATE INDEX extra_mission_index ON research_missions (status)',
    'DROP TRIGGER mission_progress_events_validate_update',
])
def test_core_or_progress_drift_refuses_before_allocation_and_source(tmp_path, drift):
    root, mission_id = _caller_store(tmp_path)
    store = root / '.fnignis' / 'canonical.sqlite3'
    with sqlite3.connect(store) as connection:
        connection.execute(drift)
    before = _digest_file(store)
    packet, confirmation = _packet(tmp_path)
    result, trace = _traced(_args(root, mission_id, packet, confirmation), tmp_path)
    assert json.loads(result.stdout) == {'status': 'REFUSED', 'reason_code': 'CALLER_SCHEMA_UNSUPPORTED'}
    assert trace['calls'] == []
    assert _digest_file(store) == before and not (root / '.fnignis' / 'follow-up').exists()


def test_wrong_progress_definitions_with_expected_names_refuse(tmp_path):
    root, mission_id = _caller_store(tmp_path, progress=False)
    store = root / '.fnignis' / 'canonical.sqlite3'
    with sqlite3.connect(store) as connection:
        connection.executescript(
            'CREATE TABLE mission_progress_revisions (mission_id TEXT PRIMARY KEY, revision INTEGER);'
            'CREATE TABLE mission_progress_events (id TEXT PRIMARY KEY, mission_id TEXT);'
            'CREATE TABLE mission_progress_commands (mission_id TEXT, command_key TEXT,'
            ' PRIMARY KEY (mission_id, command_key));')
    before = _digest_file(store)
    packet, confirmation = _packet(tmp_path)
    result, trace = _traced(_args(root, mission_id, packet, confirmation), tmp_path)
    assert json.loads(result.stdout) == {'status': 'REFUSED', 'reason_code': 'CALLER_SCHEMA_UNSUPPORTED'}
    assert trace['calls'] == []
    assert _digest_file(store) == before and not (root / '.fnignis' / 'follow-up').exists()
