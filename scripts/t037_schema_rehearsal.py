#!/usr/bin/env python
"""Rehearse the research-workspace schema on a throwaway database, and publish what it proved.

`sql/017_research_workspace.sql` adds the workspace boundary, the two surfaces, the immutable
Brief revision, the run journal and the writer claim. It claims to add all of that *around*
sources, observations and mission_evidence without touching any of them. That claim is worth
exactly as much as the evidence behind it, so this rehearses the migration somewhere nothing is
at stake and measures the corpus on both sides of it.

Two modes, and the difference between them is the safety property:

  inspect    the default. Reads a target and reports what is already there. It opens nothing for
             writing and applies nothing, so pointing it at a real configured database is safe
             and is the intended way to find out whether that database has the schema yet.

  rehearse   writes -- and has no target argument at all. It mints its own scratch database,
             applies the migrations into that, measures, and drops it. There is no flag that
             makes this mode write anywhere an operator names, which is the only version of
             "it cannot touch production" that does not depend on reading the flag correctly.

What the rehearsal measures, in order: the migration files and their SHA-256; the legacy corpus
before the migration; the migration applied; the legacy corpus after it, compared member by
member; every object `sql/017` introduces, its foreign keys and their ON DELETE actions; every
constraint the contract names, probed by trying to violate it rather than by reading its text;
a workspace created through the real use case; and the scratch database dropped.

The legacy digests come from the reconciliation audit's own projection, imported rather than
restated. A second way of hashing one corpus disagrees with the first for reasons that have
nothing to do with the data.

Usage:
    .venv/bin/python scripts/t037_schema_rehearsal.py
    .venv/bin/python scripts/t037_schema_rehearsal.py --mode rehearse --confirm-scratch
    .venv/bin/python scripts/t037_schema_rehearsal.py --mode rehearse --confirm-scratch \
        --backend postgres --json-out .handoff/t037-rehearsal.json
    .venv/bin/python scripts/t037_schema_rehearsal.py --mode inspect --dsn sqlite:///ignis.db

The PostgreSQL rehearsal needs IGNIS_TEST_POSTGRES_DSN, and uses it only to create and drop its
own `ignis_rehearsal_<uuid>` database. DATABASE_URL is never read. No DSN is ever printed.

Exit codes: 0 every check passed, 1 a check failed, 2 could not run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

SQL_DIR = REPO / "sql"
MIGRATION_UNDER_REHEARSAL = "017_research_workspace.sql"

# The order the repository's own schema contract applies. Mirrored by
# tests/unit/test_t037_schema_rehearsal.py against tests/integration/conftest.py, so the two
# cannot drift apart without a test saying so.
SCHEMA_MIGRATIONS: Tuple[str, ...] = (
    "001_initial_schema.sql",
    "002_platform_credentials.sql",
    "008_deduplicate_signal_metrics.sql",
    "015_split_published_at.sql",
    "016_source_observation_model.sql",
    "017_research_workspace.sql",
)

# The sets the reconciliation audit conserves. Named the way it names them.
CANONICAL_SETS = ("sources", "observations", "mission_associations", "cluster_memberships")

# What 017 must leave alone. Counted before and after, on top of the digests.
UNTOUCHED_TABLES = ("sources", "observations", "mission_evidence")

SCRATCH_PREFIX = "ignis_rehearsal_"
# Matched in full, not by prefix. A prefix test would accept `ignis_rehearsal_production`.
SCRATCH_PATTERN = SCRATCH_PREFIX + "[0-9a-f]{32}"


class Unrunnable(Exception):
    """The rehearsal could not start. Exit 2, not a failed check."""


# ---------------------------------------------------------------------------
# What sql/017 has to have produced
# ---------------------------------------------------------------------------

TABLES_INTRODUCED = (
    "research_workspaces",
    "market_brief_revisions",
    "mission_run_journals",
    "mission_writer_claims",
)

COLUMNS_ADDED = {
    "research_missions": (
        "workspace_id",
        "surface",
        "parent_attention_mission_id",
        "parent_cluster_id",
        "brief_revision_id",
        "revises_mission_id",
    ),
}

# (table, column) -> (referenced table, ON DELETE action). Structural rather than by constraint
# name: SQLite states these inline and unnamed, and the contract is the action, not the label.
FOREIGN_KEYS = {
    ("research_missions", "workspace_id"): ("research_workspaces", "CASCADE"),
    ("research_missions", "parent_attention_mission_id"): ("research_missions", "SET NULL"),
    ("research_missions", "parent_cluster_id"): ("topic_clusters", "SET NULL"),
    ("research_missions", "revises_mission_id"): ("research_missions", "SET NULL"),
    ("market_brief_revisions", "workspace_id"): ("research_workspaces", "CASCADE"),
    ("market_brief_revisions", "mission_id"): ("research_missions", "CASCADE"),
    ("mission_run_journals", "workspace_id"): ("research_workspaces", "CASCADE"),
    ("mission_run_journals", "mission_id"): ("research_missions", "CASCADE"),
    ("mission_writer_claims", "mission_id"): ("research_missions", "CASCADE"),
}

# table -> the column tuples that must be unique, primary keys included. These are the scope
# rules: one Brief per Market mission, one revision number per research, one journal per path,
# one writer per mission, one slug per host folder.
UNIQUE_KEYS = {
    "research_workspaces": {("id",), ("root_path", "slug")},
    "market_brief_revisions": {("id",), ("mission_id",), ("workspace_id", "revision_number")},
    "mission_run_journals": {("id",), ("journal_path",)},
    "mission_writer_claims": {("mission_id",)},
}

# table -> the leading column of an index that has to exist for the workspace-scoped reads.
INDEXED_LEADING_COLUMNS = {
    "research_missions": "workspace_id",
    "research_workspaces": "slug",
    "market_brief_revisions": "workspace_id",
    "mission_run_journals": "mission_id",
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

    def payload(self) -> Dict[str, Any]:
        return {"check": self.name, "result": "PASS" if self.passed else "FAIL",
                "detail": self.detail}


@dataclass
class Record:
    """The evidence record. Everything the operator review needs, and no DSN anywhere in it."""

    mode: str
    backend: str
    started_at: str = field(default_factory=lambda: _now())
    target: Dict[str, Any] = field(default_factory=dict)
    migrations: List[Dict[str, str]] = field(default_factory=list)
    corpus: Dict[str, Any] = field(default_factory=dict)
    schema: Dict[str, Any] = field(default_factory=dict)
    checks: List[Check] = field(default_factory=list)
    cleanup: Dict[str, Any] = field(default_factory=dict)
    disposition: Dict[str, Any] = field(default_factory=dict)

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, passed, detail))
        return passed

    @property
    def failed(self) -> List[Check]:
        return [c for c in self.checks if not c.passed]

    def payload(self) -> Dict[str, Any]:
        return {
            "task": "T037",
            "mode": self.mode,
            "backend": self.backend,
            "started_at": self.started_at,
            "finished_at": _now(),
            "target": self.target,
            "migrations": self.migrations,
            "corpus": self.corpus,
            "schema": self.schema,
            "checks": [c.payload() for c in self.checks],
            "cleanup": self.cleanup,
            "disposition": self.disposition,
            "result": "FAILED" if self.failed else "PASSED",
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def migration_inventory() -> List[Dict[str, str]]:
    """Every migration the rehearsal applies, in order, with its own identity.

    The SHA-256 is what makes "017 was rehearsed" mean a specific file rather than a filename.
    """
    inventory = []
    for position, name in enumerate(SCHEMA_MIGRATIONS, 1):
        path = SQL_DIR / name
        if not path.is_file():
            raise Unrunnable(f"Migration {name} is named by the schema contract but is missing.")
        inventory.append({
            "order": position,
            "file": name,
            "sha256": sha256_of(path),
            "under_rehearsal": name == MIGRATION_UNDER_REHEARSAL,
        })
    return inventory


# ---------------------------------------------------------------------------
# Targets. A target names itself without naming its credentials.
# ---------------------------------------------------------------------------

def describe_sqlite_target(path: Path, scratch: bool) -> Dict[str, Any]:
    """Enough to tell two databases apart, and nothing that could open either."""
    return {
        "backend": "sqlite",
        "database": path.name,
        "scratch": scratch,
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def describe_postgres_target(connection: Any, scratch: bool) -> Dict[str, Any]:
    """Database and schema identity read from the server, never from the DSN text."""
    name, schema, version = connection.execute(
        "SELECT current_database(), current_schema(), current_setting('server_version')"
    ).fetchone()
    return {
        "backend": "postgres",
        "database": name,
        "schema": schema,
        "server_version": version,
        "scratch": scratch,
    }


def is_scratch_name(database: str) -> bool:
    import re

    return re.fullmatch(SCRATCH_PATTERN, database or "") is not None


# ---------------------------------------------------------------------------
# Introspection. One normalized shape from two very different catalogs.
# ---------------------------------------------------------------------------

class Introspector:
    """The schema as the database actually holds it."""

    def tables(self) -> List[str]:
        raise NotImplementedError

    def columns(self, table: str) -> List[str]:
        raise NotImplementedError

    def foreign_keys(self, table: str) -> Dict[str, Tuple[str, str]]:
        """column -> (referenced table, ON DELETE action), action upper-cased."""
        raise NotImplementedError

    def unique_keys(self, table: str) -> set:
        """Every column tuple the database enforces as unique, primary key included."""
        raise NotImplementedError

    def index_leading_columns(self, table: str) -> set:
        raise NotImplementedError

    def count(self, table: str) -> int:
        raise NotImplementedError


class SqliteIntrospector(Introspector):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._c = connection

    def tables(self) -> List[str]:
        return sorted(
            r[0] for r in self._c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )

    def columns(self, table: str) -> List[str]:
        return [r[1] for r in self._c.execute(f"PRAGMA table_info({table})")]

    def foreign_keys(self, table: str) -> Dict[str, Tuple[str, str]]:
        out = {}
        for row in self._c.execute(f"PRAGMA foreign_key_list({table})"):
            # id, seq, table, from, to, on_update, on_delete, match
            out[row[3]] = (row[2], (row[6] or "NO ACTION").upper())
        return out

    def unique_keys(self, table: str) -> set:
        keys = set()
        pk = tuple(
            r[1] for r in sorted(
                (r for r in self._c.execute(f"PRAGMA table_info({table})") if r[5]),
                key=lambda r: r[5],
            )
        )
        if pk:
            keys.add(pk)
        for index in self._c.execute(f"PRAGMA index_list({table})"):
            if not index[2]:
                continue
            columns = tuple(r[2] for r in self._c.execute(f"PRAGMA index_info({index[1]})"))
            keys.add(columns)
        return keys

    def index_leading_columns(self, table: str) -> set:
        leading = set()
        for index in self._c.execute(f"PRAGMA index_list({table})"):
            info = list(self._c.execute(f"PRAGMA index_info({index[1]})"))
            if info:
                leading.add(info[0][2])
        return leading

    def count(self, table: str) -> int:
        return self._c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class PostgresIntrospector(Introspector):
    def __init__(self, connection: Any) -> None:
        self._c = connection

    def tables(self) -> List[str]:
        return sorted(
            r[0] for r in self._c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            ).fetchall()
        )

    def columns(self, table: str) -> List[str]:
        return [
            r[0] for r in self._c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s "
                "ORDER BY ordinal_position",
                (table,),
            ).fetchall()
        ]

    def foreign_keys(self, table: str) -> Dict[str, Tuple[str, str]]:
        rows = self._c.execute(
            """
            SELECT att.attname, cl.relname, con.confdeltype
            FROM pg_constraint con
            JOIN pg_class src ON src.oid = con.conrelid
            JOIN pg_class cl ON cl.oid = con.confrelid
            JOIN unnest(con.conkey) AS k(attnum) ON true
            JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k.attnum
            WHERE con.contype = 'f' AND src.relname = %s
            """,
            (table,),
        ).fetchall()
        actions = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL",
                   "d": "SET DEFAULT"}
        return {r[0]: (r[1], actions.get(r[2], r[2].upper())) for r in rows}

    def unique_keys(self, table: str) -> set:
        rows = self._c.execute(
            """
            SELECT con.conkey, con.conrelid
            FROM pg_constraint con
            JOIN pg_class src ON src.oid = con.conrelid
            WHERE con.contype IN ('p', 'u') AND src.relname = %s
            """,
            (table,),
        ).fetchall()
        keys = set()
        for conkey, relid in rows:
            names = []
            for attnum in conkey:
                names.append(
                    self._c.execute(
                        "SELECT attname FROM pg_attribute WHERE attrelid = %s AND attnum = %s",
                        (relid, attnum),
                    ).fetchone()[0]
                )
            keys.add(tuple(names))
        return keys

    def index_leading_columns(self, table: str) -> set:
        rows = self._c.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = %s",
            (table,),
        ).fetchall()
        leading = set()
        for (definition,) in rows:
            inside = definition.split("(", 1)[1].rsplit(")", 1)[0]
            leading.add(inside.split(",")[0].strip().split(" ")[0].strip('"'))
        return leading

    def count(self, table: str) -> int:
        return self._c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def verify_schema(record: Record, introspector: Introspector) -> None:
    """Every object sql/017 introduces, and every scope rule it is supposed to enforce."""
    tables = introspector.tables()
    record.schema["tables_present"] = [t for t in TABLES_INTRODUCED if t in tables]
    record.check(
        "017.tables_present",
        all(t in tables for t in TABLES_INTRODUCED),
        f"missing: {[t for t in TABLES_INTRODUCED if t not in tables]}",
    )

    for table, expected in COLUMNS_ADDED.items():
        present = introspector.columns(table)
        record.schema[f"columns_added.{table}"] = [c for c in expected if c in present]
        record.check(
            f"017.columns_added.{table}",
            all(c in present for c in expected),
            f"missing: {[c for c in expected if c not in present]}",
        )

    observed_fks: Dict[str, Any] = {}
    fk_failures = []
    for (table, column), (referenced, action) in FOREIGN_KEYS.items():
        found = introspector.foreign_keys(table).get(column)
        observed_fks[f"{table}.{column}"] = (
            {"references": found[0], "on_delete": found[1]} if found else None
        )
        if found != (referenced, action):
            fk_failures.append(f"{table}.{column}: expected {referenced}/{action}, found {found}")
    record.schema["foreign_keys"] = observed_fks
    record.check("017.foreign_keys_and_on_delete", not fk_failures, "; ".join(fk_failures))

    unique_failures = []
    observed_unique = {}
    for table, expected in UNIQUE_KEYS.items():
        found = introspector.unique_keys(table)
        observed_unique[table] = sorted(list(k) for k in found)
        missing = [k for k in expected if k not in found]
        if missing:
            unique_failures.append(f"{table}: missing {missing}")
    record.schema["unique_keys"] = observed_unique
    record.check("017.unique_constraints", not unique_failures, "; ".join(unique_failures))

    index_failures = []
    observed_indexes = {}
    for table, leading in INDEXED_LEADING_COLUMNS.items():
        found = introspector.index_leading_columns(table)
        observed_indexes[table] = sorted(found)
        if leading not in found:
            index_failures.append(f"{table}: no index leading on {leading}")
    record.schema["index_leading_columns"] = observed_indexes
    record.check("017.workspace_scoped_indexes", not index_failures, "; ".join(index_failures))


# ---------------------------------------------------------------------------
# Constraint probes. A CHECK is proved by being unable to break it.
# ---------------------------------------------------------------------------

@dataclass
class Probe:
    name: str
    statement: str
    params: Tuple[Any, ...] = ()


def probe_constraints(record: Record, runner) -> None:
    """Try each forbidden write once. Every one of them has to be refused.

    Probed rather than read out of the catalog because the text of a constraint is not the
    contract -- being unable to write the row is. The two backends spell these differently and
    have to refuse the same writes.
    """
    for probe in runner.forbidden_writes():
        refused, detail = runner.refuses(probe)
        record.check(f"constraint.{probe.name}", refused, detail)

    for name, holds, detail in runner.referential_actions():
        record.check(f"referential.{name}", holds, detail)


# ---------------------------------------------------------------------------
# The rehearsal itself
# ---------------------------------------------------------------------------

def legacy_corpus(dsn: str = "", connection: Any = None) -> Dict[str, Any]:
    """The four conserved sets, hashed by the audit's own projection."""
    import migration_reconciliation_audit as audit_module

    reader = audit_module.open_reader(dsn, connection=connection)
    try:
        report = audit_module.audit(reader)
    finally:
        reader.close()
    return {
        "digests": {name: report["digests"][name] for name in CANONICAL_SETS},
        "member_counts": {
            name: report["digests"]["member_counts"][name] for name in CANONICAL_SETS
        },
    }


