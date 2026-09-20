#!/usr/bin/env python
"""Run the T020 production cutover as a gated sequence, or stop at the first gate that fails.

The three migration scripts each answer one question well. What they do not do is refuse to let
the next step start, and one of them cannot: `backfill_observations.py --dry-run` exits 0 whether
the plan matches the baseline, disagrees with it, or finds no target schema at all. The gate that
the runbook places after the dry run therefore exists only in the reader's attention. Here it is
a comparison the process performs and fails on.

What this adds over running the commands by hand:

  measures the connection   a double whose text needs 17 significant digits is sent and read
                            back. metric_value and growth_velocity enter the observation digest,
                            so a connection that rounds them makes one corpus hash two ways.
                            The measurement, not the hostname, decides: the 20/09/2026 cutover
                            ran entirely through a session-mode pooler, which returned the
                            number intact.
  proves the snapshot       pg_dump exiting 0 is not a restorable file. pg_restore --list must
                            read the archive back and name objects in it.
  measures the standstill   the legacy projection is hashed before the snapshot, after it, and
                            again immediately before the write. A typed QUIESCED records that an
                            operator believes the writers are stopped; these three measurements
                            are what can contradict them, including an update in place, which
                            moves no member count at all.
  compares four counts      the dry-run plan against the baseline taken from the snapshot, by
                            value, before anything is written.
  one irreversible step     step 6 is the only step that writes, and it asks for a typed word.
  writes a journal          every step's command, exit code, timestamp and evidence, so closing
                            T020 in BACKLOG.md is a matter of quoting the file.

Steps 8 and 9 of the runbook -- start the new runtime, reopen ingress -- are deliberately not
automated. They depend on what the operator has running, and doing them early is one of the three
things the runbook forbids.

  binds a resumed run       --start-at reads the earlier run's journal, and refuses unless this
                            connection reaches the same database, the snapshot and the baseline
                            still hash to what that run recorded, and the corpus still matches
                            the measurement that run took.

Usage:
    .venv/bin/python scripts/t020_cutover.py
    .venv/bin/python scripts/t020_cutover.py --start-at 5
    .venv/bin/python scripts/t020_cutover.py --start-at 5 --journal .handoff/t020-run-...json

The DSN comes from --dsn, else $PRODUCTION_DSN, else the direct-connection key in .env. Any DSN
that passes preflight will do -- no connection is refused for the shape of its hostname. In the
20/09/2026 cutover the session-mode pooler was the only route that worked at all, and pg_dump ran
through it; if yours refuses pg_dump, take the snapshot another way and pass --snapshot.

Exit codes: 0 every step through verification passed, 1 a gate failed, 2 could not run.
"""

from __future__ import annotations

import argparse
import hashlib
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

# libpq's own parser, not a URI split. It is the only thing that agrees with what psql, pg_dump
# and psycopg will actually connect to: it reads ?password= and keyword/value strings, decodes
# percent-escapes, and keeps an IPv6 literal a host rather than a colon-separated string.
from psycopg.conninfo import conninfo_to_dict, make_conninfo

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


# The same four sets, named the way the audit names them. Written from COUNT_PAIRS rather than
# beside it so a set can never be added to one and forgotten in the other.
CANONICAL_SETS = tuple(audit_key for _, audit_key in COUNT_PAIRS)


def canonical_digests(digests: Dict[str, Any]) -> Dict[str, Any]:
    """The four digests and the four member counts, and nothing else.

    The audit publishes more than this -- an algorithm label, breakdowns -- and none of it
    describes the corpus. Comparing whole reports would make a rewording of a label look like
    data moving.
    """
    return {
        "digests": {name: digests[name] for name in CANONICAL_SETS},
        "member_counts": {name: digests["member_counts"][name] for name in CANONICAL_SETS},
    }


def corpus_drift(reference: Dict[str, Any], observed: Dict[str, Any]) -> List[str]:
    """Name every canonical set that is not byte-identical to the reference.

    The digest is compared even where the count agrees. A pass that rewrites a row rather than
    adding one leaves all four counts exactly where they were, so a count-only gate reads a
    corpus that moved as one that stood still -- and the snapshot in hand no longer restores
    what is about to be migrated.
    """
    moved = []
    for name in CANONICAL_SETS:
        was = reference["member_counts"][name]
        became = observed["member_counts"][name]
        if was != became:
            moved.append(f"{name}: {was} members became {became}")
        elif reference["digests"][name] != observed["digests"][name]:
            moved.append(f"{name}: {was} members both times, different digest")
    return moved


