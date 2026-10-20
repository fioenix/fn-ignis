"""Private restart deletion disposition; no database, source, credential or writer capability.

The trusted root supplies owner approval and action-time confirmation. Matching local bytes
is an integrity check, not proof of human consent. Concurrent hostile filesystem mutation
between the final identity check and unlink remains a filesystem race boundary.
"""
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from uuid import UUID, uuid4


class CleanupRefused(ValueError):
    """Safe refusal without payload, secret, or filesystem contents in diagnostics."""


def _refuse():
    raise CleanupRefused('EXACT_EXPIRED_CLOSED_CLEANUP_SCOPE_REQUIRED')


def _identity(path, *, directory=False):
    info = path.lstat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        _refuse()
    return [info.st_dev, info.st_ino]


def _parents(path):
    return {str(parent): _identity(parent, directory=True) for parent in path.parents}


def _file(path):
    identity = _identity(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if [os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino] != identity:
            _refuse()
        checksum = sha256(stream.read()).hexdigest()
    if _identity(path) != identity:
        _refuse()
    return {'identity': identity, 'sha256': checksum}


def _inventory(root):
    files, directories = {}, {str(root): _identity(root, directory=True)}
    for parent, names, filenames in os.walk(root, followlinks=False):
        for name in names:
            path = Path(parent) / name
            directories[str(path)] = _identity(path, directory=True)
        for name in filenames:
            path = Path(parent) / name
            files[str(path)] = _file(path)
    return files, directories


def _time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        _refuse()
    return parsed


def _hash(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        _refuse()


def seal_cleanup_manifest(*, root, copies, authority, manifest_path):
    """Snapshot explicit quiescent closed ownership only; never delete or persist evidence."""
    root, manifest_path = Path(root), Path(manifest_path)
    required = {'owner_reference', 'owner_decision', 'coordinator', 'mission_id', 'run_id',
        'scope_digest', 'packet_sha256', 'confirmation_sha256', 'started_at', 'deadline',
        'retention_until', 'closed_disposition'}
    if type(authority) is not dict or set(authority) != required:
        _refuse()
    for key in required:
        if type(authority[key]) is not str or not authority[key]:
            _refuse()
    UUID(authority['mission_id'])
    UUID(authority['run_id'])
    for key in ('scope_digest', 'packet_sha256', 'confirmation_sha256'):
        _hash(authority[key])
    if not (_time(authority['started_at']) < _time(authority['deadline']) < _time(authority['retention_until'])):
        _refuse()
    if authority['closed_disposition'] != 'SOURCE_REVOKED_QUIESCENT_STORAGE_CLOSED':
        _refuse()
    owner = json.loads((root / 'generated-ownership.json').read_text())
    if (owner['owner_reference'] != authority['owner_reference']
            or owner['scope_digest'] != authority['scope_digest']
            or _time(owner['retention_until']) != _time(authority['retention_until'])
            or owner['root_identity'] != _identity(root, directory=True)):
        _refuse()
    registered = json.loads((root / 'generated-files.json').read_text())
    if registered['receipt_hash'] != sha256((root / 'generated-ownership.json').read_bytes()).hexdigest():
        _refuse()
    files, directories = _inventory(root)
    known = {str(root / name) for name in registered['files']}
    known.update(str(root / name) for name in ('generated-ownership.json', 'generated-files.json',
        'root-scope.json', 'canonical/ownership.json', 'canonical/bootstrap-ownership.json',
        'accounting/private-run.sqlite3'))
    if not files.keys() <= known or not {str(root / name) for name in registered['files']} <= files.keys():
        _refuse()
    for name, registration in registered['files'].items():
        actual = files[str(root / name)]
        if registration['kind'] == 'generated':
            if (registration.get('state') != 'settled' or registration.get('bindings') != [
                    {'identity': actual['identity'], 'hash': actual['sha256']}]):
                _refuse()
        elif registration['kind'] == 'canonical-delegated':
            if registration['identities'] != [actual['identity']]:
                _refuse()
        else:
            _refuse()
    copy_paths = [Path(copy) for copy in copies]
    if len(set(copy_paths)) != len(copy_paths) or any(root == copy or root in copy.parents for copy in copy_paths):
        _refuse()
    for copy in copy_paths:
        files[str(copy)] = _file(copy)
    parents = _parents(root) | _parents(manifest_path)
    for path in files:
        parents.update(_parents(Path(path)))
    record = {'schema': 'ORIGINAL_CLOSED_CLEANUP_V1', 'authority': dict(authority),
        'root': str(root), 'copies': [str(copy) for copy in copy_paths],
        'files': files, 'directories': directories, 'parents': parents}
    _validate(record)
    data = (json.dumps(record, sort_keys=True, indent=2) + '\n').encode()
    with manifest_path.open('xb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return sha256(data).hexdigest()


def _validate(record):
    if (type(record) is not dict or set(record) != {'schema','authority','root','copies','files','directories','parents'}
            or record['schema'] != 'ORIGINAL_CLOSED_CLEANUP_V1'):
        _refuse()
    authority = record['authority']
    required = {'owner_reference', 'owner_decision', 'coordinator', 'mission_id', 'run_id',
        'scope_digest', 'packet_sha256', 'confirmation_sha256', 'started_at', 'deadline',
        'retention_until', 'closed_disposition'}
    if type(authority) is not dict or set(authority) != required:
        _refuse()
    if any(type(authority[key]) is not str or not authority[key] for key in required):
        _refuse()
    UUID(authority['mission_id'])
    UUID(authority['run_id'])
    for key in ('scope_digest', 'packet_sha256', 'confirmation_sha256'):
        _hash(authority[key])
    if (authority['closed_disposition'] != 'SOURCE_REVOKED_QUIESCENT_STORAGE_CLOSED'
            or not _time(authority['started_at']) < _time(authority['deadline']) < _time(authority['retention_until'])):
        _refuse()
    if any(type(record[key]) is not dict for key in ('files','directories','parents')) or not record['files']:
        _refuse()
    root = Path(record['root'])
    for name in [record['root'], *record['copies'], *record['files'], *record['directories'], *record['parents']]:
        path = Path(name)
        if not path.is_absolute() or str(path) != name or '..' in path.parts:
            _refuse()
    copies = record['copies']
    if type(copies) is not list or len(set(copies)) != len(copies):
        _refuse()
    for name, value in record['files'].items():
        path = Path(name)
        if name not in copies and root not in path.parents:
            _refuse()
        if set(value) != {'identity','sha256'} or len(value['identity']) != 2:
            _refuse()
        _hash(value['sha256'])
    if any(name not in record['files'] for name in copies):
        _refuse()
    for identity in [*[row['identity'] for row in record['files'].values()],
                     *record['directories'].values(), *record['parents'].values()]:
        if type(identity) is not list or len(identity) != 2 or any(type(v) is not int or v < 0 for v in identity):
            _refuse()
    for name in record['directories']:
        if Path(name) != root and root not in Path(name).parents:
            _refuse()
    expected_parents = set()
    for name in [record['root'], *record['files']]:
        expected_parents.update(str(parent) for parent in Path(name).parents)
    if not expected_parents <= record['parents'].keys():
        _refuse()


def _load(manifest_path, expected_sha256):
    _hash(expected_sha256)
    _identity(manifest_path)
    data = manifest_path.read_bytes()
    if sha256(data).hexdigest() != expected_sha256:
        _refuse()
    record = json.loads(data)
    _validate(record)
    if not set(_parents(manifest_path)) <= record['parents'].keys():
        _refuse()
    return record


def _check(record, audit):
    for name, identity in (record['parents'] | record['directories']).items():
        if _identity(Path(name), directory=True) != identity:
            _refuse()
    current, _ = _inventory(Path(record['root']))
    if not current.keys() <= record['files'].keys():
        _refuse()
    for name, value in record['files'].items():
        path = Path(name)
        if path.exists() or path.is_symlink():
            if name in audit['completed'] or _file(path) != value:
                _refuse()
        elif name not in audit['completed'] and name != audit['intent']:
            _refuse()


def _audit(path, expected_sha256, record):
    if path.exists() or path.is_symlink():
        _identity(path)
        value = json.loads(path.read_text())
        if (set(value) != {'manifest_sha256','run_id','completed','intent','purged','updated_at'}
                or value['manifest_sha256'] != expected_sha256 or value['run_id'] != record['authority']['run_id']
                or type(value['completed']) is not list or len(set(value['completed'])) != len(value['completed'])
                or not set(value['completed']) <= record['files'].keys()
                or (value['intent'] is not None and (value['intent'] not in record['files']
                    or value['intent'] in value['completed']))
                or type(value['purged']) is not bool
                or (value['purged'] and (set(value['completed']) != record['files'].keys()
                    or value['intent'] is not None))):
            _refuse()
        return value
    return {'manifest_sha256': expected_sha256, 'run_id': record['authority']['run_id'],
        'completed': [], 'intent': None, 'purged': False, 'updated_at': None}


def _publish(path, audit):
    temporary = path.parent / ('.' + uuid4().hex + '.cleanup.tmp')
    try:
        with temporary.open('x') as output:
            json.dump(audit, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def preflight_cleanup(manifest_path, expected_sha256):
    """Read-only integrity/coverage check; neither consent nor a purge operation."""
    manifest_path = Path(manifest_path)
    record = _load(manifest_path, expected_sha256)
    audit = _audit(manifest_path.with_suffix('.audit.json'), expected_sha256, record)
    _check(record, audit)
    return {'status': 'CLEANUP_PREFLIGHT_VERIFIED', 'run_id': record['authority']['run_id'],
        'file_count': len(record['files']), 'copy_count': len(record['copies']),
        'retention_until': record['authority']['retention_until'], 'purged': audit['purged']}


def purge_confirmed_cleanup(manifest_path, expected_sha256, confirmation):
    """Action-time trusted-root instruction, actual UTC expiry, exact deletion-only retry."""
    manifest_path = Path(manifest_path)
    record = _load(manifest_path, expected_sha256)
    now = datetime.now(timezone.utc)
    authority = record['authority']
    if (type(confirmation) is not dict or set(confirmation) != {'operation','owner_decision','coordinator',
            'run_id','manifest_sha256','confirmed_at'}
            or confirmation['operation'] != 'PURGE_EXPIRED_ORIGINAL'
            or any(confirmation[key] != authority[key] for key in ('owner_decision','coordinator','run_id'))
            or confirmation['manifest_sha256'] != expected_sha256
            or not _time(authority['retention_until']) <= _time(confirmation['confirmed_at']) <= now
            or now < _time(authority['retention_until'])):
        _refuse()
    lock_path = manifest_path.with_suffix('.lock')
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        audit_path = manifest_path.with_suffix('.audit.json')
        audit = _audit(audit_path, expected_sha256, record)
        _check(record, audit)
        for name in record['files']:
            if name in audit['completed']:
                continue
            audit.update(intent=name, updated_at=now.isoformat())
            _publish(audit_path, audit)
            path = Path(name)
            if path.exists() or path.is_symlink():
                if _file(path) != record['files'][name]:
                    _refuse()
                path.unlink()
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            audit['completed'].append(name)
            audit['intent'] = None
            _publish(audit_path, audit)
        audit['purged'] = True
        _publish(audit_path, audit)
        return {'status':'ORIGINAL_CLEANUP_PURGED','run_id':authority['run_id'],
            'removed_files':len(audit['completed']),'retention_until':authority['retention_until']}
    finally:
        os.close(descriptor)