def corpus_drift(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    moved = []
    for name in CANONICAL_SETS:
        was, became = before["member_counts"][name], after["member_counts"][name]
        if was != became:
            moved.append(f"{name}: {was} members became {became}")
        elif before["digests"][name] != after["digests"][name]:
            moved.append(f"{name}: {was} members both times, different digest")
    return moved


async def create_a_workspace(dsn: str, host_root: Path) -> Dict[str, Any]:
    """Prove the migrated schema can hold a research, through the real use case.

    The repository and the use case, not hand-written INSERTs: a schema that accepts a crafted
    row and rejects what the product writes has not been rehearsed.
    """
    from ignis.application.use_cases.create_research_workspace import (
        CreateResearchWorkspaceUseCase,
    )
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

    repository = _repository_for(dsn)
    store = WorkspaceRepository(repository=repository)
    try:
        use_case = CreateResearchWorkspaceUseCase(store=store)
        proposal = await use_case.propose(host_root, "Rehearsal research")
        before_exists = proposal.proposed_path.exists()
        workspace = await use_case.confirm(proposal, confirmation=True)
        reopened = await store.get_research_workspace(workspace.workspace_id)
        stray = [
            p.name for p in host_root.rglob("*")
            if p.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
        ]
        return {
            "proposal_wrote_nothing": not before_exists,
            "workspace_created": workspace is not None,
            "manifest_written": workspace.manifest_path.is_file(),
            "readable_from_the_shared_database": reopened is not None
            and reopened.workspace_id == workspace.workspace_id,
            "per_research_database_files": stray,
        }
    finally:
        await repository.close()


def _repository_for(dsn: str):
    if dsn.startswith("sqlite"):
        from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

        return SqliteTrendRepository(db_path=dsn)
    from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository

    return PostgresTimescaleRepository(dsn=dsn)


# ---------------------------------------------------------------------------
# A deterministic legacy corpus, so "unchanged" is a measurement and not a tautology
# ---------------------------------------------------------------------------

# Fixed identifiers and fixed timestamps. The point of the fixture is that two rehearsals of the
# same migration hash the same corpus; anything generated per run would make the digests describe
# the run rather than the migration.
FIXTURE_MISSION = "11111111-1111-4111-8111-111111111111"
FIXTURE_CLUSTER = "22222222-2222-4222-8222-222222222222"
FIXTURE_AT = "2026-01-01T00:00:00+00:00"

FIXTURE_SIGNALS = (
    # id, platform, raw_title, url, metadata, metric, velocity
    (9001, "youtube", "Fixture video one",
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ", {"video_id": "dQw4w9WgXcQ"}, 1000.0, 5.0),
    (9002, "youtube", "Fixture video one, retitled",
     "https://www.youtube.com/watch?v=dQw4w9WgXcQ", {}, 1100.0, 6.0),
    (9003, "google", "Google Search Trends: fixture keyword",
     None, {"keyword": "fixture keyword"}, 77.0, 1.5),
)

FIXTURE_METRICS = (
    (8001, 9001, 1000.0, 5.0),
    (8002, 9001, 1050.0, 5.5),
)

# The migrated half of the corpus, seeded alongside the legacy half. It is here because 017
# claims to leave source identity, observation immutability and the mission ledger alone, and a
# claim about three empty tables is not worth measuring. It also satisfies the repository's own
# refusal to open a database holding legacy rows and no observations.
FIXTURE_SOURCE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
FIXTURE_OBSERVATION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
FIXTURE_EVIDENCE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class Backend:
    """One scratch database, and everything that has to be spelled differently on each engine."""

    name = "unset"
    placeholder = "?"

    def introspector(self) -> Introspector:
        raise NotImplementedError

    def execute(self, statement: str, params: Sequence[Any] = ()) -> Any:
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError

    def error_types(self) -> Tuple[type, ...]:
        raise NotImplementedError

    def seed_legacy_fixture(self) -> None:
        raise NotImplementedError

    # -- probes ----------------------------------------------------------

    def forbidden_writes(self) -> List[Probe]:
        raise NotImplementedError

    def refuses(self, probe: Probe) -> Tuple[bool, str]:
        """True when the database refused the write. The row must not survive either way."""
        try:
            self.execute(probe.statement, probe.params)
        except self.error_types() as exc:
            self.rollback()
            # The message, not just the type: a write refused by an unrelated foreign key would
            # otherwise read as the constraint under test doing its job.
            return True, f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
        self.rollback()
        return False, "the database accepted a write the contract forbids"

    def referential_actions(self) -> List[Tuple[str, bool, str]]:
        raise NotImplementedError


def _probe_fixture_ids() -> Dict[str, str]:
    """Identifiers the probes build their scaffolding from. Fixed, for the same reason."""
    return {
        "workspace": "33333333-3333-4333-8333-333333333333",
        "attention": "44444444-4444-4444-8444-444444444444",
        "market": "55555555-5555-4555-8555-555555555555",
        "revision": "66666666-6666-4666-8666-666666666666",
        "journal": "77777777-7777-4777-8777-777777777777",
        "spare": "88888888-8888-4888-8888-888888888888",
        "run": "99999999-9999-4999-8999-999999999999",
    }


class RehearsalBackend(Backend):
    """The statements both engines are measured with, written once.

    The fixture, the scaffolding and every probe live here so that a contract proved on one
    backend is literally the same contract proved on the other. What differs -- placeholders,
    array encoding, the exception a violated constraint raises -- is named and overridden.
    """

    def array(self, values: Sequence[str]) -> Any:
        raise NotImplementedError

    def json_obj(self, value: Dict[str, Any]) -> Any:
        raise NotImplementedError

    def seed_legacy_fixture(self) -> None:
        self.execute(
            "INSERT INTO research_missions (id, title, keywords, platforms, status, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (FIXTURE_MISSION, "Fixture mission", self.array(["fixture"]),
             self.array(["google"]), "COMPLETED", FIXTURE_AT, FIXTURE_AT),
        )
        self.execute(
            "INSERT INTO topic_clusters (id, canonical_name, category, cross_platform_score,"
            " first_seen_at, last_updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (FIXTURE_CLUSTER, "fixture cluster", "general", 50.0, FIXTURE_AT, FIXTURE_AT),
        )
        for sid, platform, title, url, metadata, value, velocity in FIXTURE_SIGNALS:
            self.execute(
                "INSERT INTO trend_signals (id, platform, raw_title, source_url, metadata,"
                " metric_value, growth_velocity, geo_code, mission_id, cluster_id, captured_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, platform, title, url, self.json_obj(metadata), value, velocity, "VN",
                 FIXTURE_MISSION, FIXTURE_CLUSTER, FIXTURE_AT),
            )
        for mid, sid, value, velocity in FIXTURE_METRICS:
            self.execute(
                "INSERT INTO signal_metrics (id, signal_id, captured_at, metric_value,"
                " growth_velocity) VALUES (?, ?, ?, ?, ?)",
                (mid, sid, FIXTURE_AT, value, velocity),
            )
        self.execute(
            "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)",
            (FIXTURE_SOURCE, "youtube", "youtube:video:dQw4w9WgXcQ"),
        )
        self.execute(
            "INSERT INTO observations (id, source_id, cluster_id, observed_at,"
            " time_provenance, identity_source, observed_title, metric_value, growth_velocity,"
            " geo_code, source_url, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (FIXTURE_OBSERVATION, FIXTURE_SOURCE, FIXTURE_CLUSTER, FIXTURE_AT,
             "exact_ingestion", "metadata_external_id", "Fixture video one", 1000.0, 5.0, "VN",
             "https://www.youtube.com/watch?v=dQw4w9WgXcQ", self.json_obj({})),
        )
        self.execute(
            "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
            " VALUES (?, ?, ?, ?)",
            (FIXTURE_EVIDENCE, FIXTURE_MISSION, FIXTURE_OBSERVATION, FIXTURE_AT),
        )
        self.commit()

    def build_probe_scaffolding(self) -> None:
        ids = _probe_fixture_ids()
        self.execute(
            "INSERT INTO research_workspaces (id, slug, name, root_path, format_version, status,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ids["workspace"], "rehearsal", "Rehearsal", "/tmp/rehearsal", 1, "READY",
             FIXTURE_AT),
        )
        for key, surface in (("attention", "ATTENTION"), ("market", "MARKET")):
            self.execute(
                "INSERT INTO research_missions (id, title, keywords, platforms, status,"
                " workspace_id, surface, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ids[key], f"{surface} mission", self.array([]), self.array([]), "PENDING",
                 ids["workspace"], surface, FIXTURE_AT, FIXTURE_AT),
            )
        self.execute(
            "INSERT INTO market_brief_revisions (id, workspace_id, mission_id, revision_number,"
            " decision, target_user, problem, geo, timeframe, hypothesis, falsifiers,"
            " confirmed_by, confirmed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ids["revision"], ids["workspace"], ids["market"], 1, "d", "t", "p", "VN", "30d",
             "h", self.array(["f"]), "requester", FIXTURE_AT),
        )
        self.execute(
            "INSERT INTO mission_run_journals (id, workspace_id, mission_id, journal_path,"
            " sequence, status, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ids["journal"], ids["workspace"], ids["market"], "/tmp/run-001.json", 1, "STARTED",
             FIXTURE_AT),
        )
        self.execute(
            "INSERT INTO mission_writer_claims (mission_id, run_id, claimed_at)"
            " VALUES (?, ?, ?)",
            (ids["market"], ids["run"], FIXTURE_AT),
        )
        self.commit()

    def forbidden_writes(self) -> List[Probe]:
        ids = _probe_fixture_ids()
        mission = (
            "INSERT INTO research_missions (id, title, keywords, platforms, workspace_id,"
            " surface, brief_revision_id, revises_mission_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        empty = self.array([])
        return [
            Probe("surface_is_attention_or_market", mission,
                  (ids["spare"], "x", empty, empty, ids["workspace"], "SOMETHING", None, None,
                   FIXTURE_AT, FIXTURE_AT)),
            Probe("attention_carries_no_brief", mission,
                  (ids["spare"], "x", empty, empty, ids["workspace"], "ATTENTION",
                   ids["revision"], None, FIXTURE_AT, FIXTURE_AT)),
            Probe("attention_revises_nothing", mission,
                  (ids["spare"], "x", empty, empty, ids["workspace"], "ATTENTION", None,
                   ids["market"], FIXTURE_AT, FIXTURE_AT)),
            Probe("a_mission_cannot_revise_itself", mission,
                  (ids["spare"], "x", empty, empty, ids["workspace"], "MARKET", None,
                   ids["spare"], FIXTURE_AT, FIXTURE_AT)),
            Probe("workspace_status_is_known",
                  "INSERT INTO research_workspaces (id, slug, name, root_path, format_version,"
                  " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (ids["spare"], "other", "Other", "/tmp/other", 1, "WHATEVER", FIXTURE_AT)),
            Probe("one_research_per_folder_and_slug",
                  "INSERT INTO research_workspaces (id, slug, name, root_path, format_version,"
                  " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (ids["spare"], "rehearsal", "Duplicate", "/tmp/rehearsal", 1, "READY",
                   FIXTURE_AT)),
            Probe("a_brief_needs_a_falsifier",
                  "INSERT INTO market_brief_revisions (id, workspace_id, mission_id,"
                  " revision_number, decision, target_user, problem, geo, timeframe, hypothesis,"
                  " falsifiers, confirmed_by, confirmed_at)"
                  " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (ids["spare"], ids["workspace"], ids["attention"], 2, "d", "t", "p", "VN",
                   "30d", "h", self.array([]), "requester", FIXTURE_AT)),
            Probe("one_confirmed_brief_per_mission",
                  "INSERT INTO market_brief_revisions (id, workspace_id, mission_id,"
                  " revision_number, decision, target_user, problem, geo, timeframe, hypothesis,"
                  " falsifiers, confirmed_by, confirmed_at)"
                  " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (ids["spare"], ids["workspace"], ids["market"], 2, "d", "t", "p", "VN", "30d",
                   "h", self.array(["f"]), "requester", FIXTURE_AT)),
            Probe("one_revision_number_per_research",
                  "INSERT INTO market_brief_revisions (id, workspace_id, mission_id,"
                  " revision_number, decision, target_user, problem, geo, timeframe, hypothesis,"
                  " falsifiers, confirmed_by, confirmed_at)"
                  " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (ids["spare"], ids["workspace"], ids["attention"], 1, "d", "t", "p", "VN",
                   "30d", "h", self.array(["f"]), "requester", FIXTURE_AT)),
            Probe("one_journal_per_path",
                  "INSERT INTO mission_run_journals (id, workspace_id, mission_id, journal_path,"
                  " sequence, status, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (ids["spare"], ids["workspace"], ids["market"], "/tmp/run-001.json", 2,
                   "STARTED", FIXTURE_AT)),
            Probe("one_writer_per_mission",
                  "INSERT INTO mission_writer_claims (mission_id, run_id, claimed_at)"
                  " VALUES (?, ?, ?)",
                  (ids["market"], ids["spare"], FIXTURE_AT)),
        ]

    def referential_actions(self) -> List[Tuple[str, bool, str]]:
        ids = _probe_fixture_ids()
        results = []

        # A revision outlives the mission it revises: SET NULL, never a cascade.
        self.execute(
            "INSERT INTO research_missions (id, title, keywords, platforms, workspace_id,"
            " surface, revises_mission_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ids["spare"], "Revision", self.array([]), self.array([]), ids["workspace"],
             "MARKET", ids["market"], FIXTURE_AT, FIXTURE_AT),
        )
        self.execute("DELETE FROM research_missions WHERE id = ?", (ids["market"],))
        survivor = self.execute(
            "SELECT revises_mission_id FROM research_missions WHERE id = ?", (ids["spare"],)
        ).fetchone()
        results.append((
            "revising_mission_survives_the_mission_it_revised",
            survivor is not None and survivor[0] is None,
            f"revises_mission_id after the delete: {survivor[0] if survivor else 'row gone'}",
        ))

        # Everything scoped to a research goes with it.
        self.execute("DELETE FROM research_workspaces WHERE id = ?", (ids["workspace"],))
        remaining = {
            table: self.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace_id = ?", (ids["workspace"],)
            ).fetchone()[0]
            for table in ("research_missions", "market_brief_revisions", "mission_run_journals")
        }
        remaining["mission_writer_claims"] = self.execute(
            "SELECT COUNT(*) FROM mission_writer_claims"
        ).fetchone()[0]
        results.append((
            "deleting_a_research_takes_its_scoped_rows_with_it",
            all(count == 0 for count in remaining.values()),
            json.dumps(remaining),
        ))
        self.commit()
        return results


