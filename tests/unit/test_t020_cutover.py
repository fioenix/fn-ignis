"""What the cutover orchestrator must refuse.

The three migration scripts are covered by their own modules. What is only true of the
orchestrator is that it turns two things the runbook asks a reader to notice into things a
process fails on: a plan that does not match the baseline, and a DSN that goes through a pooler.
`backfill_observations.py --dry-run` exits 0 in both a matching and a short plan, so a test that
merely ran the dry run would pass on either.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import t020_cutover  # noqa: E402
from t020_cutover import (  # noqa: E402
    COUNT_PAIRS,
    Unrunnable,
    compare_counts,
    dsn_host,
    EXACT_DOUBLE,
    double_survives,
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


def test_a_connection_is_judged_by_the_double_it_returns():
    """Not by the host's name, and not by a session parameter read back.

    The name test was wrong twice over: the pooler is the only way in from a network without
    IPv6, and all three migration scripts already set extra_float_digits = 3 themselves.
    Reading that parameter back was wrong too -- through pgbouncer in transaction mode with an
    idle pool the same server connection is reused and the setting appears to hold, so the
    check passed on exactly the configuration it existed to catch. What the digest needs is
    the number arriving intact, so that is what is measured.
    """
    assert double_survives(EXACT_DOUBLE)
    assert not double_survives("262600000.0")
    assert not double_survives("")


def test_a_pooler_is_not_refused_for_its_name(tmp_path):
    """A pooler host gets no special treatment; it fails or passes on the ordinary checks.

    Asserted as "the refusal is the resolution one" rather than "the word pooler is absent",
    because the word is in the hostname under test and that assertion passed for the wrong
    reason.
    """
    with pytest.raises(Unrunnable) as refusal:
        preflight("postgresql://u:p@pooler.no-such-host-fnignis.supabase.com:5432/db", tmp_path)
    assert "does not resolve to an address" in str(refusal.value)


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


# --- the child processes have to be pointed at the DSN this run chose --------------------------

DB_A = "postgresql://postgres:a@db-a.example.com:5432/postgres"
DB_B = "postgresql://postgres@db-b.example.com:5432/postgres"


def test_a_passwordless_dsn_still_overrides_an_inherited_database_url(monkeypatch):
    """The three migration scripts default their DSN from DATABASE_URL.

    A run whose chosen DSN carries no password used to be handed back with the environment
    untouched, so every child inherited whatever DATABASE_URL the operator's shell had. Preflight
    would measure one database and the audit, the backfill and the verifier would read another.
    """
    monkeypatch.setenv("DATABASE_URL", DB_A)
    safe, environment = without_password(DB_B)

    assert safe == DB_B
    assert environment["DATABASE_URL"] == DB_B


def test_an_inherited_password_does_not_survive_a_passwordless_dsn(monkeypatch):
    """PGPASSWORD left in the environment authenticates a connection this run did not describe."""
    monkeypatch.setenv("PGPASSWORD", "inherited")
    _, environment = without_password(DB_B)

    assert "PGPASSWORD" not in environment


def test_a_percent_encoded_password_reaches_libpq_decoded():
    """A URI escapes reserved characters; PGPASSWORD is a literal.

    Handing libpq the escaped text authenticates with a password nobody set, and the failure
    reads as a rotation that never happened.
    """
    dsn = "postgresql://postgres:hun%40ter%232@db.example.com:5432/postgres"
    safe, environment = without_password(dsn)

    assert environment["PGPASSWORD"] == "hun@ter#2"
    assert "hun%40ter" not in safe
    assert safe == "postgresql://postgres@db.example.com:5432/postgres"


def test_a_percent_encoded_username_is_not_mangled_on_the_way_through():
    """Negative control for the decode above: the user name keeps its own escaping."""
    dsn = "postgresql://po%40st:pw@db.example.com:5432/postgres"
    safe, _ = without_password(dsn)

    assert safe == "postgresql://po%40st@db.example.com:5432/postgres"


BALANCED_BASELINE = {
    "schema_version": "016",
    "balanced": True,
    "digests": {
        "sources": "s" * 64,
        "observations": "o" * 64,
        "mission_associations": "m" * 64,
        "cluster_memberships": "c" * 64,
        "member_counts": dict(BASELINE),
    },
}


def _capture_child_environments(monkeypatch, run_dir):
    """Replace the runner with one that records the environment each child would have got."""
    seen = []
    (run_dir / "source-observation-baseline.json").write_text(json.dumps(BALANCED_BASELINE))
    (run_dir / "post-migration-verification.json").write_text(
        json.dumps({"verified": True, "comparisons": []})
    )

    def fake_run(command, capture=False, echo=False, timeout=None, env=None):
        seen.append(env or {})
        return t020_cutover.Ran(0, "", "")

    monkeypatch.setattr(t020_cutover, "run", fake_run)
    return seen


@pytest.mark.parametrize("step", ["baseline", "apply", "verify"])
def test_every_child_is_sent_at_the_dsn_this_run_chose(monkeypatch, tmp_path, step):
    """The audit, the backfill and the verifier, each against an inherited DATABASE_URL.

    DB_B is the DSN this run chose and carries no password, which is the case that used to hand
    the environment back untouched.
    """
    monkeypatch.setenv("DATABASE_URL", DB_A)
    monkeypatch.setattr(t020_cutover, "confirm", lambda *a, **k: None)
    seen = _capture_child_environments(monkeypatch, tmp_path)
    journal = t020_cutover.Journal(tmp_path / "journal.json", "db-b.example.com")

    if step == "baseline":
        t020_cutover.step_baseline(DB_B, tmp_path, journal, _measurement())
    elif step == "apply":
        t020_cutover.step_apply(DB_B, journal)
    else:
        t020_cutover.step_verify(DB_B, tmp_path, journal)

    assert seen, "the step ran no child at all"
    assert [environment.get("DATABASE_URL") for environment in seen] == [DB_B] * len(seen)


# --- the corpus has to be measured standing still, not declared standing still -----------------

CANONICAL = tuple(audit_key for _, audit_key in COUNT_PAIRS)


def _measurement(**overrides):
    """One legacy-projection measurement: four digests and four member counts."""
    digests = {name: name[0] * 64 for name in CANONICAL}
    counts = dict(BASELINE)
    for name, value in overrides.items():
        if isinstance(value, int):
            counts[name] = value
        else:
            digests[name] = value
    return {"digests": digests, "member_counts": counts}


def test_a_corpus_that_did_not_move_reports_no_drift():
    assert t020_cutover.corpus_drift(_measurement(), _measurement()) == []


@pytest.mark.parametrize("name", CANONICAL)
def test_a_member_count_that_moved_is_named(name):
    drift = t020_cutover.corpus_drift(_measurement(), _measurement(**{name: BASELINE[name] + 1}))
    assert len(drift) == 1
    assert drift[0].startswith(f"{name}:")


@pytest.mark.parametrize("name", CANONICAL)
def test_the_same_count_with_a_different_digest_is_still_drift(name):
    """An update in place moves no count.

    A pass that rewrites a row rather than adding one leaves all four member counts exactly where
    they were, so a gate that compares counts alone reads a changed corpus as an unchanged one --
    and the snapshot in hand no longer restores what is about to be migrated.
    """
    drift = t020_cutover.corpus_drift(_measurement(), _measurement(**{name: "z" * 64}))
    assert len(drift) == 1
    assert drift[0].startswith(f"{name}:")
    assert "digest" in drift[0]


ARCHIVE_LISTING = "; Archive created at 2026-09-20\n250; 1259 16384 TABLE public trend_signals postgres\n"


IDENTITY = {"database": "postgres", "database_oid": "5", "cluster_fingerprint": "f" * 32}


def _orchestrator_harness(monkeypatch, tmp_path, measurements, baseline_digests=None, identity=None):
    """Run main() with everything that needs a database replaced by a measurement it hands back.

    Only the network is stubbed. Every gate, every comparison and the order the steps run in are
    the real ones, which is the part under test.
    """
    applied = []
    remaining = list(measurements)

    monkeypatch.setattr(
        t020_cutover,
        "preflight",
        lambda dsn, run_dir: {
            "psql": Path("/usr/bin/psql"),
            "pg_dump": Path("/usr/bin/pg_dump"),
            "pg_restore": Path("/usr/bin/pg_restore"),
            "host": "db-b.example.com:5432",
            "database": "postgres",
            "user": "postgres",
            "server_version": "16.4",
            "pg_dump_major": 16,
            "identity": dict(identity or IDENTITY),
        },
    )
    monkeypatch.setattr(t020_cutover, "confirm", lambda *a, **k: None)
    monkeypatch.setattr(t020_cutover, "psql_value", lambda *a, **k: t020_cutover.Ran(0, "", ""))
    monkeypatch.setattr(t020_cutover, "step_dry_run", lambda *a, **k: None)
    monkeypatch.setattr(t020_cutover, "step_apply", lambda *a, **k: applied.append(True))
    monkeypatch.setattr(t020_cutover, "legacy_digests", lambda dsn: remaining.pop(0))

    measured = baseline_digests if baseline_digests is not None else measurements[0]
    baseline_file = dict(
        BALANCED_BASELINE,
        digests=dict(measured["digests"], member_counts=measured["member_counts"]),
    )

    def fake_run(command, capture=False, echo=False, timeout=None, env=None):
        text = " ".join(str(part) for part in command)
        if "pg_dump" in text:
            Path(command[-1]).write_bytes(b"PGDMP fake archive")
            return t020_cutover.Ran(0, "", "")
        if "pg_restore" in text:
            return t020_cutover.Ran(0, ARCHIVE_LISTING, "")
        if "migration_reconciliation_audit" in text:
            (tmp_path / "source-observation-baseline.json").write_text(json.dumps(baseline_file))
            return t020_cutover.Ran(0, "", "")
        if "post_migration_verification" in text:
            (tmp_path / "post-migration-verification.json").write_text(
                json.dumps({"verified": True, "comparisons": []})
            )
            return t020_cutover.Ran(0, "", "")
        return t020_cutover.Ran(0, "", "")

    monkeypatch.setattr(t020_cutover, "run", fake_run)
    return applied


def test_a_still_corpus_runs_all_the_way_to_the_write(monkeypatch, tmp_path):
    """The negative control for every standstill test below: nothing moved, so nothing stops."""
    applied = _orchestrator_harness(monkeypatch, tmp_path, [_measurement()] * 3)
    code = t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"])
    assert code == 0
    assert applied == [True]


def test_a_write_between_the_quiesce_and_the_snapshot_stops_the_run(monkeypatch, tmp_path, capsys):
    """The typed QUIESCED is an operator's belief. This is the measurement."""
    applied = _orchestrator_harness(
        monkeypatch, tmp_path, [_measurement(), _measurement(observations=BASELINE["observations"] + 1), _measurement()]
    )
    code = t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"])
    assert code == 1
    assert applied == [], "nothing may be written once the snapshot no longer matches the corpus"
    # Which gate stopped it, not merely that something did: the later gate would otherwise
    # cover for this one having been removed.
    assert "while the snapshot was taken" in capsys.readouterr().out


