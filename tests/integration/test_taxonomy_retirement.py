"""Real PostgreSQL retirement contracts; DSN fixtures skip when CI has no test server."""
from pathlib import Path

import psycopg
import pytest

from conftest import all_postgres_migrations, runtime_owner
from ignis.infrastructure.migration import taxonomy_retirement as retirement

pytestmark = pytest.mark.migration_chain
SQL = Path(__file__).resolve().parents[2] / 'sql'


@pytest.fixture
def legacy_pg(empty_postgres_dsn):
    with psycopg.connect(empty_postgres_dsn) as conn:
        conn.execute('CREATE TABLE topic_clusters (id TEXT PRIMARY KEY, category TEXT, score DOUBLE PRECISION, updated TIMESTAMPTZ, extra BYTEA)')
        conn.execute('CREATE TABLE industry_taxonomies (id TEXT PRIMARY KEY, keywords TEXT)')
        conn.execute("INSERT INTO industry_taxonomies VALUES ('edited', 'not the seed corpus')")
        for table in retirement.PROTECTED_SETS:
            conn.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, payload JSONB)')
            conn.execute(f'INSERT INTO {table} VALUES (%s, %s)', ('kept', '{"evidence":"unchanged"}'))
        for index, category in enumerate([*retirement.FORMER_CODES, 'outside', None, '', 'Beauty', ' beauty ']):
            conn.execute('INSERT INTO topic_clusters VALUES (%s, %s, 1.5, %s, %s)',
                         (str(index), category, '2026-01-01T00:00:00Z', b'unchanged'))
    return empty_postgres_dsn


def project(dsn):
    with psycopg.connect(dsn) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return retirement.project(conn, 'postgres', 'fixture-pg')


def apply(dsn, baseline):
    with psycopg.connect(dsn, application_name='taxonomy-retirement-test') as conn:
        return retirement.apply(conn, 'postgres', 'fixture-pg', baseline)


def test_exact_reset_preservation_retry_and_new_source_collision(legacy_pg):
    baseline = project(legacy_pg)
    assert baseline['reset_total'] == 14
    assert apply(legacy_pg, baseline)['changed_count'] == 14
    with psycopg.connect(legacy_pg) as conn:
        assert retirement.verify(conn, 'postgres', 'fixture-pg', baseline)['status'] == 'VERIFIED'
    assert apply(legacy_pg, baseline)['changed_count'] == 0
    with psycopg.connect(legacy_pg) as conn:
        conn.execute("INSERT INTO topic_clusters (id, category) VALUES ('new', 'beauty')")
    with pytest.raises(retirement.RetirementError, match='POST_STATE_MISMATCH'):
        apply(legacy_pg, baseline)
    assert apply(legacy_pg, project(legacy_pg))['changed_count'] == 0
    with psycopg.connect(legacy_pg) as conn:
        assert conn.execute("SELECT category FROM topic_clusters WHERE id='new'").fetchone() == ('beauty',)


@pytest.mark.parametrize('mutation', [
    "UPDATE topic_clusters SET id='substitute' WHERE id='0'",
    "UPDATE topic_clusters SET updated='2026-02-01T00:00:00Z' WHERE id='0'",
    "UPDATE topic_clusters SET score=123 WHERE id='0'",
    "UPDATE observations SET payload='{}'",
    "UPDATE mission_claim_evidence SET payload='{}'",
    "UPDATE mission_manifests SET payload='{}'",
])
def test_locked_recheck_refuses_content_drift(legacy_pg, mutation):
    baseline = project(legacy_pg)
    with psycopg.connect(legacy_pg) as conn:
        conn.execute(mutation)
    current = project(legacy_pg)
    with pytest.raises(retirement.RetirementError, match='BASELINE_DRIFT'):
        apply(legacy_pg, baseline)
    assert project(legacy_pg) == current


def test_direct_populated_sql_requires_projection_even_with_zero_matching_rows(legacy_pg):
    with psycopg.connect(legacy_pg) as conn:
        conn.execute("UPDATE topic_clusters SET category='custom source'")
    before = project(legacy_pg)
    with pytest.raises(psycopg.errors.RaiseException, match='TAXONOMY_PROJECTION_REQUIRED'):
        with psycopg.connect(legacy_pg) as conn:
            conn.execute((SQL / '039_remove_seeded_taxonomy.sql').read_text())
    assert project(legacy_pg) == before
    assert apply(legacy_pg, before)['changed_count'] == 0
    assert project(legacy_pg)['state'] == 'ALREADY_RETIRED'


