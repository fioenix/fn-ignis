"""Synthetic-store contracts for explicit taxonomy retirement."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from ignis.infrastructure.migration import taxonomy_retirement as retirement

CODES = ('auto', 'beauty', 'ecommerce', 'education', 'entertainment', 'fashion', 'finance',
         'food', 'health', 'news', 'realestate', 'sports', 'tech', 'travel')
PROTECTED = ('sources', 'observations', 'mission_evidence', 'trend_signals', 'signal_metrics',
             'research_missions', 'mission_manifests', 'market_brief_revisions',
             'mission_run_journals', 'mission_probe_outcomes', 'mission_evidence_qualifications',
             'mission_claims', 'mission_claim_evidence', 'market_lexicons')


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE topic_clusters (id TEXT PRIMARY KEY, category TEXT, score REAL, updated TEXT, extra BLOB)')
        conn.execute('CREATE TABLE industry_taxonomies (id TEXT PRIMARY KEY, keywords TEXT)')
        conn.execute("INSERT INTO industry_taxonomies VALUES ('edited', 'not the historical corpus')")
        for table in PROTECTED:
            conn.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, payload TEXT)')
            conn.execute(f'INSERT INTO {table} VALUES (?, ?)', ('secret-row-id', 'private evidence'))
        for index, category in enumerate([*CODES, 'outside', None, '', 'Beauty', ' beauty ']):
            conn.execute('INSERT INTO topic_clusters VALUES (?, ?, ?, ?, ?)',
                         (str(index), category, 1.5, '2026-01-01', b'unchanged'))
    return path


def projection(path):
    with sqlite3.connect(path) as conn:
        return retirement.project(conn, 'sqlite', 'fixture-store')


def cli():
    spec = importlib.util.spec_from_file_location('retire_cli', Path(__file__).resolve().parents[2] / 'scripts/retire_industry_taxonomy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_projection_counts_identity_schema_and_preservation(legacy):
    before_bytes = legacy.read_bytes()
    result = projection(legacy)
    assert result.get('reset_total') == 14
    assert result['reset_counts'] == dict.fromkeys(CODES, 1)
    assert result['cluster_count'] == 19
    assert set(result['protected_sets']) == set(PROTECTED)
    assert result['clusters_before_digest'] != result['clusters_expected_after_digest']
    assert result['schema_before_digest'] != result['schema_expected_after_digest']
    assert 'SOURCE_CODE_COLLISION' in result['limitations']
    assert projection(legacy) == result
    assert legacy.read_bytes() == before_bytes
    serialized = json.dumps(result)
    assert 'private evidence' not in serialized and 'secret-row-id' not in serialized


def test_projection_detects_same_count_substitution_and_every_field(legacy):
    before = projection(legacy)
    with sqlite3.connect(legacy) as conn:
        conn.execute("UPDATE topic_clusters SET id = 'replacement' WHERE id = '0'")
    after = projection(legacy)
    assert before.get('target_digest') != after.get('target_digest')
    assert before['reset_counts'] == after['reset_counts']
    assert before['cluster_noncategory_digest'] != after['cluster_noncategory_digest']
    with sqlite3.connect(legacy) as conn:
        conn.execute("UPDATE topic_clusters SET extra = X'00' WHERE id = 'replacement'")
        conn.execute("UPDATE mission_claim_evidence SET payload = 'changed'")
    changed = projection(legacy)
    assert changed['cluster_noncategory_digest'] != after['cluster_noncategory_digest']
    assert changed['protected_sets'] != after['protected_sets']


def test_projection_reordered_rows_and_absent_table(legacy):
    before = projection(legacy)
    with sqlite3.connect(legacy) as conn:
        rows = conn.execute('SELECT * FROM topic_clusters ORDER BY id DESC').fetchall()
        conn.execute('DELETE FROM topic_clusters')
        conn.executemany('INSERT INTO topic_clusters VALUES (?, ?, ?, ?, ?)', rows)
    assert projection(legacy) == before
    with sqlite3.connect(legacy) as conn:
        conn.execute('DROP TABLE industry_taxonomies')
    after = projection(legacy)
    assert after.get('state') == 'ALREADY_RETIRED'
    assert after['reset_counts'] == dict.fromkeys(CODES, 0)
    assert after['matching_code_counts'] == dict.fromkeys(CODES, 1)
    assert after['clusters_before_digest'] == after['clusters_expected_after_digest']


def test_cli_project_is_read_only_sanitized_stdout(legacy, capsys, monkeypatch):
    module = cli()
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    monkeypatch.setattr(SqliteTrendRepository, '_create_tables_and_seed', lambda self: pytest.fail('bootstrap forbidden'))
    before = legacy.read_bytes()
    files = sorted(legacy.parent.iterdir())
    assert module.main(['project', '--sqlite', str(legacy)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result.get('reset_total') == 14
    assert legacy.read_bytes() == before
    assert sorted(legacy.parent.iterdir()) == files
    assert 'private evidence' not in json.dumps(result)


@pytest.mark.parametrize('args', [[], ['project'], ['project', '--sqlite', '/missing'],
    ['project', '--sqlite', 'a', '--postgres-service', 'b'],
    ['verify', '--sqlite', 'a'], ['project', '--postgres-service', 'password=secret']])
def test_cli_invalid_input_has_stable_sanitized_exit(args, capsys):
    assert cli().main(args) == 2
    output = capsys.readouterr()
    assert json.loads(output.out)['reason'] == 'INVALID_INPUT'
    assert 'secret' not in output.out + output.err


def test_unknown_schema_refused(tmp_path, capsys):
    path = tmp_path / 'empty.sqlite3'
    sqlite3.connect(path).close()
    assert cli().main(['project', '--sqlite', str(path)]) == 2
    assert json.loads(capsys.readouterr().out)['reason'] == 'UNSUPPORTED_STORE'


def test_verify_compares_actual_poststate_and_refuses_tampering(legacy, capsys):
    module = cli()
    assert module.main(['project', '--sqlite', str(legacy)]) == 0
    baseline = json.loads(capsys.readouterr().out)
    receipt = legacy.parent / 'projection.json'
    receipt.write_text(json.dumps(baseline))
    assert module.main(['verify', '--sqlite', str(legacy), '--baseline', str(receipt)]) == 1
    assert json.loads(capsys.readouterr().out)['reason'] == 'POST_STATE_MISMATCH'
    with sqlite3.connect(legacy) as conn:
        conn.execute('UPDATE topic_clusters SET category = ? WHERE category IN (' + ','.join('?' for _ in CODES) + ')',
                     ('unclassified', *CODES))
        conn.execute('DROP TABLE industry_taxonomies')
    assert module.main(['verify', '--sqlite', str(legacy), '--baseline', str(receipt)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'VERIFIED'
    with sqlite3.connect(legacy) as conn:
        conn.execute("UPDATE mission_claims SET payload = 'tampered'")
    assert module.main(['verify', '--sqlite', str(legacy), '--baseline', str(receipt)]) == 1
    capsys.readouterr()
    baseline['reset_total'] = 0
    receipt.write_text(json.dumps(baseline))
    assert module.main(['verify', '--sqlite', str(legacy), '--baseline', str(receipt)]) == 1
    assert json.loads(capsys.readouterr().out)['reason'] == 'INVALID_BASELINE'


def test_projection_does_not_read_credentials_and_covers_zero_counts(legacy):
    with sqlite3.connect(legacy) as conn:
        conn.execute("DELETE FROM topic_clusters WHERE category = 'tech'")
        def authorize(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ and table in ('platform_credentials', 'mission_author_keys'):
                pytest.fail('secret table read')
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
        result = retirement.project(conn, 'sqlite', 'fixture-store')
    assert result['reset_counts']['tech'] == 0
    assert len(result['reset_counts']) == 14
    assert result['reset_total'] == 13


@pytest.mark.parametrize('value', [float('nan'), float('inf'), object()])
def test_projection_refuses_unsupported_scalars(value):
    with pytest.raises(retirement.RetirementError, match='UNSUPPORTED_VALUE'):
        retirement.digest(value)


@pytest.mark.asyncio
async def test_fresh_and_repeated_bootstrap_never_creates_taxonomy(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    path = tmp_path / 'fresh.sqlite3'
    for _ in range(2):
        repo = SqliteTrendRepository(str(path))
        await repo._ensure_schema()
        await repo.close()
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'industry_taxonomies'").fetchall() == []


def apply_fixture(path, baseline, factory=sqlite3.Connection):
    with sqlite3.connect(path, factory=factory) as conn:
        return retirement.apply(conn, 'sqlite', 'fixture-store', baseline)


def test_apply_resets_exact_codes_preserves_all_fields_and_retries(legacy):
    baseline = projection(legacy)
    result = apply_fixture(legacy, baseline)
    assert result['changed_count'] == 14
    with sqlite3.connect(legacy) as conn:
        assert retirement.verify(conn, 'sqlite', 'fixture-store', baseline)['status'] == 'VERIFIED'
        assert conn.execute("SELECT category FROM topic_clusters WHERE id = '1'").fetchone() == ('unclassified',)
    assert apply_fixture(legacy, baseline)['changed_count'] == 0
    with sqlite3.connect(legacy) as conn:
        conn.execute("INSERT INTO topic_clusters VALUES ('new-source', 'beauty', 99, 'new', X'00')")
    with pytest.raises(retirement.RetirementError, match='POST_STATE_MISMATCH'):
        apply_fixture(legacy, baseline)
    fresh = projection(legacy)
    assert fresh['state'] == 'ALREADY_RETIRED'
    assert apply_fixture(legacy, fresh)['changed_count'] == 0
    with sqlite3.connect(legacy) as conn:
        assert conn.execute("SELECT category FROM topic_clusters WHERE id = 'new-source'").fetchone() == ('beauty',)


@pytest.mark.parametrize('mutation', [
    "UPDATE topic_clusters SET id = 'substitute' WHERE id = '0'",
    "UPDATE topic_clusters SET updated = 'changed' WHERE id = '0'",
    "UPDATE topic_clusters SET score = 123 WHERE id = '0'",
    "UPDATE observations SET payload = 'changed'",
    "UPDATE mission_claim_evidence SET payload = 'changed'",
    "UPDATE mission_manifests SET payload = 'changed'",
])
def test_apply_rejects_stale_baseline_before_writing(legacy, mutation):
    baseline = projection(legacy)
    with sqlite3.connect(legacy) as conn:
        conn.execute(mutation)
    before = legacy.read_bytes()
    with pytest.raises(retirement.RetirementError, match='BASELINE_DRIFT'):
        apply_fixture(legacy, baseline)
    assert legacy.read_bytes() == before


@pytest.mark.parametrize('stage', ['after_update', 'after_drop'])
def test_apply_rolls_back_both_mutation_boundaries(legacy, stage):
    class Failure(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            if statement.startswith('DROP TABLE') and stage == 'after_update':
                raise RuntimeError('injected failure')
            result = super().execute(statement, *args, **kwargs)
            if statement.startswith('DROP TABLE') and stage == 'after_drop':
                raise RuntimeError('injected failure')
            return result
    baseline = projection(legacy)
    with pytest.raises(retirement.RetirementError, match='APPLY_FAILED'):
        apply_fixture(legacy, baseline, Failure)
    assert projection(legacy) == baseline


def test_apply_empty_target_drops_table_and_absent_marker_never_resets(legacy):
    with sqlite3.connect(legacy) as conn:
        conn.execute("UPDATE topic_clusters SET category = 'source label'")
    baseline = projection(legacy)
    assert baseline['reset_total'] == 0
    assert apply_fixture(legacy, baseline)['changed_count'] == 0
    assert projection(legacy)['state'] == 'ALREADY_RETIRED'


def test_apply_unknown_dependent_object_rolls_back(legacy):
    with sqlite3.connect(legacy) as conn:
        conn.execute('CREATE VIEW unrelated_view AS SELECT * FROM industry_taxonomies')
    baseline = projection(legacy)
    with pytest.raises(retirement.RetirementError):
        apply_fixture(legacy, baseline)
    assert projection(legacy) == baseline


def test_apply_missing_or_wrong_store_baseline_refuses(legacy):
    baseline = projection(legacy)
    for bad in (None, {}, {**baseline, 'store_identity': 'another-store'}):
        with pytest.raises(retirement.RetirementError, match='INVALID_BASELINE'):
            apply_fixture(legacy, bad)
    assert projection(legacy) == baseline


def test_cli_apply_requires_published_receipt_and_verifies_commit(legacy, capsys):
    module = cli()
    assert module.main(['project', '--sqlite', str(legacy)]) == 0
    receipt = legacy.parent / 'projection.json'
    receipt.write_text(capsys.readouterr().out)
    assert module.main(['apply', '--sqlite', str(legacy), '--baseline', str(receipt)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['changed_count'] == 14 and result['committed'] is True
    assert module.main(['verify', '--sqlite', str(legacy), '--baseline', str(receipt)]) == 0
    capsys.readouterr()
    assert module.main(['apply', '--sqlite', str(legacy), '--baseline', str(receipt)]) == 0
    assert json.loads(capsys.readouterr().out)['changed_count'] == 0



def test_numbered_migration_uses_exact_frozen_identifiers_and_empty_digest():
    import re
    text = (Path(__file__).resolve().parents[2] / 'sql' / '039_remove_seeded_taxonomy.sql').read_text()
    codes = re.search(r'former_codes CONSTANT text\[\] := ARRAY\[(.*?)\];', text, re.S).group(1)
    assert tuple(re.findall(r"'([^']+)'", codes)) == retirement.FORMER_CODES
    assert retirement._RowsDigest('targets', ['id', 'category']).finish()['digest'] in text



def test_postgres_service_cli_selects_read_only_backend_without_config(capsys, monkeypatch):
    import psycopg
    module = cli()
    statements = []
    class Connection:
        def execute(self, statement):
            statements.append(statement)
        def close(self):
            statements.append('closed')
    def connect(**kwargs):
        assert kwargs == {'service': 'synthetic-service'}
        return Connection()
    monkeypatch.setattr(psycopg, 'connect', connect)
    monkeypatch.setattr(retirement, 'postgres_identity', lambda conn: 'synthetic-identity')
    def project(conn, backend, identity):
        assert backend == 'postgres' and identity == 'synthetic-identity'
        assert statements == ['SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY']
        return {'backend': backend}
    monkeypatch.setattr(retirement, 'project', project)
    assert module.main(['project', '--postgres-service', 'synthetic-service']) == 0
    assert json.loads(capsys.readouterr().out) == {'backend': 'postgres'}
    assert statements[-1] == 'closed'


@pytest.mark.parametrize('flag', ['--sqlite', '--postgres-service'])
def test_empty_backend_never_falls_through_to_default_connection(flag, capsys, monkeypatch):
    import psycopg
    calls = []
    def forbidden(**kwargs):
        calls.append(True)
        raise RuntimeError('synthetic connection guard')
    monkeypatch.setattr(psycopg, 'connect', forbidden)
    assert cli().main(['project', flag, '']) == 2
    assert json.loads(capsys.readouterr().out)['reason'] == 'INVALID_INPUT'
    assert calls == []


@pytest.mark.parametrize('stage', ['after_update', 'after_drop'])
def test_interrupted_apply_rolls_back_before_returning_control(legacy, stage):
    class Interrupted(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            if statement.startswith('DROP TABLE') and stage == 'after_update':
                raise KeyboardInterrupt()
            result = super().execute(statement, *args, **kwargs)
            if statement.startswith('DROP TABLE') and stage == 'after_drop':
                raise KeyboardInterrupt()
            return result
    baseline = projection(legacy)
    connection = sqlite3.connect(legacy, factory=Interrupted)
    try:
        with pytest.raises(KeyboardInterrupt):
            retirement.apply(connection, 'sqlite', 'fixture-store', baseline)
        assert not connection.in_transaction, 'An interrupted apply must release its transaction'
        assert retirement.project(connection, 'sqlite', 'fixture-store') == baseline
    finally:
        connection.close()



def test_protected_table_without_primary_key_has_stable_complete_digest(legacy):
    rows = [(None, 'null key'), ('same', 'second'), ('same', 'first'),
            ('same', 'first')]
    with sqlite3.connect(legacy) as conn:
        conn.execute('DROP TABLE trend_signals')
        conn.execute('CREATE TABLE trend_signals (id TEXT, payload TEXT)')
        conn.executemany('INSERT INTO trend_signals VALUES (?, ?)', rows)
    baseline = projection(legacy)
    assert baseline['protected_sets']['trend_signals']['count'] == 4
    with sqlite3.connect(legacy) as conn:
        conn.execute('DELETE FROM trend_signals')
        conn.executemany('INSERT INTO trend_signals VALUES (?, ?)', reversed(rows))
    assert projection(legacy) == baseline
    assert apply_fixture(legacy, baseline)['changed_count'] == 14
    with sqlite3.connect(legacy) as conn:
        assert retirement.verify(conn, 'sqlite', 'fixture-store', baseline)['status'] == 'VERIFIED'
        conn.execute("UPDATE trend_signals SET payload='changed' WHERE payload='second'")
    with sqlite3.connect(legacy) as conn:
        with pytest.raises(retirement.RetirementError, match='POST_STATE_MISMATCH'):
            retirement.verify(conn, 'sqlite', 'fixture-store', baseline)


def test_topic_clusters_still_requires_a_primary_key(legacy):
    with sqlite3.connect(legacy) as conn:
        conn.execute('ALTER TABLE topic_clusters RENAME TO old_clusters')
        conn.execute('CREATE TABLE topic_clusters AS SELECT * FROM old_clusters')
        conn.execute('DROP TABLE old_clusters')
    with pytest.raises(retirement.RetirementError, match='UNSUPPORTED_STORE'):
        projection(legacy)
