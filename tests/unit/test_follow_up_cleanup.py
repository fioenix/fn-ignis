"""Synthetic original ownership; restart cleanup never restores a source or SQLite writer."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import pytest
import pytest_asyncio
from ignis.infrastructure import follow_up_cleanup as cleanup
from ignis.infrastructure import follow_up_root_composition as composition
from tests.unit.test_follow_up_root_composition import framing, INSTRUCTION

SCRIPT = Path(__file__).parents[2] / 'scripts/purge_follow_up_owned.py'


@pytest_asyncio.fixture
async def disposition(tmp_path, monkeypatch):
    root = tmp_path / 'owned-runtime'
    original = Path.open
    def fail(path, *args, **kwargs):
        if path == root / 'root-scope.json': raise OSError('SYNTHETIC_AFTER_SEAL_FAILURE')
        return original(path, *args, **kwargs)
    brief, receipt = framing()
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', fail)
        with pytest.raises(composition.StartupRetentionFailure) as caught:
            await composition.bootstrap_confirmed_parent(root=root, brief=brief, receipt=receipt,
                instruction=INSTRUCTION, resolve_credential=lambda: (_ for _ in ()).throw(AssertionError()),
                transport=None, quota_manager=None, clusterer=None)
    recovery = caught.value.recovery
    original_owner = json.loads((root / 'generated-ownership.json').read_text())
    # Expired time belongs only to disposable offline fixture metadata, not any live mission.
    start = datetime.now(timezone.utc) - timedelta(days=8)
    expiry = start + timedelta(days=7)
    original_owner['retention_until'] = expiry.isoformat()
    owner_path = root / 'generated-ownership.json'
    owner_path.write_text(json.dumps(original_owner))
    registered_path = root / 'generated-files.json'
    registered = json.loads(registered_path.read_text())
    registered['receipt_hash'] = sha256(owner_path.read_bytes()).hexdigest()
    registered_path.write_text(json.dumps(registered))
    copy = tmp_path / 'evidence-copy.json'
    copy.write_text('{"description":"Synthetic retained evidence"}')
    manifest = tmp_path / 'cleanup.json'
    authority = {'owner_reference': original_owner['owner_reference'], 'owner_decision': 'SYNTHETIC_OWNER_APPROVAL',
        'coordinator':'SYNTHETIC_ROOT_COORDINATOR','mission_id':str(recovery.confirmation.selected_parent_id),
        'run_id':str(recovery.confirmation.bounds.run_id),'scope_digest':original_owner['scope_digest'],
        'packet_sha256':'a'*64,'confirmation_sha256':'b'*64,'started_at':start.isoformat(),
        'deadline':(start+timedelta(minutes=15)).isoformat(),'retention_until':expiry.isoformat(),
        'closed_disposition':'SOURCE_REVOKED_QUIESCENT_STORAGE_CLOSED'}
    checksum = cleanup.seal_cleanup_manifest(root=root, copies=[copy], authority=authority, manifest_path=manifest)
    confirmation = {'operation':'PURGE_EXPIRED_ORIGINAL','owner_decision':authority['owner_decision'],
        'coordinator':authority['coordinator'],'run_id':authority['run_id'],'manifest_sha256':checksum,
        'confirmed_at':datetime.now(timezone.utc).isoformat()}
    confirm_path = tmp_path / 'action.json'; confirm_path.write_text(json.dumps(confirmation))
    return root, copy, manifest, checksum, confirmation, confirm_path


def invoke(manifest, checksum, confirmation=None):
    args = ['--preflight'] if confirmation is None else ['--action-confirmation',str(confirmation)]
    return subprocess.run([sys.executable,str(SCRIPT),'--manifest',str(manifest),'--sha256',checksum,*args],
        capture_output=True,text=True,timeout=10)


@pytest.mark.asyncio
async def test_fresh_process_physically_deletes_exact_original_files_and_copy_then_replays(disposition):
    root, copy, manifest, checksum, confirmation, confirm_path = disposition
    files = set(json.loads(manifest.read_text())['files'])
    assert invoke(manifest,checksum).returncode == 0
    assert all(Path(name).exists() for name in files)
    assert invoke(manifest,checksum,confirm_path).returncode == 0
    assert all(not Path(name).exists() for name in files) and not copy.exists()
    again = invoke(manifest,checksum,confirm_path)
    assert again.returncode == 0
    assert json.loads(again.stdout)['removed_files'] == len(files)
    audit = json.loads(manifest.with_suffix('.audit.json').read_text())
    assert audit['purged'] and set(audit['completed']) == files and audit['intent'] is None


@pytest.mark.parametrize('change',['replaced','changed','symlink','parent','foreign','missing','authority'])
@pytest.mark.asyncio
async def test_whole_scope_refusal_precedes_any_original_deletion(disposition, change):
    root, copy, manifest, checksum, confirmation, confirm_path = disposition
    canonical = root / 'canonical/canonical.sqlite3'
    before = canonical.read_bytes()
    if change == 'replaced':
        replacement = copy.with_suffix('.replacement'); replacement.write_bytes(copy.read_bytes()); replacement.replace(copy)
    elif change == 'changed': copy.write_text('Changed synthetic payload')
    elif change == 'symlink':
        copy.unlink(); copy.symlink_to(canonical)
    elif change == 'parent':
        directory = root / '.ignis'; directory.rename(root / '.ignis-original'); directory.symlink_to(root / '.ignis-original')
    elif change == 'foreign': (root / 'unregistered.txt').write_text('Foreign preserved')
    elif change == 'missing': copy.unlink()
    else:
        confirmation['run_id'] = str(uuid4()); confirm_path.write_text(json.dumps(confirmation))
    assert invoke(manifest,checksum,confirm_path).returncode == 2
    assert canonical.read_bytes() == before
    if change == 'foreign': assert (root / 'unregistered.txt').read_text() == 'Foreign preserved'


@pytest.mark.asyncio
async def test_before_expiry_original_identity_is_preserved_without_audit(disposition, monkeypatch):
    root, copy, manifest, checksum, confirmation, _ = disposition
    class BeforeExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(json.loads(manifest.read_text())['authority']['retention_until'])-timedelta(seconds=1)
    monkeypatch.setattr(cleanup, 'datetime', BeforeExpiry)
    inode = copy.stat().st_ino
    with pytest.raises(cleanup.CleanupRefused): cleanup.purge_confirmed_cleanup(manifest,checksum,confirmation)
    assert copy.stat().st_ino == inode and (root/'canonical/canonical.sqlite3').exists()
    assert not manifest.with_suffix('.audit.json').exists()


@pytest.mark.parametrize('interruption',['before_unlink','after_unlink'])
@pytest.mark.asyncio
async def test_restart_retry_consumes_original_durable_intent_only(disposition, monkeypatch, interruption):
    root, copy, manifest, checksum, confirmation, confirm_path = disposition
    original_publish = cleanup._publish
    calls = []
    def interrupt(path, audit):
        calls.append(dict(audit))
        if interruption=='after_unlink' and len(audit['completed'])==1:
            raise OSError('SYNTHETIC_PROCESS_INTERRUPTION')
        original_publish(path,audit)
        if interruption=='before_unlink' and audit['intent'] is not None:
            raise OSError('SYNTHETIC_PROCESS_INTERRUPTION')
    with monkeypatch.context() as patch:
        patch.setattr(cleanup,'_publish',interrupt)
        with pytest.raises(OSError): cleanup.purge_confirmed_cleanup(manifest,checksum,confirmation)
    assert invoke(manifest,checksum,confirm_path).returncode == 0
    assert not (root/'canonical/canonical.sqlite3').exists() and not copy.exists()


def test_private_cli_imports_no_provider_config_or_database_and_has_no_clock_or_force_option():
    import ast
    modules=[]
    for path in (SCRIPT,Path(cleanup.__file__)):
        tree=ast.parse(path.read_text())
        modules += [node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
    assert not any(name and ('config' in name or 'sqlite' in name or 'http' in name or 'provider' in name) for name in modules)
    assert '--force' not in SCRIPT.read_text() and '--now' not in SCRIPT.read_text()