def legacy_digests(dsn: str) -> Dict[str, Any]:
    """Hash the whole legacy projection, the way the baseline does.

    The audit's own reader and its own projection, imported rather than reimplemented: a second
    way of hashing the same corpus would disagree with the baseline for reasons that have
    nothing to do with the data. It reads every legacy row, which on the production corpus is a
    few seconds -- paid three times over a cutover, against a snapshot that would otherwise be
    trusted on an operator's word.
    """
    import migration_reconciliation_audit as audit_module

    reader = audit_module.open_reader(dsn)
    try:
        report = audit_module.audit(reader)
    finally:
        reader.close()
    return canonical_digests(report["digests"])


def require_no_drift(reference: Dict[str, Any], observed: Dict[str, Any], moment: str) -> None:
    drift = corpus_drift(reference, observed)
    if not drift:
        say(f"  corpus unchanged {moment}")
        return
    raise Stop(
        f"The legacy corpus changed {moment}:\n    "
        + "\n    ".join(drift)
        + "\n  A typed QUIESCED says a writer was meant to be stopped; this says one was not.\n"
        "  The snapshot no longer restores the corpus the next step would migrate, so nothing\n"
        "  after this point may run. Find the writer, stop it, and start again from step 1."
    )


def require_standstill(dsn: str, reference: Dict[str, Any], moment: str) -> Dict[str, Any]:
    observed = legacy_digests(dsn)
    require_no_drift(reference, observed, moment)
    return observed


