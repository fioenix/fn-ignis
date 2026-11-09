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
