#!/usr/bin/env python
"""Run the T020 production cutover as a gated sequence, or stop at the first gate that fails.

The three migration scripts each answer one question well. What they do not do is refuse to let
the next step start, and one of them cannot: `backfill_observations.py --dry-run` exits 0 whether
the plan matches the baseline, disagrees with it, or finds no target schema at all. The gate that
the runbook places after the dry run therefore exists only in the reader's attention. Here it is
a comparison the process performs and fails on.

What this adds over running the commands by hand:

  measures the connection   the three migration scripts open their session with
                            SET extra_float_digits = 3, without which a double arrives rounded
                            and lands in the observation digest. Preflight sets it and reads it
                            back on a second statement, so a pooler that scopes a SET to one
                            transaction is refused for what it does rather than for its name.
  proves the snapshot       pg_dump exiting 0 is not a restorable file. pg_restore --list must
                            read the archive back and name objects in it.
  compares four counts      the dry-run plan against the baseline taken from the snapshot, by
                            value, before anything is written.
  one irreversible step     step 6 is the only step that writes, and it asks for a typed word.
  writes a journal          every step's command, exit code, timestamp and evidence, so closing
                            T020 in BACKLOG.md is a matter of quoting the file.

Steps 8 and 9 of the runbook -- start the new runtime, reopen ingress -- are deliberately not
automated. They depend on what the operator has running, and doing them early is one of the three
things the runbook forbids.

Usage:
    .venv/bin/python scripts/t020_cutover.py
    .venv/bin/python scripts/t020_cutover.py --start-at 5

The DSN comes from --dsn, else $PRODUCTION_DSN, else the direct-connection key in .env. A
session-mode pooler is fine; pg_dump cannot run through one, so pass --snapshot with a snapshot
taken another way.

Exit codes: 0 every step through verification passed, 1 a gate failed, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

HANDOFF = REPO / ".handoff"
MIGRATION_SQL = REPO / "sql" / "016_source_observation_model.sql"
VENV_PYTHON = REPO / ".venv" / "bin" / "python"

# Keg-only on Homebrew, so the binaries exist while `psql` is not on PATH. Looked up rather than
# assumed: a wrong pg_dump is worse than a missing one.
LIBPQ_FALLBACK = Path("/opt/homebrew/opt/libpq/bin")

# The four canonical sets. The left name is what the backfill plan calls the count; the right is
# what the audit baseline calls the same set. They were never spelled the same way.
COUNT_PAIRS = (
    ("sources", "sources"),
    ("observations", "observations"),
    ("mission_evidence", "mission_associations"),
    ("cluster_memberships", "cluster_memberships"),
)


def compare_counts(plan: Dict[str, Any], baseline_counts: Dict[str, int]) -> List[str]:
    """Name every canonical set where the plan and the baseline disagree.

    Separate from the step that prints it because this comparison is the gate. The dry run
    exits 0 whether the numbers agree or not, so if this returns [] wrongly, nothing else
    stands between a short plan and a written migration.
    """
    return [
        f"{audit_key}: plan {plan[plan_key]}, baseline {baseline_counts[audit_key]}"
        for plan_key, audit_key in COUNT_PAIRS
        if plan[plan_key] != baseline_counts[audit_key]
    ]


# libpq honours this itself, which is what makes a host that accepts no connection fail rather
# than hang. The wall-clock timeout on the probe is the backstop for whatever gets past connect.
CONNECT_TIMEOUT_SECONDS = "15"
PROBE_TIMEOUT = 45

# A double whose shortest round-trip text needs 17 significant digits. Rounded to 15 it becomes
# 262600000.0, and that value is inside the observation digest -- this exact number is the one
# the corpus contains and the one that first showed a pooler changing a digest.
EXACT_DOUBLE = "262600000.00000003"


def double_survives(read_back: str) -> bool:
    """Whether the connection returned the double intact.

    The property, not the mechanism. An earlier version of this check set a session parameter
    and read the parameter back, which proves nothing: through pgbouncer in transaction mode
    with an idle pool the same server connection is reused and the setting appears to hold. What
    protects the digest is that the number arrives unrounded, so that is what is measured.
    """
    return read_back == EXACT_DOUBLE


APPLY_CONFIRMATION = "APPLY"
QUIESCE_CONFIRMATION = "QUIESCED"


class Stop(Exception):
    """A gate refused. The message is what the operator needs to decide what to do next."""


class Unrunnable(Exception):
    """A precondition is absent. Nothing was attempted."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def say(text: str = "") -> None:
    print(text, flush=True)


