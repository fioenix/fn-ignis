"""T071 direct dual-backend schema controls, not atomic admission or execution."""
from contextlib import contextmanager
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql

from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.sqlite_research_schema import install_research_schema
from tests.integration.conftest import SCHEMA_MIGRATIONS, RUNTIME_ROLE, runtime_owner

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'sql/029_mission_follow_up.sql'
TABLES = ('mission_follow_up_work', 'mission_follow_ups', 'mission_follow_up_reservations')
CANONICAL = ('research_workspaces', 'research_missions', 'market_brief_revisions',
             'sources', 'observations', 'mission_evidence', 'mission_claims', 'mission_claim_evidence',
             'mission_run_journals', 'mission_manifests', 'research_assignments', 'research_work_items',
             'research_input_sets')


class Schema:
    def __init__(self, connection, postgres, admin_dsn=None):
        self.conn, self.postgres, self.admin_dsn = connection, postgres, admin_dsn

    def execute(self, statement, params=()):
        return self.conn.execute(statement if self.postgres else statement.replace('%s', '?'), params)

    def insert(self, table, values):
        # Identifiers are literal test-controlled schema names, never external input.
        return self.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('%s' for _ in values)})",
                            tuple(values.values()))

    def install(self):
        assert MIGRATION.is_file(), 'T071 migration unavailable; not behavioral RED.'
        if self.postgres:
            with psycopg.connect(self.admin_dsn) as installer:
                installer.execute(MIGRATION.read_text())
                for table in TABLES:
                    installer.execute(sql.SQL('ALTER TABLE public.{} OWNER TO {}').format(
                        sql.Identifier(table), sql.Identifier(RUNTIME_ROLE)))
                for signature in ('follow_up_scope_valid(TEXT,BOOLEAN)', 'validate_follow_up_record()',
                                  'preserve_follow_up_record()', 'preserve_follow_up_mission_owner()'):
                    installer.execute(sql.SQL('ALTER FUNCTION public.' + signature + ' OWNER TO {}').format(
                        sql.Identifier(RUNTIME_ROLE)))
        else:
            module = importlib.import_module('ignis.infrastructure.persistence.sqlite_follow_up_schema')
            module.install_follow_up_schema(self.conn)

    def baseline(self):
        return {t: self.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall() for t in CANONICAL}

    @contextmanager
    def rejected(self, kind):
        error = {'check': psycopg.errors.CheckViolation, 'foreign': psycopg.errors.ForeignKeyViolation,
                 'unique': psycopg.errors.UniqueViolation, 'notnull': psycopg.errors.NotNullViolation}[kind] if self.postgres else sqlite3.IntegrityError
        if self.postgres:
            with pytest.raises(error):
                with self.conn.transaction():
                    yield
            return
        self.execute('SAVEPOINT refusal')
        try:
            with pytest.raises(error):
                yield
        finally:
            self.execute('ROLLBACK TO SAVEPOINT refusal')
            self.execute('RELEASE SAVEPOINT refusal')


@pytest_asyncio.fixture(params=('sqlite', 'postgres'))
async def schema(request, tmp_path):
    if request.param == 'sqlite':
        repository = SqliteTrendRepository(db_path=f"sqlite:///{tmp_path/'schema.db'}")
        await repository._ensure_schema()
        await repository._ensure_progress_schema()
        conn = repository._get_connection()
        install_research_schema(conn)
        conn.row_factory = None
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            yield Schema(conn, False)
        finally:
            conn.close()
            await repository.close()
    else:
        dsn = request.getfixturevalue('supabase_like_dsn')
        with psycopg.connect(dsn) as setup:
            for name in SCHEMA_MIGRATIONS:
                setup.execute((ROOT/'sql'/name).read_text())
        with runtime_owner(dsn) as owner_dsn, psycopg.connect(owner_dsn, autocommit=True) as conn:
            yield Schema(conn, True, dsn)