def test_a_write_between_the_snapshot_and_the_apply_stops_before_the_write(monkeypatch, tmp_path, capsys):
    """The last measurement is taken immediately before step 6, and step 6 must not start.

    The snapshot is the only way back from an applied backfill. A row written after it was taken
    is a row the snapshot cannot restore, so the run has to end on the side of the gate where
    nothing has been written yet.
    """
    applied = _orchestrator_harness(
        monkeypatch, tmp_path, [_measurement(), _measurement(), _measurement(sources="z" * 64)]
    )
    code = t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"])
    assert code == 1
    assert applied == []
    assert "between the snapshot and the write" in capsys.readouterr().out


def test_assume_quiesced_does_not_stand_in_for_the_measurement(monkeypatch, tmp_path):
    """--assume-quiesced skips a question, not a gate.

    Every test above passes it, so the flag cannot be what makes them stop. This one states it
    directly: the corpus moves and the flag is given, and the run still refuses.
    """
    applied = _orchestrator_harness(
        monkeypatch, tmp_path, [_measurement(), _measurement(), _measurement(observations=1)]
    )
    code = t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"])
    assert code == 1
    assert applied == []


def test_the_baseline_the_verifier_will_use_is_bound_to_the_measured_corpus(monkeypatch, tmp_path):
    """Step 3's artifact is what step 7 compares against, so it has to describe the same corpus."""
    applied = _orchestrator_harness(
        monkeypatch,
        tmp_path,
        [_measurement()] * 3,
        baseline_digests=_measurement(observations="z" * 64),
    )
    code = t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"])
    assert code == 1
    assert applied == []