class SqliteBackend(RehearsalBackend):
    """The scratch file the rehearsal made for itself, and nothing else.

    SQLite has no `sql/017` to execute: the repository restates the whole schema in
    `_ensure_schema` on every connection, so what a SQLite-local install actually runs is the
    restatement. That is what this rehearses, and the record says so rather than implying the
    migration file was executed here.
    """

    name = "sqlite"
    placeholder = "?"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def dsn(self) -> str:
        return f"sqlite:///{self.path}"

    def array(self, values: Sequence[str]) -> Any:
        return json.dumps(list(values))

    def json_obj(self, value: Dict[str, Any]) -> Any:
        return json.dumps(value)

    def open(self) -> None:
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def apply_files(self, names: Sequence[str]) -> None:
        """Let the repository state the schema, which is how a SQLite install gets it.

        The file list is ignored: the restatement is one operation and cannot be stopped
        partway, which is why the SQLite rehearsal proves idempotency rather than ordering.
        """
        from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

        async def build() -> None:
            repository = SqliteTrendRepository(db_path=self.dsn)
            await repository.list_research_workspaces(1)
            await repository.close()

        asyncio.run(build())

    def describe(self, scratch: bool) -> Dict[str, Any]:
        return describe_sqlite_target(self.path, scratch)

    def introspector(self) -> Introspector:
        return SqliteIntrospector(self._conn)

    def execute(self, statement: str, params: Sequence[Any] = ()) -> Any:
        return self._conn.execute(statement, tuple(params))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def error_types(self) -> Tuple[type, ...]:
        return (sqlite3.IntegrityError,)