def shown(path: Path) -> str:
    """Repo-relative when it is inside the repo, absolute otherwise -- a run dir need not be."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def heading(step: int, title: str) -> None:
    say()
    say(f"── step {step} · {title} " + "─" * max(0, 60 - len(title)))


class Journal:
    """Every step's evidence, on disk, written as each step ends rather than at the end."""

    def __init__(self, path: Path, dsn_host: str) -> None:
        self.path = path
        self.data: Dict[str, Any] = {
            "started_at": now(),
            "dsn_host": dsn_host,
            "steps": [],
        }
        self._flush()

    def begin(self, step: int, title: str) -> None:
        """Written before the step runs, not after it succeeds.

        A run that is killed mid-step used to leave nothing behind: the journal ended at the
        last step that finished, so which step was in flight -- and therefore whether anything
        had been written -- had to be guessed. It happened during a real apply.
        """
        self.data["steps"].append({"step": step, "title": title, "at": now(), "state": "started"})
        self._flush()

    def record(self, step: int, title: str, **evidence: Any) -> None:
        self.data["steps"].append({"step": step, "title": title, "at": now(), "state": "done", **evidence})
        self._flush()

    def _flush(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")


DIRECT_CONNECTION_KEY = "DATABASE_DIRECT_CONNECTION"


def dsn_from_env_file(path: Path = REPO / ".env") -> str:
    """The direct connection out of .env, if it is there.

    Deliberately not DATABASE_URL. That is the runtime's DSN, and a cutover choosing its own
    connection rather than inheriting the application's is the point: which connection the
    migration ran through is part of what the journal records.
    """
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{DIRECT_CONNECTION_KEY}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def resolve(host: str, port: int) -> None:
    """Fail on a name the machine cannot use, before blaming the credentials.

    getaddrinfo is what psql calls, and it does not always agree with dig. dig sends its own
    query; getaddrinfo goes through the system resolver, which a VPN can own. On 20/09/2026 dig
    printed this host's AAAA record while getaddrinfo failed for every family, with Cloudflare
    WARP running and every configured nameserver pointing at its local resolver.

    The message reports what was measured rather than a mechanism. An earlier version asserted a
    missing IPv6 default route; netstat showed several, through the VPN's own tunnels.
    """
    try:
        socket.getaddrinfo(host, port)
        return
    except socket.gaierror as failure:
        reason = failure

    usable = []
    for family, label in ((socket.AF_INET6, "AAAA"), (socket.AF_INET, "A")):
        try:
            socket.getaddrinfo(host, port, family)
            usable.append(label)
        except socket.gaierror:
            pass

    # dig asks DNS directly. Disagreement between the two is the whole diagnosis, so it is
    # measured here rather than described.
    direct = run(["dig", "+short", "AAAA", host], capture=True, timeout=10)
    dns_answer = direct.stdout.strip().splitlines()[-1] if direct.stdout.strip() else ""

    tunnels = run(["netstat", "-rn", "-f", "inet6"], capture=True, timeout=10)
    via_tunnel = sorted(
        {line.split()[-1] for line in tunnels.stdout.splitlines() if line.startswith("default") and "utun" in line}
    )

    raise Unrunnable(
        f"{host} does not resolve to an address this machine can use.\n"
        f"  getaddrinfo: {reason}\n"
        f"  families getaddrinfo can use: {', '.join(usable) or 'none'}\n"
        f"  the same name asked of DNS directly: {dns_answer or 'no answer'}\n"
        f"  IPv6 default routes through a tunnel: {', '.join(via_tunnel) or 'none'}\n"
        + (
            "  DNS has the address and getaddrinfo will not use it, which is what a VPN owning\n"
            "  the system resolver looks like. Disconnect it and run again.\n"
            if dns_answer
            else "  DNS has no address for this name either. Check the host in .env.\n"
        )
        + "  The pooler host resolves over IPv4 and is a usable fallback for every step except\n"
        "  the snapshot -- take that one from the provider's dashboard and pass --snapshot."
    )


def find_tool(name: str) -> Path:
    found = shutil.which(name)
    if found:
        return Path(found)
    candidate = LIBPQ_FALLBACK / name
    if candidate.exists():
        return candidate
    raise Unrunnable(
        f"{name} not found on PATH or in {LIBPQ_FALLBACK}. "
        f"On this machine libpq is installed keg-only: brew install libpq, then use "
        f"{LIBPQ_FALLBACK}/{name} or add it to PATH."
    )


def tool_major_version(tool: Path) -> Optional[int]:
    out = run([str(tool), "--version"], capture=True)
    match = re.search(r"(\d+)\.\d+", out.stdout)
    return int(match.group(1)) if match else None


class Ran:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(
    command: Sequence[str],
    capture: bool = False,
    echo: bool = False,
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
) -> Ran:
    """Run a command. `capture` keeps the output for inspection; otherwise it streams.

    stderr is never discarded. The reason a step failed is usually only there.

    A captured child gets no stdin. Captured output and an inherited terminal is how a command
    that decides to ask something -- psql wanting a password, say -- waits forever while the
    operator sees nothing at all.
    """
    if echo:
        say(f"  $ {' '.join(redact(part) for part in command)}")
    try:
        if capture:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                env=env,
            )
            return Ran(completed.returncode, completed.stdout, completed.stderr)
        completed = subprocess.run(command, stderr=subprocess.PIPE, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return Ran(-1, "", f"gave no answer in {timeout}s")
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return Ran(completed.returncode, "", completed.stderr or "")


def without_password(dsn: str) -> Tuple[str, Dict[str, str]]:
    """The DSN with its password removed, and the environment that carries it instead.

    argv is world-readable. On this machine `ps` printed a full connection string, password
    included, to an unprivileged process during a real run -- so the password travels in the
    environment, which `ps` cannot show another user, and never as an argument.

    psql and pg_dump take it from PGPASSWORD. The three migration scripts already default their
    --dsn from DATABASE_URL, so they are given the whole DSN that way and no --dsn at all.

    DATABASE_URL is set on every call, not only when a password had to be moved out of the URI.
    A passwordless DSN used to be handed back with the environment untouched, so preflight
    measured the database this run chose while the audit, the backfill and the verifier read
    whichever one the operator's shell already named.
    """
    parsed = urlsplit(dsn)
    environment = dict(os.environ)
    environment["DATABASE_URL"] = dsn
    if not parsed.password:
        # An inherited one would authenticate a connection this run never described.
        environment.pop("PGPASSWORD", None)
        return dsn, environment
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    # parsed.username keeps its percent-encoding, which is what belongs back in a URI. The
    # password does not: PGPASSWORD is a literal, and handing libpq the escaped text
    # authenticates with a password nobody set.
    authority = f"{parsed.username}@{host}" if parsed.username else host
    stripped = urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, parsed.fragment))
    environment["PGPASSWORD"] = unquote(parsed.password)
    return stripped, environment