def test_the_snapshot_is_hashed_into_the_journal(monkeypatch, tmp_path):
    """A resumed run has to be able to tell that the file on disk is the file that was taken."""
    _orchestrator_harness(monkeypatch, tmp_path, [_measurement()] * 3)
    assert t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"]) == 0

    journal = json.loads(sorted(tmp_path.glob("t020-run-*.json"))[-1].read_text())
    snapshot = [entry for entry in journal["steps"] if entry["title"] == "snapshot" and entry["state"] == "done"][0]
    assert snapshot["sha256"] == t020_cutover.sha256_of(Path(snapshot["path"]))
    assert len(snapshot["sha256"]) == 64


# --- a resumed run has to be the same run, against the same database --------------------------


def _one_completed_run(monkeypatch, tmp_path):
    """A real run through step 7, leaving a real journal, snapshot and baseline behind."""
    _orchestrator_harness(monkeypatch, tmp_path, [_measurement()] * 3)
    assert t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"]) == 0


def _resume(monkeypatch, tmp_path, measurements=None, identity=None, argv=()):
    applied = _orchestrator_harness(
        monkeypatch, tmp_path, measurements or [_measurement()], identity=identity
    )
    code = t020_cutover.main(
        ["--dsn", DB_B, "--run-dir", str(tmp_path), "--start-at", "4", *argv]
    )
    return code, applied