class PostgresBackend(RehearsalBackend):
    """A database this process created, migrated file by file, and drops again.

    The admin DSN comes from IGNIS_TEST_POSTGRES_DSN and is used for exactly two statements:
    CREATE DATABASE and DROP DATABASE, both naming `ignis_rehearsal_<uuid>`. It is never printed
    and never stored in the record.
    """

    name = "postgres"
    placeholder = "%s"

    def __init__(self, admin_dsn: str) -> None:
        self._admin_dsn = admin_dsn
        self.database = SCRATCH_PREFIX + uuid.uuid4().hex
        self._conn: Any = None

    @property
    def dsn(self) -> str:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        parts = conninfo_to_dict(self._admin_dsn)
        parts["dbname"] = self.database
        return make_conninfo(**parts)

    def array(self, values: Sequence[str]) -> Any:
        return list(values)

    def json_obj(self, value: Dict[str, Any]) -> Any:
        return json.dumps(value)

    def create(self) -> None:
        import psycopg
        from psycopg import sql

        if not is_scratch_name(self.database):
            raise Unrunnable(f"{self.database} is not a scratch database name.")
        with psycopg.connect(self._admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database)))

    def drop(self) -> Dict[str, Any]:
        """Drop the scratch database and read back that it is gone."""
        import psycopg
        from psycopg import sql

        if not is_scratch_name(self.database):
            raise Unrunnable(f"refusing to drop {self.database}: not a scratch database name.")
        with psycopg.connect(self._admin_dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(self.database)
                )
            )
            leftovers = [
                r[0] for r in admin.execute(
                    "SELECT datname FROM pg_database WHERE datname LIKE %s",
                    (SCRATCH_PREFIX + "%",),
                ).fetchall()
            ]
        return {"dropped": self.database, "scratch_databases_remaining": leftovers}

    def open(self) -> None:
        import psycopg

        self._conn = psycopg.connect(self.dsn)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def apply_files(self, names: Sequence[str]) -> None:
        """Run exactly these migration files, in the order given.

        Splitting the run is what makes the rehearsal a measurement rather than an assertion:
        the legacy corpus is seeded and hashed with everything up to 016 in place, and only
        then does 017 execute.
        """
        import psycopg

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            for name in names:
                conn.execute((SQL_DIR / name).read_text(encoding="utf-8"))

    def describe(self, scratch: bool) -> Dict[str, Any]:
        return describe_postgres_target(self._conn, scratch)

    def introspector(self) -> Introspector:
        return PostgresIntrospector(self._conn)

    def execute(self, statement: str, params: Sequence[Any] = ()) -> Any:
        return self._conn.execute(statement.replace("?", "%s"), tuple(params))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def error_types(self) -> Tuple[type, ...]:
        import psycopg

        return (psycopg.errors.IntegrityError,)


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

