"""What the cutover orchestrator must refuse.

The three migration scripts are covered by their own modules. What is only true of the
orchestrator is that it turns two things the runbook asks a reader to notice into things a
process fails on: a plan that does not match the baseline, and a DSN that goes through a pooler.
`backfill_observations.py --dry-run` exits 0 in both a matching and a short plan, so a test that
merely ran the dry run would pass on either.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from t020_cutover import (  # noqa: E402
    COUNT_PAIRS,
    Unrunnable,
    compare_counts,
    dsn_host,
    preflight,
    redact,
    without_password,
)

BASELINE = {
    "sources": 1924,
    "observations": 18597,
    "mission_associations": 1301,
    "cluster_memberships": 15754,
}
MATCHING_PLAN = {
    "sources": 1924,
    "observations": 18597,
    "mission_evidence": 1301,
    "cluster_memberships": 15754,
}


def test_a_matching_plan_reports_no_mismatch():
    assert compare_counts(MATCHING_PLAN, BASELINE) == []


@pytest.mark.parametrize("plan_key,audit_key", COUNT_PAIRS)
def test_each_of_the_four_sets_is_compared(plan_key, audit_key):
    """One short set has to be caught whichever set it is.

    Parametrised rather than written once because the earlier version of this gate compared the
    sets the two scripts happened to spell the same way, and mission_evidence against
    mission_associations is precisely the pair that differs.
    """
    short = dict(MATCHING_PLAN, **{plan_key: MATCHING_PLAN[plan_key] - 1})
    mismatches = compare_counts(short, BASELINE)
    assert len(mismatches) == 1
    assert mismatches[0].startswith(f"{audit_key}:")


def test_a_pooler_dsn_is_refused_before_anything_is_read(tmp_path):
    with pytest.raises(Unrunnable) as refusal:
        preflight("postgresql://u:p@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres", tmp_path)
    assert "pooler" in str(refusal.value)


def test_a_dsn_never_reaches_the_terminal_with_its_password():
    dsn = "postgresql://postgres:hunter2@db.example.com:5432/postgres"
    assert "hunter2" not in redact(dsn)
    assert dsn_host(dsn) == "db.example.com:5432"


def test_the_password_travels_in_the_environment_not_in_argv():
    """argv is world-readable.

    During a real run `ps` printed a full connection string, password included, to an
    unprivileged process on the same machine. Whatever else changes, the string handed to psql
    must not carry the password, and the three migration scripts must be given it the way they
    already accept it -- DATABASE_URL -- rather than on a command line.
    """
    dsn = "postgresql://postgres:hunter2@db.example.com:5432/postgres"
    safe, environment = without_password(dsn)

    assert "hunter2" not in safe
    assert safe == "postgresql://postgres@db.example.com:5432/postgres"
    assert environment["PGPASSWORD"] == "hunter2"
    assert environment["DATABASE_URL"] == dsn


def test_a_dsn_with_no_password_is_left_alone():
    dsn = "postgresql://postgres@db.example.com:5432/postgres"
    safe, _ = without_password(dsn)
    assert safe == dsn