def seed(db):
    names = ('workspace', 'other_workspace', 'parent', 'child', 'foreign', 'assignment',
             'parent_work', 'work', 'inputs', 'brief', 'gap', 'follow_up', 'reservation')
    x = dict(zip(names, (str(uuid4()) for _ in names)))
    stamp = '2026-10-08T00:00:00+00:00'
    for name in ('workspace', 'other_workspace'):
        db.insert('research_workspaces', dict(id=x[name], slug=name, root_path=f'/{name}', created_at=stamp))
    for name in ('parent', 'child', 'foreign'):
        db.insert('research_missions', dict(id=x[name], title=name, keywords=['schema'] if db.postgres else '["schema"]',
                 geo_code='VN', workspace_id=x['other_workspace'] if name == 'foreign' else x['workspace'],
                 status='COMPLETED' if name == 'parent' else 'PENDING', created_at=stamp))
    db.insert('market_brief_revisions', dict(id=x['brief'], mission_id=x['parent'], workspace_id=x['workspace'],
              revision_number=1, decision='decide', target_user='operator', problem='gap', geo='VN', timeframe='7d',
              hypothesis='testable', falsifiers=['refused'] if db.postgres else '["refused"]',
              confirmed_by='owner', confirmed_at=stamp))
    db.insert('research_assignments', dict(assignment_id=x['assignment'], mission_id=x['parent'],
              host_task_ref='schema', epoch=1, actions=['FOLLOW_UP'] if db.postgres else '["FOLLOW_UP"]',
              sources=['youtube'] if db.postgres else '["youtube"]', deadline='2030-01-01T00:00:00+00:00',
              quota_ceiling=10, state='ACTIVE', version=1, expected_manifest_digest='a'*64,
              expected_brief_revision_id=x['brief']))
    db.insert('research_input_sets', dict(input_id=x['inputs'], mission_id=x['parent'],
              manifest_digest='a'*64, brief_digest='b'*64))
    for name in ('parent_work', 'work'):
        db.insert('research_work_items', dict(work_id=x[name], mission_id=x['parent'], assignment_id=x['assignment'],
                  input_id=x['inputs'], question='bounded', expertise='Synthesis', epoch=1, state='ASSIGNED',
                  version=1, ownership_fence='schema-fence'))
    for name in ('parent', 'child'):
        source, observation = str(uuid4()), str(uuid4())
        db.insert('sources', dict(id=source, platform='youtube', external_id=source))
        db.insert('observations', dict(id=observation, source_id=source, time_provenance='unknown',
                  identity_source='metadata_external_id'))
        db.insert('mission_evidence', dict(id=str(uuid4()), mission_id=x[name], observation_id=observation, recorded_at=stamp))
    return x


def work_values(x, **changes):
    return dict(work_id=x['work'], parent_mission_id=x['parent'], parent_work_id=x['parent_work'],
                assignment_id=x['assignment'], research_epoch=1, assignment_version=1, work_version=1,
                input_id=x['inputs'], brief_revision_id=x['brief'], gap_id=x['gap'],
                approved_queries='["bounded","falsifier"]', approved_sources='["youtube"]',
                requested_queries='["bounded"]', requested_sources='["youtube"]',
                authority_deadline='2030-01-01T00:00:00+00:00') | changes


def relation_values(x, **changes):
    return dict(follow_up_id=x['follow_up'], parent_mission_id=x['parent'], child_mission_id=x['child'],
                work_id=x['work'], reservation_id=x['reservation'], child_manifest_digest='c'*64,
                child_brief_digest='d'*64, idempotency_key='first') | changes


def reserve_values(x, **changes):
    return dict(reservation_id=x['reservation'], follow_up_id=x['follow_up'], parent_mission_id=x['parent'],
                child_mission_id=x['child'], reserved_quota=4, reserved_cost=6, state='RESERVED', version=1) | changes


def admit(db, x):
    # Deferred reciprocal FKs require both relation and reservation in one transaction.
    db.execute('BEGIN')
    try:
        db.insert(TABLES[1], relation_values(x))
        db.insert(TABLES[2], reserve_values(x))
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def prepared(db, **changes):
    x = seed(db)
    if not db.postgres:
        db.conn.commit()
    db.install()
    db.insert(TABLES[0], work_values(x, **changes))
    if not db.postgres:
        db.conn.commit()
    return x