def test_a_resume_that_matches_the_earlier_run_reaches_the_write(monkeypatch, tmp_path):
    """The negative control for every refusal below."""
    _one_completed_run(monkeypatch, tmp_path)
    code, applied = _resume(monkeypatch, tmp_path)
    assert code == 0
    assert applied == [True]


def test_a_resume_with_no_earlier_journal_is_refused(monkeypatch, tmp_path):
    """The baseline file having the right name was the whole of the old check."""
    (tmp_path / "source-observation-baseline.json").write_text(
        json.dumps(dict(BALANCED_BASELINE, digests=dict(_measurement()["digests"], member_counts=BASELINE)))
    )
    code, applied = _resume(monkeypatch, tmp_path)
    assert code == 2
    assert applied == []


def test_a_resume_against_another_database_is_refused(monkeypatch, tmp_path, capsys):
    """A baseline describes one corpus. Resuming against a second one migrates it blind."""
    _one_completed_run(monkeypatch, tmp_path)
    elsewhere = dict(IDENTITY, database_oid="9", cluster_fingerprint="e" * 32)

    code, applied = _resume(monkeypatch, tmp_path, identity=elsewhere)

    assert code == 2
    assert applied == []
    assert "database" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("artifact", ["snapshot", "baseline"])
def test_a_resume_whose_artifact_changed_since_the_earlier_run_is_refused(monkeypatch, tmp_path, artifact):
    """Both files are hashed into the journal, so a replacement is not merely a same-named file.

    The snapshot is the only way back from step 6 and the baseline is what step 7 judges the
    result against; a run that cannot prove either is the one it left behind has neither.
    """
    _one_completed_run(monkeypatch, tmp_path)
    journal = json.loads(sorted(tmp_path.glob("t020-run-*.json"))[-1].read_text())
    entry = [e for e in journal["steps"] if e["title"] == artifact and e["state"] == "done"][-1]
    path = Path(entry["path"] if artifact == "snapshot" else entry["baseline"])
    path.write_bytes(path.read_bytes() + b"  ")

    code, applied = _resume(monkeypatch, tmp_path)

    assert code == 2
    assert applied == []


