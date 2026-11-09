"""Raw, projection-gated retirement; never initialize an application repository."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

# Retired data identifiers, not a runtime lexicon or a classification vocabulary.
FORMER_CODES = (
    'auto', 'beauty', 'ecommerce', 'education', 'entertainment', 'fashion', 'finance',
    'food', 'health', 'news', 'realestate', 'sports', 'tech', 'travel',
)
PROTECTED_SETS = (
    'sources', 'observations', 'mission_evidence', 'trend_signals', 'signal_metrics',
    'research_missions', 'mission_manifests', 'market_brief_revisions',
    'mission_run_journals', 'mission_probe_outcomes', 'mission_evidence_qualifications',
    'mission_claims', 'mission_claim_evidence', 'market_lexicons',
)
FORMAT_VERSION = 'ignis-taxonomy-retirement-v1'
MIGRATION_ID = '039_remove_seeded_taxonomy'
TABLE = 'industry_taxonomies'


class RetirementError(Exception):
    """Stable public reason; raw driver errors must never reach receipts."""

    def __init__(self, reason: str, exit_code: int = 1):
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code


def _scalar(value):
    if value is None:
        return ['null']
    if isinstance(value, bool):
        return ['bool', value]
    if isinstance(value, int):
        return ['int', str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RetirementError('UNSUPPORTED_VALUE', 2)
        return ['float', value.hex()]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise RetirementError('UNSUPPORTED_VALUE', 2)
        return ['decimal', str(value)]
    if isinstance(value, str):
        return ['str', value]
    if isinstance(value, UUID):
        return ['uuid', str(value)]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise RetirementError('UNSUPPORTED_VALUE', 2)
        return ['datetime', value.astimezone(timezone.utc).isoformat()]
    if isinstance(value, date):
        return ['date', value.isoformat()]
    if isinstance(value, (bytes, memoryview)):
        return ['bytes', bytes(value).hex()]
    if isinstance(value, (list, tuple)):
        return ['array', [_scalar(item) for item in value]]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return ['object', {key: _scalar(item) for key, item in sorted(value.items())}]
    raise RetirementError('UNSUPPORTED_VALUE', 2)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    """Canonical, typed, length-delimited content digest."""
    payload = _json(_scalar(value))
    return hashlib.sha256(len(payload).to_bytes(8, 'big') + payload).hexdigest()


class _RowsDigest:
    def __init__(self, table, columns):
        self.hash = hashlib.sha256()
        self.count = 0
        self.add_record([FORMAT_VERSION, table, list(columns)])

    def add_record(self, value):
        encoded = _json(_scalar(value))
        self.hash.update(len(encoded).to_bytes(8, 'big'))
        self.hash.update(encoded)

    def row(self, value):
        self.add_record(value)
        self.count += 1

    def finish(self):
        copy = self.hash.copy()
        encoded = _json(['row_count', self.count])
        copy.update(len(encoded).to_bytes(8, 'big'))
        copy.update(encoded)
        return {'count': self.count, 'digest': copy.hexdigest()}


def sqlite_identity(path):
    path = Path(path).resolve(strict=True)
    stat = path.stat()
    return digest(['sqlite', str(path), stat.st_dev, stat.st_ino])


def postgres_identity(connection):
    row = connection.execute(
        'SELECT current_database(), inet_server_addr()::text, inet_server_port()'
    ).fetchone()
    return digest(['postgres', *row])


def _schema(connection, backend):
    if backend == 'sqlite':
        return [list(row) for row in connection.execute(
            'SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name'
        )]
    if backend != 'postgres':
        raise RetirementError('UNSUPPORTED_BACKEND', 2)
    # Stable names and definitions, never object OIDs or secret table contents.
    queries = (
        "SELECT 'table', c.relname, c.relname, jsonb_build_array(c.relkind, c.relrowsecurity, "
        "c.relforcerowsecurity, c.relacl) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S')",
        "SELECT 'column', a.attname, c.relname, jsonb_build_array(format_type(a.atttypid,a.atttypmod), "
        "a.attnotnull, pg_get_expr(d.adbin,d.adrelid), a.attidentity, a.attgenerated) "
        "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d "
        "ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE n.nspname='public' "
        "AND c.relkind IN ('r','p','v','m') AND a.attnum>0 AND NOT a.attisdropped",
        "SELECT 'constraint', conname, rel.relname, pg_get_constraintdef(c.oid)::text "
        "FROM pg_constraint c JOIN pg_class rel ON rel.oid=c.conrelid "
        "JOIN pg_namespace n ON n.oid=rel.relnamespace WHERE n.nspname='public'",
        "SELECT 'index', indexname, tablename, indexdef FROM pg_indexes WHERE schemaname='public'",
        "SELECT 'policy', policyname, tablename, jsonb_build_array(permissive,roles,cmd,qual,with_check) "
        "FROM pg_policies WHERE schemaname='public'",
        "SELECT 'trigger', t.tgname, c.relname, pg_get_triggerdef(t.oid) "
        "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal",
        "SELECT 'view', viewname, viewname, definition FROM pg_views WHERE schemaname='public'",
    )
    records = [list(row) for query in queries for row in connection.execute(query)]
    return sorted(records, key=lambda row: _json(_scalar(row)))


def _rows(connection, backend, table):
    # Table names come exclusively from the fixed preservation boundary above.
    if backend == 'sqlite':
        info = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = sorted(row[1] for row in info)
        keys = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
    else:
        info = connection.execute(
            'SELECT column_name FROM information_schema.columns '
            "WHERE table_schema='public' AND table_name=%s ORDER BY column_name", (table,),
        ).fetchall()
        columns = [row[0] for row in info]
        keys = [row[0] for row in connection.execute(
            'SELECT a.attname FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid '
            'JOIN pg_namespace n ON n.oid=c.relnamespace '
            'JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=ANY(i.indkey) '
            "WHERE n.nspname='public' AND c.relname=%s AND i.indisprimary ORDER BY a.attname", (table,),
        )]
    if not columns or not keys or (table == 'topic_clusters' and not {'id', 'category'} <= set(columns)):
        raise RetirementError('UNSUPPORTED_STORE', 2)
    selected = ','.join('"' + name.replace('"', '""') + '"' for name in columns)
    order = ','.join('"' + name.replace('"', '""') + '"' for name in keys)
    prefix = 'public.' if backend == 'postgres' else ''
    return columns, connection.execute(f'SELECT {selected} FROM {prefix}"{table}" ORDER BY {order}')


def project(connection, backend, store_identity):
    """Read one consistent snapshot and hash complete rows without exporting their content.

    PostgreSQL callers establish REPEATABLE READ before invoking this reader. Apply callers
    own their transaction and acquire write-blocking locks before its first snapshot.
    """
    if backend == 'sqlite' and not connection.in_transaction:
        connection.execute('BEGIN')
    schema = _schema(connection, backend)
    present = any(row[0] == 'table' and row[1] == TABLE for row in schema)
    columns, rows = _rows(connection, backend, 'topic_clusters')
    noncategory = [column for column in columns if column != 'category']
    before = _RowsDigest('topic_clusters', columns)
    after = _RowsDigest('topic_clusters', columns)
    preserved = _RowsDigest('topic_clusters', noncategory)
    targets = _RowsDigest('targets', ['id', 'category'])
    counts = dict.fromkeys(FORMER_CODES, 0)
    for values in rows:
        row = dict(zip(columns, values))
        before.row(row)
        preserved.row({key: row[key] for key in noncategory})
        if row['category'] in counts:
            counts[row['category']] += 1
            if present:
                targets.row({key: row[key] for key in ('id', 'category')})
                row['category'] = 'unclassified'
        after.row(row)
    protected = {}
    for table in sorted(PROTECTED_SETS):
        fields, records = _rows(connection, backend, table)
        hashed = _RowsDigest(table, fields)
        for record in records:
            hashed.row(dict(zip(fields, record)))
        protected[table] = hashed.finish()
    reset = counts if present else dict.fromkeys(FORMER_CODES, 0)
    result = {
        'format_version': FORMAT_VERSION, 'migration_id': MIGRATION_ID,
        'backend': backend, 'store_identity': store_identity,
        'table_present': present, 'state': 'PENDING' if present else 'ALREADY_RETIRED',
        'former_codes': list(FORMER_CODES), 'former_codes_digest': digest(FORMER_CODES),
        'cluster_count': before.count, 'matching_code_counts': counts,
        'reset_counts': reset, 'reset_total': sum(reset.values()),
        'target_digest': targets.finish()['digest'],
        'clusters_before_digest': before.finish()['digest'],
        'clusters_expected_after_digest': after.finish()['digest'],
        'cluster_noncategory_digest': preserved.finish()['digest'], 'protected_sets': protected,
        'schema_before_digest': digest(schema),
        'schema_expected_after_digest': digest([row for row in schema if row[2] != TABLE]),
        'invariants': {'category_only': True, 'evidence_unchanged': True, 'lexicons_unchanged': True},
        'limitations': ['SOURCE_CODE_COLLISION'] if present else ['ABSENT_TABLE_PROVENANCE_UNKNOWN'],
    }
    result['projection_digest'] = digest(result)
    return result


def _validate_baseline(baseline, backend, store_identity):
    if not isinstance(baseline, dict):
        raise RetirementError('INVALID_BASELINE')
    content = {key: value for key, value in baseline.items() if key != 'projection_digest'}
    if (baseline.get('projection_digest') != digest(content)
            or baseline.get('format_version') != FORMAT_VERSION
            or baseline.get('migration_id') != MIGRATION_ID
            or baseline.get('backend') != backend
            or baseline.get('store_identity') != store_identity
            or baseline.get('former_codes') != list(FORMER_CODES)
            or baseline.get('former_codes_digest') != digest(FORMER_CODES)
            or baseline.get('invariants') != {'category_only': True, 'evidence_unchanged': True, 'lexicons_unchanged': True}):
        raise RetirementError('INVALID_BASELINE')


def verify(connection, backend, store_identity, baseline):
    """Compare actual rows and schema with the published expected post-state."""
    _validate_baseline(baseline, backend, store_identity)
    actual = project(connection, backend, store_identity)
    checks = {
        'table_absent': not actual['table_present'],
        'clusters': actual['clusters_before_digest'] == baseline.get('clusters_expected_after_digest'),
        'noncategory': actual['cluster_noncategory_digest'] == baseline.get('cluster_noncategory_digest'),
        'evidence': actual['protected_sets'] == baseline.get('protected_sets'),
        'schema': actual['schema_before_digest'] == baseline.get('schema_expected_after_digest'),
    }
    if not all(checks.values()):
        raise RetirementError('POST_STATE_MISMATCH')
    return {'status': 'VERIFIED', 'changed_count': 0, 'invariants': checks,
            'clusters_digest': actual['clusters_before_digest'],
            'schema_digest': actual['schema_before_digest']}


def apply(connection, backend, store_identity, baseline):
    """Lock, recheck the published snapshot, mutate, verify actual state, then commit."""
    _validate_baseline(baseline, backend, store_identity)
    if backend not in ('sqlite', 'postgres'):
        raise RetirementError('UNSUPPORTED_BACKEND', 2)
    active = connection.in_transaction if backend == 'sqlite' else bool(connection.info.transaction_status)
    if active:
        raise RetirementError('ACTIVE_TRANSACTION')
    try:
        if backend == 'sqlite':
            connection.execute('PRAGMA busy_timeout = 5000')
            connection.execute('BEGIN IMMEDIATE')
        else:
            connection.execute("SET LOCAL lock_timeout = '5s'")
            # No snapshot is read before these locks. All apply callers use this order.
            for table in sorted((*PROTECTED_SETS, 'topic_clusters')):
                connection.execute(f'LOCK TABLE public."{table}" IN ACCESS EXCLUSIVE MODE')
            if connection.execute("SELECT to_regclass('public.industry_taxonomies')").fetchone()[0]:
                connection.execute('LOCK TABLE public.industry_taxonomies IN ACCESS EXCLUSIVE MODE')
        current = project(connection, backend, store_identity)
        if not current['table_present']:
            result = verify(connection, backend, store_identity, baseline)
            connection.rollback()  # A validated retry writes nothing, including no marker.
            return {**result, 'status': 'ALREADY_RETIRED', 'committed': False}
        if current != baseline:
            raise RetirementError('BASELINE_DRIFT')
        if backend == 'sqlite':
            import re
            # SQLite permits dropping a table still referenced by a view or trigger. Refuse
            # those dependencies explicitly; never leave another object's SQL broken.
            if any(row[2] != TABLE and row[3] and re.search(r'\bindustry_taxonomies\b', row[3], re.I)
                   for row in _schema(connection, backend)):
                raise RetirementError('DEPENDENT_OBJECT')
            placeholders = ','.join('?' for _ in FORMER_CODES)
            connection.execute(
                f'UPDATE topic_clusters SET category = ? WHERE category IN ({placeholders})',
                ('unclassified', *FORMER_CODES),
            )
            connection.execute('DROP TABLE industry_taxonomies')
        else:
            from ignis.resources import sql_seed_file
            migration = sql_seed_file(MIGRATION_ID + '.sql')
            if migration is None:
                raise RetirementError('MIGRATION_UNAVAILABLE', 2)
            connection.execute("SELECT set_config('ignis.taxonomy_projection_digest', %s, true)",
                               (baseline['projection_digest'],))
            connection.execute(migration.read_text(encoding='utf-8'))
        result = verify(connection, backend, store_identity, baseline)
        connection.commit()
        return {**result, 'status': 'APPLIED', 'changed_count': baseline['reset_total'], 'committed': True}
    except Exception as error:
        connection.rollback()
        if isinstance(error, RetirementError):
            raise
        raise RetirementError('APPLY_FAILED') from None