def test_install_and_reapply_preserve_canonical_counts_and_digest(schema, record_property):
    seed(schema)
    if not schema.postgres:
        schema.conn.commit()
    before = schema.baseline()
    assert [len(before[t]) for t in ('sources','observations','mission_evidence')] == [2, 2, 2]
    for _ in range(2):
        schema.install()
        assert schema.baseline() == before
        assert [schema.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in TABLES] == [0, 0, 0]
    record_property('canonical_counts', json.dumps({t:len(rows) for t,rows in before.items()}))
    record_property('canonical_sha256', sha256(repr(before).encode()).hexdigest())


@pytest.mark.parametrize('change', [{'parent_mission_id': 'foreign'}, {'parent_work_id': 'unknown'},
                                    {'assignment_id': 'unknown'}, {'input_id': 'unknown'}])
def test_recorded_work_requires_exact_existing_parent_ownership(schema, change):
    x = seed(schema)
    if not schema.postgres:
        schema.conn.commit()
    schema.install()
    values = {k: x[v] if v in x else str(uuid4()) for k,v in change.items()}
    with schema.rejected('foreign'):
        schema.insert(TABLES[0], work_values(x, **values))


@pytest.mark.parametrize('change', [{'approved_queries': 'not-json'}, {'requested_queries': '[]'},
                                    {'approved_sources': '["youtube","youtube"]'},
                                    {'requested_sources': '["invalid source"]'},
                                    {'research_epoch': 0}, {'assignment_version': 0}])
def test_work_rejects_ambiguous_scope_or_versions(schema, change):
    x = seed(schema)
    if not schema.postgres:
        schema.conn.commit()
    schema.install()
    with schema.rejected('check'):
        schema.insert(TABLES[0], work_values(x, **change))


def test_admitted_child_is_existing_distinct_and_same_research(schema):
    x = prepared(schema)
    for child, kind in ((x['parent'], 'check'), (x['foreign'], 'check'), (str(uuid4()), 'foreign')):
        with schema.rejected(kind):
            schema.insert(TABLES[1], relation_values(x, child_mission_id=child))
    admit(schema, x)
    assert schema.execute('SELECT status FROM research_missions WHERE id=%s', (x['parent'],)).fetchone() == ('COMPLETED',)
    with schema.rejected('check'):
        schema.execute('UPDATE research_missions SET workspace_id=%s WHERE id=%s', (x['other_workspace'], x['child']))


def alternate(db, x):
    other = dict(x, child=str(uuid4()), work=str(uuid4()), follow_up=str(uuid4()), reservation=str(uuid4()))
    db.insert('research_missions', dict(id=other['child'], title='other child',
              keywords=['schema'] if db.postgres else '["schema"]', workspace_id=x['workspace'],
              created_at='2026-10-08T00:00:00+00:00'))
    db.insert('research_work_items', dict(work_id=other['work'], mission_id=x['parent'],
              assignment_id=x['assignment'], input_id=x['inputs'], question='bounded', expertise='Synthesis',
              epoch=1, state='ASSIGNED', version=1, ownership_fence='other-fence'))
    db.insert(TABLES[0], work_values(other))
    if not db.postgres:
        db.conn.commit()
    return other


@pytest.mark.parametrize('identity', ['follow_up_id','child_mission_id','work_id','reservation_id','idempotency_key'])
def test_each_admission_uniqueness_constraint_has_no_other_collision(schema, identity):
    x = prepared(schema)
    admit(schema, x)
    other = alternate(schema, x)
    values = relation_values(other, idempotency_key='different-key')
    values[identity] = relation_values(x)[identity]
    with schema.rejected('unique'):
        schema.insert(TABLES[1], values)
    assert schema.execute('SELECT count(*) FROM mission_follow_ups').fetchone() == (1,)


def test_relationship_and_recorded_scope_are_immutable(schema):
    x = prepared(schema)
    admit(schema, x)
    with schema.rejected('check'):
        schema.execute('DELETE FROM mission_follow_ups')
    with schema.rejected('check'):
        schema.execute("UPDATE mission_follow_up_work SET requested_queries='[\"changed\"]'")


def test_relation_cannot_commit_without_its_exact_reservation(schema):
    x = prepared(schema)
    schema.execute('BEGIN')
    schema.insert(TABLES[1], relation_values(x))
    error = psycopg.errors.ForeignKeyViolation if schema.postgres else sqlite3.IntegrityError
    with pytest.raises(error):
        schema.execute('COMMIT')
    schema.execute('ROLLBACK')
    assert schema.execute('SELECT count(*) FROM mission_follow_ups').fetchone() == (0,)