def sha256_of(path: Path) -> str:
    """The file's own identity, so a resumed run can tell it from another file of that name."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# libpq honours this itself, which is what makes a host that accepts no connection fail rather
# than hang. The wall-clock timeout on the probe is the backstop for whatever gets past connect.
CONNECT_TIMEOUT_SECONDS = "15"
PROBE_TIMEOUT = 45

# A double whose shortest round-trip text needs 17 significant digits. Rounded to 15 it becomes
# 262600000.0, and that value is inside the observation digest -- this exact number is the one
# the corpus contains and the one that first showed a connection changing a digest.
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
        + "  Another route to the same database is a fine answer -- a pooler host that resolves\n"
        "  over IPv4, for instance. Nothing here refuses a connection for its hostname; what it\n"
        "  has to do is pass the measurements above."
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


def dsn_fields(dsn: str) -> Dict[str, str]:
    """Every connection parameter libpq reads out of this DSN.

    Hand-rolled URI splitting got two shapes wrong that libpq treats as ordinary. A password
    given as `?password=` is invisible to urlsplit().password, so the old code concluded there
    was nothing to move and handed the whole string to psql on the command line. An IPv6 literal
    lost its brackets on the way back into a URI and stopped naming a host at all.
    """
    try:
        return conninfo_to_dict(dsn)
    except Exception as exc:
        raise Unrunnable(f"libpq cannot read this connection string: {exc}")


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
    fields = dsn_fields(dsn)
    environment = dict(os.environ)
    environment["DATABASE_URL"] = dsn
    password = fields.pop("password", None)
    if password is None:
        # An inherited one would authenticate a connection this run never described.
        environment.pop("PGPASSWORD", None)
    else:
        environment["PGPASSWORD"] = password
    # Keyword/value, which psql and pg_dump accept as readily as a URI and which cannot be
    # reassembled wrongly. libpq has already decoded every percent-escape.
    return make_conninfo(**fields), environment


def redact(part: str) -> str:
    """A DSN carries the password. It is not going into the terminal scrollback or the journal."""
    if "://" in part and "@" in part:
        scheme, rest = part.split("://", 1)
        return f"{scheme}://[REDACTED]@{rest.split('@', 1)[1]}"
    return part


def dsn_host(dsn: str) -> str:
    fields = dsn_fields(dsn)
    host = fields.get("host", "")
    port = fields.get("port", "")
    return f"{host}:{port}" if port else host or "?"


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

    fields = dsn_fields(dsn)
    host = dsn_host(dsn)

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

    resolve(fields.get("host", ""), int(fields.get("port") or 5432))
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
            "  step 7 cannot mean anything. A connection answering with extra_float_digits = 0\n"
            "  does exactly this, whatever kind of endpoint it is. Find one that does not."
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

    which_database = psql_value(psql, dsn, IDENTITY_SQL)
    if not which_database.ok:
        raise Unrunnable(
            "Could not read this database's identity.\n"
            f"  psql said: {which_database.stderr.strip() or '(nothing)'}\n"
            "  A resumed run has nothing to check its journal against without it."
        )
    which_cluster = psql_value(psql, dsn, SYSTEM_IDENTIFIER_SQL)
    identity = identity_fields(
        which_database.stdout, which_cluster.stdout if which_cluster.ok else ""
    )
    if identity["system_identifier"]:
        say(f"  cluster         {identity['system_identifier']}")
    else:
        say("  cluster         identifier not readable on this connection")
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
        "identity": identity,
    }


# ───────────────────────────── resuming an earlier run ─────────────────────────────


def previous_journal(run_dir: Path, supplied: Optional[Path]) -> Tuple[Path, Dict[str, Any]]:
    """The journal of the run being resumed, named or found, never guessed at."""
    if supplied is not None:
        if not supplied.exists():
            raise Unrunnable(f"--journal {supplied} does not exist.")
        path = supplied
    else:
        candidates = sorted(run_dir.glob("t020-run-*.json"))
        if not candidates:
            raise Unrunnable(
                f"--start-at needs the journal of the run it resumes, and {shown(run_dir)} holds "
                "none. Pass --journal, or start from step 1.\n"
                "  The baseline file alone is not enough: its name says nothing about which "
                "database it was taken from or whether it is still the file that was written."
            )
        path = candidates[-1]
    try:
        return path, json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise Unrunnable(f"Could not read {shown(path)}: {exc}")


def last_done(data: Dict[str, Any], title: str) -> Optional[Dict[str, Any]]:
    finished = [
        entry for entry in data.get("steps", []) if entry.get("title") == title and entry.get("state") == "done"
    ]
    return finished[-1] if finished else None


def identity_differences(recorded: Dict[str, Any], observed: Dict[str, Any]) -> List[str]:
    """Every identity field the two runs can both state and state differently."""
    return [
        f"{field}: the earlier run recorded {recorded[field]}, this connection reports {observed.get(field)}"
        for field in sorted(recorded)
        if recorded.get(field) and observed.get(field) and recorded[field] != observed[field]
    ]


def cluster_identified(recorded: Dict[str, Any], observed: Dict[str, Any]) -> bool:
    """Whether the two runs agree on a value that actually names one cluster.

    Only system_identifier does. The database name and OID separate two databases inside one
    cluster and say nothing at all between clusters, so agreeing on them is not identification.
    """
    return bool(recorded.get("system_identifier")) and recorded.get("system_identifier") == observed.get(
        "system_identifier"
    )


def verified_artifact(entry: Dict[str, Any], key: str, what: str) -> Path:
    """The file the earlier run wrote, proven to still be that file."""
    recorded = entry.get(key)
    recorded_sha = entry.get("sha256")
    if not recorded or not recorded_sha:
        raise Unrunnable(
            f"The earlier run's journal records no hashed {what}. It predates this check, so "
            "there is nothing to resume against. Start from step 1."
        )
    path = Path(recorded)
    if not path.exists():
        raise Unrunnable(f"The {what} the earlier run wrote is gone: {shown(path)}")
    actual = sha256_of(path)
    if actual != recorded_sha:
        raise Unrunnable(
            f"The {what} at {shown(path)} is not the file the earlier run wrote.\n"
            f"  journal  {recorded_sha}\n"
            f"  on disk  {actual}\n"
            "  A file of the right name is not the right file. Start from step 1."
        )
    return path


def resume_context(
    run_dir: Path, supplied: Optional[Path], tools: Dict[str, Any], start_at: int, dsn: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Bind this run to the run it resumes: same database, same files, same measurement.

    The old check was that a file called source-observation-baseline.json existed in the run
    directory. That is satisfied by a rehearsal artifact, by a baseline taken from a different
    deployment, and by the right file after something rewrote it.
    """
    path, data = previous_journal(run_dir, supplied)
    say(f"  resuming the run journalled in {shown(path)}")

    recorded_identity = (last_done(data, "preflight") or {}).get("identity") or {}
    differences = identity_differences(recorded_identity, tools["identity"])
    if not recorded_identity:
        raise Unrunnable(
            f"{shown(path)} records no database identity, so this connection cannot be shown to "
            "reach the database that run migrated. Start from step 1."
        )
    if differences:
        raise Unrunnable(
            "This connection does not reach the database the earlier run measured:\n    "
            + "\n    ".join(differences)
            + "\n  The baseline describes that corpus, not this one."
        )
    say(f"  same database   {recorded_identity.get('database')} (oid {recorded_identity.get('database_oid')})")
    identified = cluster_identified(recorded_identity, tools["identity"])
    if identified:
        say(f"  same cluster    {recorded_identity['system_identifier']}")

    if start_at > 2:
        snapshot = verified_artifact(last_done(data, "snapshot") or {}, "path", "snapshot")
        say(f"  same snapshot   {shown(snapshot)}")

    if start_at > 3:
        entry = last_done(data, "baseline") or {}
        baseline_path = verified_artifact(entry, "baseline", "baseline")
        say(f"  same baseline   {shown(baseline_path)}")
        baseline = json.loads(baseline_path.read_text())
        # The reference the pre-apply gate compares against is the earlier run's measurement.
        # One taken now could only ever agree with whatever it found.
        standstill = {"digests": entry["digests"], "member_counts": entry["member_counts"]}
        identify_by_corpus(dsn, standstill, identified)
        return baseline, standstill

    quiesce = last_done(data, "quiesce") or {}
    standstill = quiesce.get("standstill")
    if not standstill:
        raise Unrunnable(
            f"{shown(path)} records no corpus measurement to resume against. Start from step 1."
        )
    identify_by_corpus(dsn, standstill, identified)
    return {}, standstill