def test_a_resume_whose_corpus_kept_its_counts_but_changed_its_payload_is_refused(monkeypatch, tmp_path):
    """The reference is the earlier run's measurement, so a write since then is still visible.

    Measuring afresh at resume time would make this gate agree with whatever it found.
    """
    _one_completed_run(monkeypatch, tmp_path)

    code, applied = _resume(monkeypatch, tmp_path, measurements=[_measurement(observations="z" * 64)])

    assert code == 1
    assert applied == []


# --- an interrupted write has an outcome nobody in this process can see ------------------------

REAL_STEP_APPLY = t020_cutover.step_apply


def _interrupt_journal_at(monkeypatch, step):
    """Make the journal raise where a signal would land, and keep the entries written so far."""
    original = t020_cutover.Journal.record

    def record(self, recorded_step, title, **evidence):
        if recorded_step == step:
            raise KeyboardInterrupt("signal 15")
        return original(self, recorded_step, title, **evidence)

    monkeypatch.setattr(t020_cutover.Journal, "record", record)


def test_an_interrupt_between_the_commit_and_the_journal_reports_an_unknown_outcome(
    monkeypatch, tmp_path, capsys
):
    """The child exits 0, having committed, and the signal lands before the entry is written.

    Claiming a rollback here is the one thing the message must not do: the transaction the claim
    rests on had already committed, and from this process the two outcomes look identical.
    """
    _orchestrator_harness(monkeypatch, tmp_path, [_measurement()] * 3)
    monkeypatch.setattr(t020_cutover, "step_apply", REAL_STEP_APPLY)
    _interrupt_journal_at(monkeypatch, 6)

    code = t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"])
    out = capsys.readouterr().out

    assert code == 2
    assert "rolled back" not in out or "unknown" in out.lower()
    assert "outcome is unknown" in out
    assert "ingress closed" in out
    assert "--start-at 5" in out


def test_an_interrupt_before_the_write_does_not_call_the_outcome_unknown(monkeypatch, tmp_path, capsys):
    """Negative control: the same handler, interrupted where nothing can have been written.

    Without this, a message that always said "unknown" would pass the test above.
    """
    _orchestrator_harness(monkeypatch, tmp_path, [_measurement()] * 3)
    _interrupt_journal_at(monkeypatch, 3)

    code = t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"])
    out = capsys.readouterr().out

    assert code == 2
    assert "outcome is unknown" not in out
    assert "nothing was written" in out


def test_the_journal_shows_the_write_started_and_never_finished(monkeypatch, tmp_path):
    """What the operator has to read afterwards, and the reason the message can say 'unknown'."""
    _orchestrator_harness(monkeypatch, tmp_path, [_measurement()] * 3)
    monkeypatch.setattr(t020_cutover, "step_apply", REAL_STEP_APPLY)
    _interrupt_journal_at(monkeypatch, 6)
    t020_cutover.main(["--dsn", DB_B, "--run-dir", str(tmp_path), "--assume-quiesced"])

    steps = json.loads(sorted(tmp_path.glob("t020-run-*.json"))[-1].read_text())["steps"]
    assert {"step": 6, "state": "started"}.items() <= [e for e in steps if e["step"] == 6][0].items()
    assert not [e for e in steps if e["step"] == 6 and e["state"] == "done"]