def test_unresolved_zero_retains_allocation_and_known_usage_cannot_decrease(schema):
    x = prepared(schema)
    admit(schema, x)
    schema.execute("UPDATE mission_follow_up_reservations SET state='UNRESOLVED',measured_quota=0,version=2")
    assert schema.execute('SELECT reserved_quota,reserved_cost,measured_quota,measured_cost FROM mission_follow_up_reservations').fetchone() == (4, 6, 0, None)
    with schema.rejected('check'):
        schema.execute("UPDATE mission_follow_up_reservations SET state='SETTLED',measurement_receipt_id=%s,version=3", (str(uuid4()),))
    schema.execute("UPDATE mission_follow_up_reservations SET measured_quota=2,measured_cost=8,version=3")
    with schema.rejected('check'):
        schema.execute('UPDATE mission_follow_up_reservations SET measured_cost=7,version=4')
    schema.execute("UPDATE mission_follow_up_reservations SET state='SETTLED',measurement_receipt_id=%s,version=4", (str(uuid4()),))
    for statement in ('UPDATE mission_follow_up_reservations SET measured_cost=9,version=5',
                      'UPDATE mission_follow_up_reservations SET reserved_cost=0,version=5',
                      'DELETE FROM mission_follow_up_reservations'):
        with schema.rejected('check'):
            schema.execute(statement)


@pytest.mark.parametrize('change', [{'requested_queries':'["unapproved"]'},
                                     {'requested_sources':'["threads"]'}])
def test_recorded_proposal_does_not_admit_widened_query_or_source(schema, change):
    x = prepared(schema, **change)
    with schema.rejected('check'):
        schema.insert(TABLES[1], relation_values(x))


@pytest.mark.parametrize('table,key', [(TABLES[0],'work_id'), (TABLES[1],'follow_up_id'),
                                     (TABLES[2],'reservation_id')])
def test_primary_identity_cannot_be_null_even_for_direct_sql(schema, table, key):
    x = prepared(schema) if table != TABLES[0] else seed(schema)
    if table == TABLES[0]:
        if not schema.postgres:
            schema.conn.commit()
        schema.install()
    values = {TABLES[0]:work_values, TABLES[1]:relation_values, TABLES[2]:reserve_values}[table](x)
    values[key] = None
    with schema.rejected('notnull'):
        schema.insert(table, values)


def test_raw_query_length_cannot_escape_bound_with_padding(schema):
    x = seed(schema)
    if not schema.postgres:
        schema.conn.commit()
    schema.install()
    with schema.rejected('check'):
        schema.insert(TABLES[0], work_values(x, approved_queries=json.dumps([' ' + 'q'*512 + ' '])))
    schema.insert(TABLES[0], work_values(x, approved_queries=json.dumps(['q'*512])))
    assert schema.execute('SELECT count(*) FROM mission_follow_up_work').fetchone() == (1,)


def test_populated_reapply_preserves_links_usage_and_canonical_evidence(schema):
    x = prepared(schema)
    admit(schema, x)
    before = schema.baseline()
    links = {t:schema.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall() for t in TABLES}
    schema.install()
    assert schema.baseline() == before
    assert {t:schema.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall() for t in TABLES} == links


def test_postgres_client_revokes_close_select_and_truncate_after_public_grant(schema):
    if not schema.postgres:
        pytest.skip('PostgreSQL role boundary only.')
    prepared(schema)
    for table in TABLES:
        schema.execute(f'GRANT ALL ON {table} TO PUBLIC')
        assert schema.execute('SELECT has_table_privilege(%s,%s,%s)', ('anon',table,'TRUNCATE')).fetchone() == (True,)
    schema.install()
    with psycopg.connect(schema.admin_dsn, autocommit=True) as client:
        client.execute('SET ROLE anon')
        for table in TABLES:
            for operation in ('SELECT * FROM ', 'TRUNCATE '):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    client.execute(operation + table)
    for role in ('anon','authenticated'):
        for table in TABLES:
            for privilege in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'):
                assert schema.execute('SELECT has_table_privilege(%s,%s,%s)', (role,table,privilege)).fetchone() == (False,)