BEFORE_017 = tuple(n for n in SCHEMA_MIGRATIONS if n != MIGRATION_UNDER_REHEARSAL)


def inspect(dsn: str) -> Record:
    """Read a target and report what is already there. Opens nothing for writing.

    This is the mode that may be pointed at a real configured database. It applies no file,
    creates no table and writes no row; the only thing it produces is the record.
    """
    record = Record(mode="inspect", backend="sqlite" if dsn.startswith("sqlite") else "postgres")
    record.migrations = migration_inventory()

    if dsn.startswith("sqlite"):
        path = Path(dsn.split("///", 1)[1] if "///" in dsn else dsn.replace("sqlite:", ""))
        if not path.exists():
            raise Unrunnable(f"No SQLite database at {path.name}.")
        record.target = describe_sqlite_target(path, scratch=False)
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        introspector: Introspector = SqliteIntrospector(connection)
        closer = connection.close
    else:
        import psycopg

        connection = psycopg.connect(dsn)
        connection.read_only = True
        record.target = describe_postgres_target(connection, scratch=False)
        introspector = PostgresIntrospector(connection)
        closer = connection.close

    try:
        present = introspector.tables()
        record.schema["tables_present"] = [t for t in TABLES_INTRODUCED if t in present]
        record.schema["migration_applied"] = all(t in present for t in TABLES_INTRODUCED)
        record.corpus = {
            "table_counts": {
                table: introspector.count(table) for table in UNTOUCHED_TABLES if table in present
            }
        }
        record.check(
            "inspect.read_only",
            True,
            "no schema was applied and no row was written",
        )
    finally:
        closer()

    record.disposition = {
        "rehearsal_only": True,
        "production_apply_performed": False,
        "schema_applied_to_this_target": False,
        "note": (
            "inspect mode reports what the target already holds. Applying sql/017 to a "
            "configured database is not part of T037."
        ),
    }
    return record