@pytest.mark.parametrize('event', ['ddl_command_start', 'ddl_command_end'])
def test_failure_at_drop_boundaries_rolls_back_the_update_and_drop(legacy_pg, event):
    with psycopg.connect(legacy_pg) as conn:
        conn.execute("CREATE FUNCTION reject_retirement_drop() RETURNS event_trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected retirement failure'; END $$")
        conn.execute(f"CREATE EVENT TRIGGER reject_retirement ON {event} WHEN TAG IN ('DROP TABLE') EXECUTE FUNCTION reject_retirement_drop()")
    before = project(legacy_pg)
    with pytest.raises(retirement.RetirementError, match='APPLY_FAILED'):
        apply(legacy_pg, before)
    assert project(legacy_pg) == before
    with psycopg.connect(legacy_pg) as conn:
        conn.execute('DROP EVENT TRIGGER reject_retirement')


def test_unexpected_dependency_refuses_without_cascade(legacy_pg):
    with psycopg.connect(legacy_pg) as conn:
        conn.execute('CREATE VIEW unrelated_view AS SELECT * FROM industry_taxonomies')
    before = project(legacy_pg)
    with pytest.raises(retirement.RetirementError, match='APPLY_FAILED'):
        apply(legacy_pg, before)
    assert project(legacy_pg) == before


def test_lock_timeout_is_bounded_and_rolls_back(legacy_pg):
    baseline = project(legacy_pg)
    import time
    started = time.monotonic()
    with psycopg.connect(legacy_pg) as writer:
        writer.execute('LOCK TABLE topic_clusters IN ACCESS EXCLUSIVE MODE')
        with pytest.raises(retirement.RetirementError, match='APPLY_FAILED'):
            apply(legacy_pg, baseline)
    assert time.monotonic() - started < 10
    assert project(legacy_pg) == baseline


def test_non_superuser_owner_can_retire_without_extra_grants(legacy_pg):
    with runtime_owner(legacy_pg) as owner:
        baseline = project(owner)
        assert apply(owner, baseline)['changed_count'] == 14


@pytest.mark.parametrize('roles', [False, True])
def test_whole_chain_publishes_zero_projection_and_retires(request, roles):
    import json
    dsn = request.getfixturevalue("supabase_like_dsn" if roles else "empty_postgres_dsn")
    notices = []
    with psycopg.connect(dsn) as conn:
        conn.add_notice_handler(lambda notice: notices.append(notice.message_primary))
        for name in all_postgres_migrations():
            conn.execute((SQL / name).read_text())
        assert conn.execute("SELECT to_regclass('public.industry_taxonomies')").fetchone() == (None,)
    receipts = [json.loads(value) for value in notices if value.startswith('{') and '039_remove_seeded_taxonomy' in value]
    assert len(receipts) == 1
    assert receipts[0]['reset_counts'] == dict.fromkeys(retirement.FORMER_CODES, 0)
    assert receipts[0]['reset_total'] == 0
    assert receipts[0]['target_digest'] == retirement._RowsDigest('targets', ['id', 'category']).finish()['digest']


def test_baseline_is_recomputed_after_waiting_for_writer(legacy_pg):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import time
    baseline = project(legacy_pg)
    started = Event()
    def attempt():
        started.set()
        return apply(legacy_pg, baseline)
    with psycopg.connect(legacy_pg) as writer:
        writer.execute("UPDATE topic_clusters SET score=123 WHERE id='0'")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(attempt)
            assert started.wait(timeout=2)
            deadline = time.monotonic() + 3
            waiting = False
            while time.monotonic() < deadline:
                waiting = writer.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                    "AND application_name='taxonomy-retirement-test' AND wait_event_type='Lock')"
                ).fetchone()[0]
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting, 'The apply connection must wait for the writer before rechecking'
            writer.commit()
            with pytest.raises(retirement.RetirementError, match='BASELINE_DRIFT'):
                future.result(timeout=10)
    assert project(legacy_pg)['table_present'] is True