def identify_by_corpus(dsn: str, standstill: Dict[str, Any], identified: bool) -> None:
    """When the cluster will not name itself, make the corpus do it.

    A provider may revoke EXECUTE on pg_control_system(). Refusing every resume there would be a
    real regression, and falling back to the shape of the catalog is the defect this replaced.
    What is left that actually distinguishes one deployment from another is the data: a corpus
    hashing to the journal's four digests is not a coincidence between two databases.
    """
    if identified:
        return
    if not any(standstill["member_counts"].values()):
        raise Unrunnable(
            "This connection will not name its cluster, and the earlier run measured an empty\n"
            "  corpus. Every empty corpus hashes alike, so nothing here distinguishes this\n"
            "  database from any other. Start from step 1."
        )
    say("  the cluster will not name itself; identifying this database by its corpus instead")
    require_no_drift(standstill, legacy_digests(dsn), "against the journal's own measurement")


# ───────────────────────────── step 1: quiesce ─────────────────────────────

# Which database, within whatever cluster this connection reached.
IDENTITY_SQL = (
    "select current_database()"
    " || '|' || (select oid from pg_database where datname = current_database())::text"
)

# Which cluster. initdb writes this once from the clock and a random value, so it is the only
# non-privileged answer measured to differ between two freshly initialised servers. The shape of
# the catalog is not: two independent timescale/timescaledb-ha:pg16 clusters both reported
# `postgres` at OID 5 beside the two templates, hashing identically, because that is what every
# default cluster holds. EXECUTE on pg_control_system() is held by PUBLIC (proacl `=X/postgres`),
# but a provider may revoke it, so an unreadable answer is handled rather than assumed.
SYSTEM_IDENTIFIER_SQL = "select system_identifier::text from pg_control_system()"


def identity_fields(identity_row: str, system_identifier: str) -> Dict[str, str]:
    database, database_oid = [field.strip() for field in identity_row.strip().split("|")]
    return {
        "database": database,
        "database_oid": database_oid,
        "system_identifier": system_identifier.strip(),
    }

QUIESCE_SQL = """
select pid, coalesce(nullif(application_name, ''), '?'), state, coalesce(query_start::text, '-')
from pg_stat_activity
where datname = current_database() and pid <> pg_backend_pid()
order by query_start nulls last
"""


def step_quiesce(tools: Dict[str, Any], dsn: str, journal: Journal, assume: bool) -> Dict[str, Any]:
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

    # The reference every later measurement is compared against. The typed word and the
    # pg_stat_activity listing are both an operator's reading of the situation; this is the
    # corpus itself, and it is the only one of the three that can contradict the other two.
    standstill = legacy_digests(dsn)
    say("  measured the legacy corpus:")
    for name in CANONICAL_SETS:
        say(f"    {name:<22} {standstill['member_counts'][name]:>8}  {standstill['digests'][name][:16]}")
    journal.record(
        1,
        "quiesce",
        other_backends=len(rows),
        backends=rows,
        standstill=standstill,
    )
    return standstill


def confirm(prompt: str, expected: str, on_refusal: str) -> None:
    try:
        answer = input(prompt).strip()
    except EOFError:
        raise Stop(f"This step needs a typed {expected} and stdin is closed. Run it in a terminal.")
    if answer != expected:
        raise Stop(f"Got {answer or 'nothing'!r}, not {expected}. {on_refusal}")


# ───────────────────────────── step 2: snapshot ─────────────────────────────