def rehearse(backend: RehearsalBackend, host_root: Path) -> Record:
    """Seed, measure, migrate, measure again, and prove every rule the migration claims."""
    record = Record(mode="rehearse", backend=backend.name)
    record.migrations = migration_inventory()

    # 1. Everything the migration is supposed to leave alone, in place and hashed.
    backend.apply_files(BEFORE_017)
    backend.open()
    record.target = backend.describe(scratch=True)
    record.check(
        "scratch_target_only",
        bool(record.target.get("scratch")),
        f"target is {record.target.get('database')}",
    )
    backend.seed_legacy_fixture()
    before = legacy_corpus(backend.dsn)
    counts_before = {t: backend.introspector().count(t) for t in UNTOUCHED_TABLES}
    backend.close()

    # 2. The migration under rehearsal, and only it.
    backend.apply_files([MIGRATION_UNDER_REHEARSAL])
    backend.open()

    after = legacy_corpus(backend.dsn)
    counts_after = {t: backend.introspector().count(t) for t in UNTOUCHED_TABLES}
    drift = corpus_drift(before, after)
    record.corpus = {
        "seeded_fixture": True,
        "before": before,
        "after": after,
        "drift": drift,
        "untouched_table_counts": {"before": counts_before, "after": counts_after},
    }
    record.check("corpus.unchanged_by_017", not drift, "; ".join(drift))
    record.check(
        "corpus.untouched_tables_unchanged",
        counts_before == counts_after,
        f"{counts_before} -> {counts_after}",
    )

    # 3. Every object the migration introduces.
    verify_schema(record, backend.introspector())

    # 4. Re-applying it must add nothing. An idempotent migration is what lets a resumed run
    #    finish rather than fork the schema.
    tables_once = set(backend.introspector().tables())
    backend.close()
    backend.apply_files([MIGRATION_UNDER_REHEARSAL])
    backend.open()
    tables_twice = set(backend.introspector().tables())
    record.check(
        "017.reapplying_creates_nothing_new",
        tables_once == tables_twice,
        f"added on the second apply: {sorted(tables_twice - tables_once)}",
    )

    # 5. The rules, proved by being unable to break them.
    backend.build_probe_scaffolding()
    probe_constraints(record, backend)
    backend.close()

    # 6. A research created the way the product creates one.
    workspace_proof = asyncio.run(create_a_workspace(backend.dsn, host_root))
    record.schema["workspace_creation"] = workspace_proof
    record.check(
        "workspace.created_through_the_real_use_case",
        workspace_proof["workspace_created"] and workspace_proof["manifest_written"]
        and workspace_proof["readable_from_the_shared_database"],
        json.dumps(workspace_proof),
    )
    record.check(
        "workspace.no_per_research_database",
        workspace_proof["per_research_database_files"] == [],
        f"found: {workspace_proof['per_research_database_files']}",
    )

    record.disposition = {
        "rehearsal_only": True,
        "production_apply_performed": False,
        "scratch_database": record.target.get("database"),
        "migration_file_executed": backend.name == "postgres",
        "note": (
            "sql/017 was executed as a file only on the PostgreSQL scratch path. The SQLite "
            "rehearsal measures the repository's own schema restatement, which is what a "
            "SQLite-local install runs."
        ),
    }
    return record