def redact(part: str) -> str:
    """A DSN carries the password. It is not going into the terminal scrollback or the journal."""
    if "://" in part and "@" in part:
        scheme, rest = part.split("://", 1)
        return f"{scheme}://[REDACTED]@{rest.split('@', 1)[1]}"
    return part


def dsn_host(dsn: str) -> str:
    if "://" not in dsn:
        return "?"
    rest = dsn.split("://", 1)[1]
    authority = rest.split("@", 1)[1] if "@" in rest else rest
    return authority.split("/", 1)[0]


def psql_value(psql: Path, dsn: str, sql: str, timeout: int = PROBE_TIMEOUT) -> Ran:
    """One value out of the database, or a failure. Never a prompt, never an unbounded wait."""
    safe, environment = without_password(dsn)
    return run(
        [str(psql), safe, "-tAX", "-w", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture=True,
        timeout=timeout,
        env=environment,
    )


# ───────────────────────────── step 0: preflight ─────────────────────────────


def preflight(dsn: str, run_dir: Path) -> Dict[str, Any]:
    heading(0, "preflight")
    if not dsn:
        raise Unrunnable(f"No DSN: pass --dsn, set PRODUCTION_DSN, or put {DIRECT_CONNECTION_KEY} in .env.")

    host = dsn_host(dsn)
    if not dsn.startswith("postgres"):
        raise Unrunnable(f"This cutover targets PostgreSQL. Got a {dsn.split(':', 1)[0]} DSN.")

    if not MIGRATION_SQL.exists():
        raise Unrunnable(f"Missing {MIGRATION_SQL.relative_to(REPO)}")
    if not VENV_PYTHON.exists():
        raise Unrunnable(f"Missing {VENV_PYTHON}. Run ./scripts/bootstrap.sh first.")

    psql = find_tool("psql")
    pg_dump = find_tool("pg_dump")
    pg_restore = find_tool("pg_restore")

    run_dir.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(run_dir).free / 1024**3

    say(f"  host            {host}")
    say(f"  run dir         {run_dir} ({free_gb:.1f} GiB free)")

    target = urlsplit(dsn)
    resolve(target.hostname or "", target.port or 5432)
    safe_dsn, environment = without_password(dsn)
    # the value in force, not the default: an environment override that the line does not
    # reflect is the same class of untruth this whole script exists to remove
    say(f"  connecting ... ({os.environ['PGCONNECT_TIMEOUT']}s connect timeout)")

    reading = run(
        [
            str(psql),
            safe_dsn,
            "-tAX",
            "-w",
            "-c",
            "SET extra_float_digits = 3",
            "-c",
            f"select {EXACT_DOUBLE}::float8::text",
        ],
        capture=True,
        timeout=PROBE_TIMEOUT,
        env=environment,
    )
    read_back = reading.stdout.strip().splitlines()[-1].strip() if reading.stdout.strip() else ""
    say(f"  float precision {read_back or '(nothing)'}")
    if not double_survives(read_back):
        raise Unrunnable(
            "A double does not survive this connection intact.\n"
            f"  sent {EXACT_DOUBLE}, read back {read_back or 'nothing'}\n"
            "  metric_value and growth_velocity are inside the observation digest, so a\n"
            "  connection that rounds them makes the same corpus hash two different ways and\n"
            "  step 7 cannot mean anything. Supabase's pooler answers with\n"
            "  extra_float_digits = 0, which does exactly this. Use a direct connection."
        )

    probe = psql_value(
        psql,
        dsn,
        "select current_database() || ' | ' || current_user || ' | ' || current_setting('server_version')",
    )
    if not probe.ok:
        raise Unrunnable(
            "Could not reach the database.\n"
            f"  psql said: {probe.stderr.strip() or '(nothing)'}\n"
            "  The name resolves to an address this machine can use, so what is left is a\n"
            "  password that no longer matches a rotation, or a host that accepts no\n"
            "  connection from this network."
        )
    database, user, server_version = [field.strip() for field in probe.stdout.strip().split("|")]
    server_major = int(server_version.split(".")[0])
    dump_major = tool_major_version(pg_dump)

    say(f"  database        {database} as {user}")
    say(f"  server          {server_version}")
    say(f"  pg_dump         {dump_major} ({pg_dump})")

    if dump_major is not None and dump_major < server_major:
        raise Unrunnable(f"pg_dump {dump_major} cannot dump a server {server_major} cluster. Upgrade libpq.")

    return {
        "psql": psql,
        "pg_dump": pg_dump,
        "pg_restore": pg_restore,
        "host": host,
        "database": database,
        "user": user,
        "server_version": server_version,
        "pg_dump_major": dump_major,
    }


# ───────────────────────────── step 1: quiesce ─────────────────────────────

QUIESCE_SQL = """
select pid, coalesce(nullif(application_name, ''), '?'), state, coalesce(query_start::text, '-')
from pg_stat_activity
where datname = current_database() and pid <> pg_backend_pid()
order by query_start nulls last
"""


def step_quiesce(tools: Dict[str, Any], dsn: str, journal: Journal, assume: bool) -> None:
    heading(1, "quiesce every writer")
    journal.begin(1, "quiesce")
    result = psql_value(tools["psql"], dsn, QUIESCE_SQL)
    if not result.ok:
        raise Stop(f"Could not read pg_stat_activity.\n{result.stderr.strip()}")

    rows = [line.split("|") for line in result.stdout.strip().splitlines() if line.strip()]
    if rows:
        say(f"  {len(rows)} other backend(s) on this database:")
        for pid, application, state, started in rows:
            say(f"    pid {pid:<8} {application:<28} {state:<20} since {started}")
    else:
        say("  no other backend is connected")

    say()
    say("  Stop the worker daemon, any cron entry and every open MCP session. A connection that")
    say("  writes after the snapshot is a row the migration will not carry.")
    if assume:
        say("  --assume-quiesced given; not asking.")
    else:
        confirm(
            f"  Type {QUIESCE_CONFIRMATION} once nothing can write: ",
            QUIESCE_CONFIRMATION,
            "Nothing was touched.",
        )
    journal.record(1, "quiesce", other_backends=len(rows), backends=rows)


def confirm(prompt: str, expected: str, on_refusal: str) -> None:
    try:
        answer = input(prompt).strip()
    except EOFError:
        raise Stop(f"This step needs a typed {expected} and stdin is closed. Run it in a terminal.")
    if answer != expected:
        raise Stop(f"Got {answer or 'nothing'!r}, not {expected}. {on_refusal}")


# ───────────────────────────── step 2: snapshot ─────────────────────────────


def step_snapshot(tools: Dict[str, Any], dsn: str, run_dir: Path, journal: Journal, supplied: Optional[Path]) -> Path:
    heading(2, "snapshot, and prove it reads back")
    journal.begin(2, "snapshot")

    if supplied is not None:
        if not supplied.exists():
            raise Stop(f"--snapshot {supplied} does not exist.")
        target = supplied
        say(f"  using    {shown(target)} (taken elsewhere; this step only proves it reads back)")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = run_dir / f"snapshot-{stamp}.dump"
        safe, environment = without_password(dsn)
        dumped = run(
            [str(tools["pg_dump"]), safe, "-w", "-Fc", "-f", str(target)],
            capture=True,
            env=environment,
        )
        if not dumped.ok:
            raise Stop(
                "pg_dump failed, so there is no snapshot and nothing after this step may run.\n"
                f"{dumped.stderr.strip()}\n"
                "A pooler may refuse pg_dump at the startup protocol; Supabase's session-mode\n"
                "pooler on 5432 did not, in the 20/09/2026 cutover. If yours does, take the\n"
                "snapshot from the provider's dashboard and pass it with --snapshot."
            )

    size = target.stat().st_size if target.exists() else 0
    listed = run([str(tools["pg_restore"]), "--list", str(target)], capture=True)
    objects = [line for line in listed.stdout.splitlines() if line and not line.startswith(";")]
    if supplied is None:
        say(f"  wrote     {shown(target)} ({size / 1024**2:.1f} MiB)")
    else:
        say(f"            {size / 1024**2:.1f} MiB")
    say(f"  reads back as {len(objects)} archive entries")

    if not listed.ok or not objects:
        raise Stop(
            "pg_dump exited 0 but pg_restore --list cannot read the archive back. That file is "
            f"not a snapshot.\n{listed.stderr.strip()}"
        )

    journal.record(
        2,
        "snapshot",
        path=str(target),
        bytes=size,
        archive_entries=len(objects),
        taken_by="operator" if supplied is not None else "pg_dump",
    )
    return target


# ───────────────────────────── step 3: baseline ─────────────────────────────


def step_baseline(dsn: str, run_dir: Path, journal: Journal) -> Dict[str, Any]:
    heading(3, "baseline, from the corpus about to be migrated")
    journal.begin(3, "baseline")
    baseline_path = run_dir / "source-observation-baseline.json"
    rows_path = run_dir / "source-observation-rows.json"

    result = run(
        [
            str(VENV_PYTHON),
            str(REPO / "scripts" / "migration_reconciliation_audit.py"),
            "--json-out",
            str(baseline_path),
            "--rows-out",
            str(rows_path),
        ],
        echo=True,
        env=without_password(dsn)[1],
    )
    if not result.ok:
        raise Stop(
            f"The audit exited {result.returncode}. It only exits 0 when the corpus balances, "
            "and an unbalanced corpus is the migration's own gate. Do not continue."
        )
    if not baseline_path.exists():
        raise Stop(f"The audit exited 0 but wrote no {baseline_path.name}.")

    baseline = json.loads(baseline_path.read_text())
    if not baseline.get("balanced"):
        raise Stop("The audit exited 0 but the report says the corpus is not balanced.")

    counts = baseline["digests"]["member_counts"]
    say(f"  baseline  {shown(baseline_path)} (schema_version {baseline['schema_version']})")
    for _, audit_key in COUNT_PAIRS:
        say(f"    {audit_key:<22} {counts[audit_key]}")
    say(f"  unsanitized rows in {shown(rows_path)} -- never commit this file")

    journal.record(
        3,
        "baseline",
        exit_code=0,
        baseline=str(baseline_path),
        schema_version=baseline["schema_version"],
        member_counts=counts,
        digests={name: baseline["digests"][name] for _, name in COUNT_PAIRS},
    )
    return baseline


# ───────────────────────────── step 4: schema ─────────────────────────────


def step_schema(tools: Dict[str, Any], dsn: str, journal: Journal) -> None:
    heading(4, "apply the schema")
    journal.begin(4, "schema")
    safe, environment = without_password(dsn)
    result = run(
        [str(tools["psql"]), safe, "-w", "-v", "ON_ERROR_STOP=1", "-f", str(MIGRATION_SQL)],
        echo=True,
        env=environment,
    )
    if not result.ok:
        raise Stop(f"psql exited {result.returncode} applying {MIGRATION_SQL.name}.")
    say("  schema applied; this migration moves no data")
    journal.record(4, "schema", exit_code=0, file=MIGRATION_SQL.name)


# ───────────────────────────── step 5: dry run ─────────────────────────────


def step_dry_run(dsn: str, baseline: Dict[str, Any], journal: Journal) -> None:
    heading(5, "dry run, compared with the baseline by value")
    journal.begin(5, "dry run")
    try:
        import backfill_observations as backfill_module
    except Exception as exc:  # pragma: no cover - import failure is a broken checkout
        raise Unrunnable(f"Could not import backfill_observations: {exc}")

    target = backfill_module.open_target(dsn)
    try:
        summary = backfill_module.backfill(target, apply=False)
    except backfill_module.BackfillRefused as exc:
        raise Stop(f"The backfill refused the plan: {exc}")
    finally:
        target.close()

    if not summary["target_tables_present"]:
        raise Stop("The target tables are absent. Step 4 did not take effect.")

    expected = baseline["digests"]["member_counts"]
    mismatches = compare_counts(summary, expected)
    say("            plan       baseline")
    for plan_key, audit_key in COUNT_PAIRS:
        planned, wanted = summary[plan_key], expected[audit_key]
        say(f"  {'ok ' if planned == wanted else 'BAD'} {audit_key:<22} {planned:>8}  {wanted:>8}")

    pre_existing = summary["pre_existing_observations"]
    if pre_existing:
        say(f"  {pre_existing} planned observations already exist; the write updates those rows")

    journal.record(
        5,
        "dry run",
        plan={plan_key: summary[plan_key] for plan_key, _ in COUNT_PAIRS},
        baseline_counts=expected,
        pre_existing_observations=pre_existing,
        matched=not mismatches,
    )
    if mismatches:
        raise Stop(
            "The plan and the baseline disagree:\n    "
            + "\n    ".join(mismatches)
            + "\n  The dry run's own exit code is 0 either way, which is why this is compared "
            "here. Do not reconcile by editing the baseline -- find out what changed."
        )
    say("  four counts match")


# ───────────────────────────── step 6: apply ─────────────────────────────


def step_apply(dsn: str, journal: Journal) -> None:
    heading(6, "apply the backfill -- THIS IS THE STEP THAT DOES NOT REVERSE")
    say("  One transaction. Recovery from here on is the snapshot from step 2, nothing else.")
    confirm(
        f"  Type {APPLY_CONFIRMATION} to write: ",
        APPLY_CONFIRMATION,
        "Nothing was written; the database is as step 4 left it.",
    )
    journal.begin(6, "apply")
    result = run(
        [
            str(VENV_PYTHON),
            str(REPO / "scripts" / "backfill_observations.py"),
            "--apply",
        ],
        echo=True,
        env=without_password(dsn)[1],
    )
    journal.record(6, "apply", exit_code=result.returncode)
    if not result.ok:
        raise Stop(
            f"The backfill exited {result.returncode}. It runs in one transaction, so the three "
            "tables are as they were before this step -- but verify that before retrying."
        )


# ───────────────────────────── step 7: verify ─────────────────────────────


def step_verify(dsn: str, run_dir: Path, journal: Journal) -> Dict[str, Any]:
    heading(7, "verify against the baseline from step 3")
    journal.begin(7, "verify")
    baseline_path = run_dir / "source-observation-baseline.json"
    report_path = run_dir / "post-migration-verification.json"
    if not baseline_path.exists():
        raise Unrunnable(
            f"{baseline_path.name} is missing. Verification must use the baseline taken from the "
            "snapshot that was migrated, never the rehearsal artifact tracked in docs/."
        )

    result = run(
        [
            str(VENV_PYTHON),
            str(REPO / "scripts" / "post_migration_verification.py"),
            "--baseline",
            str(baseline_path),
            "--json-out",
            str(report_path),
        ],
        echo=True,
        env=without_password(dsn)[1],
    )
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    journal.record(
        7,
        "verify",
        exit_code=result.returncode,
        verified=report.get("verified"),
        report=str(report_path) if report else None,
        digests={comparison["set"]: comparison["actual_digest"] for comparison in report.get("comparisons", [])},
    )
    if not result.ok or not report.get("verified"):
        raise Stop(
            f"Verification exited {result.returncode}. Hold ingress closed. Every line marked BAD "
            "above names a set whose digest or member count moved; that is data the migration did "
            "not carry, not a threshold to relax."
        )
    return report


# ───────────────────────────── closing ─────────────────────────────


def closing_note(journal: Journal, report: Dict[str, Any]) -> None:
    say()
    say("─" * 68)
    say("  Steps 1 through 7 passed. Steps 8 and 9 are yours, in this order:")
    say("    8. start the new runtime and check health")
    say("    9. reopen ingress")
    say()
    say("  Starting the runtime before verification passed is one of the three things the")
    say("  runbook forbids; it passed, so this is now the ordinary order rather than a shortcut.")
    say()
    say(f"  Journal: {shown(journal.path)}")
    say("  For the BACKLOG.md entry:")
    say(f"    run on {now()} · audit exit 0 · verification exit 0")
    for comparison in report.get("comparisons", []):
        say(f"    {comparison['set']:<22} {comparison['actual_digest']}")


def _interrupt(signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dsn",
        default="",
        help=f"default: $PRODUCTION_DSN, else {DIRECT_CONNECTION_KEY} from .env",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=HANDOFF,
        help="where the snapshot, baseline, report and journal go; default .handoff/",
    )
    parser.add_argument(
        "--start-at",
        type=int,
        default=1,
        choices=range(1, 8),
        metavar="1-7",
        help="resume after a gate stopped the run; preflight always runs",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="a snapshot taken another way; step 2 then only proves it reads back",
    )
    parser.add_argument(
        "--assume-quiesced",
        action="store_true",
        help="skip the typed confirmation in step 1, having already stopped every writer",
    )
    args = parser.parse_args(argv)
    os.environ.setdefault("PGCONNECT_TIMEOUT", CONNECT_TIMEOUT_SECONDS)
    # SIGHUP is a closed terminal, SIGTERM a kill. Both used to end the process with no journal
    # entry at all; both now take the same path as Ctrl-C.
    signal.signal(signal.SIGHUP, _interrupt)
    signal.signal(signal.SIGTERM, _interrupt)
    if not args.dsn:
        args.dsn = os.environ.get("PRODUCTION_DSN", "") or dsn_from_env_file()

    say()
    say("  T020 production cutover")
    say(f"  runbook .handoff/T020-cutover-runbook.md · started {now()}")

    journal: Optional[Journal] = None
    try:
        tools = preflight(args.dsn, args.run_dir)
        journal = Journal(
            args.run_dir / f"t020-run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json",
            tools["host"],
        )
        journal.record(0, "preflight", **{key: tools[key] for key in ("host", "database", "user", "server_version")})

        if args.start_at > 1:
            say()
            say(f"  --start-at {args.start_at}: steps 1 to {args.start_at - 1} are being skipped.")
            if args.start_at > 2:
                say("  The snapshot from the earlier run is the only thing standing between a")
                say("  failed step 6 and data loss. Confirm it still exists before continuing.")

        if args.start_at <= 1:
            step_quiesce(tools, args.dsn, journal, args.assume_quiesced)
        if args.start_at <= 2:
            step_snapshot(tools, args.dsn, args.run_dir, journal, args.snapshot)

        baseline: Dict[str, Any]
        if args.start_at <= 3:
            baseline = step_baseline(args.dsn, args.run_dir, journal)
        else:
            baseline_path = args.run_dir / "source-observation-baseline.json"
            if not baseline_path.exists():
                raise Unrunnable(f"--start-at {args.start_at} needs {baseline_path.name} from step 3.")
            baseline = json.loads(baseline_path.read_text())
            say(f"  reusing {shown(baseline_path)} from the earlier run")

        if args.start_at <= 4:
            step_schema(tools, args.dsn, journal)
        if args.start_at <= 5:
            step_dry_run(args.dsn, baseline, journal)
        if args.start_at <= 6:
            step_apply(args.dsn, journal)
        report = step_verify(args.dsn, args.run_dir, journal)
        closing_note(journal, report)
        return 0

    except Stop as exc:
        say()
        say(f"  STOPPED: {exc}")
        if journal is not None:
            journal.record(-1, "stopped", reason=str(exc))
            say(f"  Journal: {shown(journal.path)}")
        say("  Ingress stays closed until a rerun passes step 7.")
        return 1
    except Unrunnable as exc:
        say()
        say(f"  CANNOT RUN: {exc}")
        return 2
    except KeyboardInterrupt as interrupt:
        say()
        # an exception object is always truthy, so the reason has to come from its text
        say(f"  INTERRUPTED ({str(interrupt) or 'Ctrl-C'}).")
        if journal is not None:
            journal.record(-1, "interrupted", reason=str(interrupt) or "Ctrl-C")
            say(f"  Journal: {shown(journal.path)}")
        say("  The backfill is one transaction, so an interrupted write rolled back -- but the")
        say("  journal's last entry is what says which step was in flight. Rerun --start-at 5:")
        say("  the dry run reports how many planned observations already exist, which is 0 after")
        say("  a rollback and the full count after a commit.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