def step_snapshot(
    tools: Dict[str, Any],
    dsn: str,
    run_dir: Path,
    journal: Journal,
    supplied: Optional[Path],
    standstill: Dict[str, Any],
) -> Path:
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
                "Some endpoints refuse pg_dump at the startup protocol. The session-mode pooler\n"
                "used in the 20/09/2026 cutover did not, and produced an 844-entry archive. If\n"
                "this one does, take the snapshot another way and pass it with --snapshot."
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

    # A snapshot of a corpus that was moving is a snapshot of neither state. Measured after the
    # archive is proven readable, so a file that cannot be restored fails for that reason first.
    require_standstill(dsn, standstill, "while the snapshot was taken")

    journal.record(
        2,
        "snapshot",
        path=str(target),
        bytes=size,
        sha256=sha256_of(target),
        archive_entries=len(objects),
        taken_by="operator" if supplied is not None else "pg_dump",
    )
    return target


# ───────────────────────────── step 3: baseline ─────────────────────────────


def step_baseline(dsn: str, run_dir: Path, journal: Journal, standstill: Dict[str, Any]) -> Dict[str, Any]:
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

    # This file is what step 7 compares the migrated corpus against. If it describes a
    # different corpus than the one measured at step 1, the whole chain verifies the wrong thing.
    require_no_drift(standstill, canonical_digests(baseline["digests"]), "in the audit's own baseline")

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
        digests={name: baseline["digests"][name] for name in CANONICAL_SETS},
        sha256=sha256_of(baseline_path),
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


def interrupted_message(journal: Optional[Journal]) -> str:
    """What the operator can and cannot conclude from a run that was killed.

    The old message said an interrupted write rolled back, unconditionally. It cannot: step 6
    runs the backfill as a child, and a signal that arrives after that child committed and
    before this process wrote the entry leaves a committed migration with no record of one.
    From inside this process the two outcomes are the same absence.
    """
    entries = journal.data["steps"] if journal is not None else []
    started = any(entry["step"] == 6 and entry["state"] == "started" for entry in entries)
    finished = any(entry["step"] == 6 and entry["state"] == "done" for entry in entries)
    if not started or finished:
        return (
            "  The write either had not started or had already been recorded, so nothing was written\n"
            "  that the journal does not name. Rerun from the step its last entry names."
        )
    return (
        "  The write was in flight and its outcome is unknown. The backfill runs in one\n"
        "  transaction, so an interrupt during it rolls back -- but a signal that arrived after\n"
        "  the child committed and before this journal recorded it leaves a committed migration\n"
        "  and no entry saying so. The two look identical from here.\n"
        "  Hold ingress closed. Rerun with --start-at 5 and read the dry run's count of planned\n"
        "  observations that already exist: 0 after a rollback, the full count after a commit.\n"
        "  Do not run step 6 again until that number has said which happened."
    )


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
        "--journal",
        type=Path,
        default=None,
        help="the journal of the run being resumed; default: the newest one in the run dir",
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

        # Resolved before this run opens a journal of its own, so that "the newest journal in
        # the run directory" cannot mean the empty one this process just created.
        baseline: Dict[str, Any] = {}
        standstill: Dict[str, Any] = {}
        if args.start_at > 1:
            say()
            say(f"  --start-at {args.start_at}: steps 1 to {args.start_at - 1} are being skipped.")
            baseline, standstill = resume_context(
                args.run_dir, args.journal, tools, args.start_at, args.dsn
            )

        journal = Journal(
            args.run_dir / f"t020-run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json",
            tools["host"],
        )
        journal.record(
            0,
            "preflight",
            identity=tools["identity"],
            **{key: tools[key] for key in ("host", "database", "user", "server_version")},
        )

        if args.start_at <= 1:
            standstill = step_quiesce(tools, args.dsn, journal, args.assume_quiesced)
        if args.start_at <= 2:
            step_snapshot(tools, args.dsn, args.run_dir, journal, args.snapshot, standstill)
        if args.start_at <= 3:
            baseline = step_baseline(args.dsn, args.run_dir, journal, standstill)

        if args.start_at <= 4:
            step_schema(tools, args.dsn, journal)
        if args.start_at <= 5:
            step_dry_run(args.dsn, baseline, journal)
        if args.start_at <= 6:
            # The last thing measured before the only step that writes. Everything after this
            # line is recoverable only from the snapshot, so the snapshot has to still describe
            # the corpus -- and step 6 must not start if it does not.
            require_standstill(args.dsn, standstill, "between the snapshot and the write")
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
        outcome = interrupted_message(journal)
        if journal is not None:
            journal.record(-1, "interrupted", reason=str(interrupt) or "Ctrl-C")
            say(f"  Journal: {shown(journal.path)}")
        say(outcome)
        return 2


if __name__ == "__main__":
    sys.exit(main())