def render(record: Record) -> str:
    lines = [
        f"T037 schema rehearsal -- {record.mode} / {record.backend}",
        f"  target        {record.target.get('database', 'unknown')}"
        f" (scratch={record.target.get('scratch')})",
    ]
    under = next(m for m in record.migrations if m["under_rehearsal"])
    lines.append(f"  migration     {under['file']}  sha256={under['sha256']}")
    lines.append(f"  order         {' -> '.join(m['file'] for m in record.migrations)}")
    if record.corpus.get("before"):
        for name in CANONICAL_SETS:
            was = record.corpus["before"]["member_counts"][name]
            became = record.corpus["after"]["member_counts"][name]
            same = record.corpus["before"]["digests"][name] == record.corpus["after"]["digests"][name]
            lines.append(
                f"  corpus        {name:22} {was} -> {became} members,"
                f" digest {'unchanged' if same else 'CHANGED'}"
            )
    for check in record.checks:
        mark = "ok  " if check.passed else "FAIL"
        lines.append(f"  {mark} {check.name}" + (f"  -- {check.detail}" if not check.passed else ""))
    lines.append(
        f"  disposition   rehearsal only, production apply performed: "
        f"{record.disposition.get('production_apply_performed')}"
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mode", choices=("inspect", "rehearse"), default="inspect",
        help="inspect reads a target read-only (default); rehearse writes to its own scratch "
             "database and takes no target",
    )
    parser.add_argument(
        "--dsn", default="",
        help="inspect only. The database to read. Never written to, and never applied to.",
    )
    parser.add_argument(
        "--backend", choices=("sqlite", "postgres"), default="sqlite",
        help="rehearse only. postgres needs IGNIS_TEST_POSTGRES_DSN and executes sql/017 itself.",
    )
    parser.add_argument(
        "--confirm-scratch", action="store_true",
        help="required by rehearse. States that writing to a throwaway database is intended.",
    )
    parser.add_argument("--json-out", default="", help="write the evidence record here")
    args = parser.parse_args(argv)

    try:
        if args.mode == "inspect":
            if not args.dsn:
                raise Unrunnable(
                    "inspect needs --dsn naming the database to read. It is opened read-only "
                    "and nothing is applied to it."
                )
            record = inspect(args.dsn)
        else:
            if args.dsn:
                raise Unrunnable(
                    "rehearse takes no --dsn. It writes only to a scratch database it creates "
                    "itself, which is what keeps it unable to reach a configured one."
                )
            if not args.confirm_scratch:
                raise Unrunnable(
                    "rehearse writes schema. Pass --confirm-scratch to state that a throwaway "
                    "database is what you mean."
                )
            record = run_rehearsal(args.backend)
    except Unrunnable as exc:
        print(f"could not run: {exc}", file=sys.stderr)
        return 2

    print(render(record))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record.payload(), indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(f"  record        {out}")
    return 1 if record.failed else 0


def run_rehearsal(backend_name: str) -> Record:
    """Build the scratch target, rehearse into it, and take it away again."""
    scratch_root = Path(tempfile.mkdtemp(prefix="t037-"))
    host_root = scratch_root / "host"
    host_root.mkdir()
    try:
        if backend_name == "sqlite":
            backend = SqliteBackend(scratch_root / "rehearsal.db")
            record = rehearse(backend, host_root)
            backend.close()
            record.cleanup = {
                "scratch_root_removed": True,
                "scratch_databases_remaining": [],
            }
            return record

        admin_dsn = os.environ.get("IGNIS_TEST_POSTGRES_DSN", "").strip()
        if not admin_dsn:
            raise Unrunnable(
                "IGNIS_TEST_POSTGRES_DSN is not set, so the PostgreSQL rehearsal cannot run. "
                "This is missing coverage, not a passing result. DATABASE_URL is not a "
                "substitute and is never read here."
            )
        backend = PostgresBackend(admin_dsn)
        backend.create()
        try:
            record = rehearse(backend, host_root)
        finally:
            backend.close()
            record_cleanup = backend.drop()
        record.cleanup = {**record_cleanup, "scratch_root_removed": True}
        return record
    finally:
        shutil.rmtree(scratch_root, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
