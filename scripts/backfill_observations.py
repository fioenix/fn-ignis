#!/usr/bin/env python
"""Move the legacy corpus into sources, observations and mission_evidence. One transaction.

The projection is not restated here. Which legacy rows become observations, which clock each
one gets and how a source is identified all come from the modules the audit and the verifier
use, so a green reconciliation means the three agree rather than that they were written on the
same afternoon.

Four properties the implementation is shaped around, each of them a way the migration could
otherwise be unrepeatable or lossy:

  one transaction     a failure halfway leaves all three tables exactly as they were
  deterministic ids   an observation's id comes from the legacy row it stands for, so a second
                      run updates the same rows instead of writing a second corpus
  payload-free ids    two events identical on every field are still two observations; the id
                      comes from lineage, never from content
  database-issued     a source's id is whatever the database returns from the upsert. It may
  source ids          already exist with a random id, written by the live writer before the
                      backfill ran, and assuming the deterministic one would collide with
                      UNIQUE(platform, external_id)

One of --dry-run and --apply is required; neither is implied, because the difference between
planning a migration and performing one should not be a default.

Usage:
    python scripts/backfill_observations.py --dsn "$DATABASE_URL" --dry-run
    python scripts/backfill_observations.py --dsn "$DATABASE_URL" --apply

Exit codes: 0 applied (or dry run complete), 1 refused, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ignis.domain.source_identity import resolve_source_identity  # noqa: E402
from ignis.infrastructure.migration.legacy_projection import (  # noqa: E402
    MetricPoint,
    SignalRow,
    canonical_metadata,
    group_points_by_signal,
    observation_events_for_row,
)

# Fixed namespace, so the same legacy row yields the same observation id on every run, on every
# machine, forever. Changing it would orphan every observation already written.
OBSERVATION_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "fn-ignis.observation.lineage")


class BackfillRefused(Exception):
    """Raised instead of writing something the reconciliation could not later explain."""


def observation_id_for(lineage_table: str, lineage_id: str) -> str:
    """Deterministic from lineage, never from payload.

    Two collection events identical on every conserved field are still two observations, so an
    id derived from content would fuse them. The legacy row they came from is what tells them
    apart, and it is also what makes a second run update rather than duplicate.
    """
    if not lineage_id:
        raise BackfillRefused(
            f"a {lineage_table} event carries no lineage id, so its observation id would not be"
            " reproducible on a second run"
        )
    return str(uuid.uuid5(OBSERVATION_NAMESPACE, f"{lineage_table}:{lineage_id}"))


@dataclass
class PlannedObservation:
    observation_id: str
    identity_key: Tuple[str, str]
    cluster_id: Optional[str]
    observed_at: Optional[str]
    published_at: Optional[str]
    time_provenance: str
    identity_source: str
    observed_title: Optional[str]
    metric_value: Optional[float]
    growth_velocity: Optional[float]
    geo_code: Optional[str]
    source_url: Optional[str]
    metadata: str
    mission_id: Optional[str]


@dataclass
class Plan:
    sources: List[Tuple[str, str]]
    observations: List[PlannedObservation]

    @property
    def evidence_count(self) -> int:
        return sum(1 for o in self.observations if o.mission_id)

    @property
    def cluster_count(self) -> int:
        return sum(1 for o in self.observations if o.cluster_id)


def build_plan(signals: Sequence[SignalRow], points: Sequence[MetricPoint]) -> Plan:
    """Everything the backfill will write, computed before a single row is touched."""
    points_by_signal = group_points_by_signal(points)
    identities: Dict[Tuple[str, str], None] = {}
    planned: List[PlannedObservation] = []

    for row in signals:
        identity = resolve_source_identity(row.platform, row.source_url, row.metadata)
        if identity is None:
            # Never skipped. The corpus has 0 of these and the audit asserts it; one appearing
            # means the identity policy changed under the migration, and a silently dropped row
            # is the failure the reconciliation cannot see.
            raise BackfillRefused(
                f"trend_signals row {row.signal_id} resolves to no external identity"
            )
        key = (identity.platform, identity.external_id)
        identities.setdefault(key, None)

        for event in observation_events_for_row(
            row, identity.canonical_identity, identity.identity_source,
            points_by_signal.get(row.signal_id, []),
        ):
            is_parent = event.lineage_table == "trend_signals"
            planned.append(
                PlannedObservation(
                    observation_id=observation_id_for(event.lineage_table, event.lineage_id),
                    identity_key=key,
                    # Only the parent carries the legacy row's cluster and mission. A metric
                    # point records that the same source was seen again; the legacy schema says
                    # nothing about which cluster that later sighting belonged to, and the
                    # baseline counts one membership per legacy row -- 15,754. Copying the
                    # parent's cluster onto its points would make it 18,391 and the
                    # reconciliation would fail, correctly.
                    cluster_id=row.cluster_id if is_parent else None,
                    observed_at=event.observed_at,
                    published_at=row.published_at,
                    time_provenance=event.time_provenance,
                    identity_source=identity.identity_source,
                    observed_title=row.raw_title,
                    metric_value=event.metric_value,
                    growth_velocity=event.growth_velocity,
                    geo_code=row.geo_code,
                    source_url=row.source_url,
                    metadata=canonical_metadata(row.metadata),
                    mission_id=row.mission_id if is_parent else None,
                )
            )

    duplicates = len(planned) - len({o.observation_id for o in planned})
    if duplicates:
        raise BackfillRefused(
            f"{duplicates} planned observations share an id; lineage is not unique"
        )
    return Plan(sources=list(identities), observations=planned)


# --- backends ---------------------------------------------------------------------------------


class BackfillTarget:
    """One connection, one transaction, both backends."""

    def enforce_read_only(self) -> None:
        """Make a dry run unable to write, rather than merely not writing."""
        raise NotImplementedError

    def legacy_rows(self) -> Tuple[List[SignalRow], List[MetricPoint]]:
        raise NotImplementedError

    def existing_observation_ids(self) -> set:
        raise NotImplementedError

    def upsert_source(self, platform: str, external_id: str) -> str:
        raise NotImplementedError

    def write_observation(self, observation: PlannedObservation, source_id: str) -> None:
        raise NotImplementedError

    def write_evidence(self, mission_id: str, observation_id: str) -> None:
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def _metadata_dict(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


class PostgresTarget(BackfillTarget):
    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=False)

    def enforce_read_only(self) -> None:
        self._conn.execute("SET TRANSACTION READ ONLY")

    def legacy_rows(self):
        signals = [
            SignalRow(
                signal_id=str(r[0]),
                platform=str(r[1]),
                source_url=r[2],
                raw_title=r[3],
                metadata=_metadata_dict(r[4]),
                captured_at=r[5].isoformat() if r[5] else None,
                metric_value=float(r[6]) if r[6] is not None else None,
                mission_id=str(r[7]) if r[7] else None,
                cluster_id=str(r[8]) if r[8] else None,
                growth_velocity=float(r[9]) if r[9] is not None else None,
                geo_code=r[10],
                published_at=r[11].isoformat() if r[11] else None,
            )
            for r in self._conn.execute(
                "SELECT id, platform, source_url, raw_title, metadata, captured_at,"
                " metric_value, mission_id, cluster_id, growth_velocity, geo_code, published_at"
                " FROM trend_signals ORDER BY id"
            )
        ]
        points = [
            MetricPoint(
                signal_id=str(r[0]),
                captured_at=r[1].isoformat() if r[1] else None,
                metric_value=float(r[2]) if r[2] is not None else None,
                growth_velocity=float(r[3]) if r[3] is not None else None,
                metric_id=str(r[4]),
            )
            for r in self._conn.execute(
                "SELECT signal_id, captured_at, metric_value, growth_velocity, id"
                " FROM signal_metrics ORDER BY id"
            )
        ]
        return signals, points

    def existing_observation_ids(self):
        # to_regclass rather than a failed SELECT. Letting the query fail aborts the
        # transaction, and the rollback needed to recover from it discards SET TRANSACTION READ
        # ONLY with everything else -- the dry run would then be writable again, safe only
        # because the code happens not to write afterwards.
        present = self._conn.execute("SELECT to_regclass('public.observations')").fetchone()[0]
        if present is None:
            return None  # sql/016 has not been applied here
        return {str(r[0]) for r in self._conn.execute("SELECT id FROM observations")}

    def upsert_source(self, platform: str, external_id: str) -> str:
        row = self._conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES (%s, %s)"
            " ON CONFLICT (platform, external_id) DO UPDATE SET platform = EXCLUDED.platform"
            " RETURNING id",
            (platform, external_id),
        ).fetchone()
        return str(row[0])

    def write_observation(self, observation: PlannedObservation, source_id: str) -> None:
        self._conn.execute(
            "INSERT INTO observations (id, source_id, cluster_id, observed_at, published_at,"
            " time_provenance, identity_source, observed_title, metric_value, growth_velocity,"
            " geo_code, source_url, metadata)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (id) DO UPDATE SET"
            " source_id = EXCLUDED.source_id, cluster_id = EXCLUDED.cluster_id,"
            " observed_at = EXCLUDED.observed_at, published_at = EXCLUDED.published_at,"
            " time_provenance = EXCLUDED.time_provenance,"
            " identity_source = EXCLUDED.identity_source,"
            " observed_title = EXCLUDED.observed_title, metric_value = EXCLUDED.metric_value,"
            " growth_velocity = EXCLUDED.growth_velocity, geo_code = EXCLUDED.geo_code,"
            " source_url = EXCLUDED.source_url, metadata = EXCLUDED.metadata",
            (
                observation.observation_id,
                source_id,
                observation.cluster_id,
                observation.observed_at,
                observation.published_at,
                observation.time_provenance,
                observation.identity_source,
                observation.observed_title,
                observation.metric_value,
                observation.growth_velocity,
                observation.geo_code,
                observation.source_url,
                observation.metadata,
            ),
        )

    def write_evidence(self, mission_id: str, observation_id: str) -> None:
        self._conn.execute(
            "INSERT INTO mission_evidence (mission_id, observation_id) VALUES (%s, %s)"
            " ON CONFLICT (mission_id, observation_id) DO NOTHING",
            (mission_id, observation_id),
        )

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


class SqliteTarget(BackfillTarget):
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("BEGIN")

    def enforce_read_only(self) -> None:
        self._conn.execute("PRAGMA query_only = ON")

    def legacy_rows(self):
        signals = [
            SignalRow(
                signal_id=str(r[0]),
                platform=str(r[1]),
                source_url=r[2],
                raw_title=r[3],
                metadata=_metadata_dict(r[4]),
                captured_at=r[5],
                metric_value=float(r[6]) if r[6] is not None else None,
                mission_id=str(r[7]) if r[7] else None,
                cluster_id=str(r[8]) if r[8] else None,
                growth_velocity=float(r[9]) if r[9] is not None else None,
                geo_code=r[10],
                published_at=r[11],
            )
            for r in self._conn.execute(
                "SELECT id, platform, source_url, raw_title, metadata, captured_at,"
                " metric_value, mission_id, cluster_id, growth_velocity, geo_code, published_at"
                " FROM trend_signals ORDER BY id"
            ).fetchall()
        ]
        points = [
            MetricPoint(
                signal_id=str(r[0]),
                captured_at=r[1],
                metric_value=float(r[2]) if r[2] is not None else None,
                growth_velocity=float(r[3]) if r[3] is not None else None,
                metric_id=str(r[4]),
            )
            for r in self._conn.execute(
                "SELECT signal_id, captured_at, metric_value, growth_velocity, id"
                " FROM signal_metrics ORDER BY id"
            ).fetchall()
        ]
        return signals, points

    def existing_observation_ids(self):
        present = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'observations'"
        ).fetchone()
        if present is None:
            return None  # sql/016 has not been applied here
        return {str(r[0]) for r in self._conn.execute("SELECT id FROM observations")}

    def upsert_source(self, platform: str, external_id: str) -> str:
        row = self._conn.execute(
            "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)"
            " ON CONFLICT (platform, external_id) DO UPDATE SET platform = excluded.platform"
            " RETURNING id",
            (str(uuid.uuid4()), platform, external_id),
        ).fetchone()
        return str(row[0])

    def write_observation(self, observation: PlannedObservation, source_id: str) -> None:
        self._conn.execute(
            "INSERT INTO observations (id, source_id, cluster_id, observed_at, published_at,"
            " time_provenance, identity_source, observed_title, metric_value, growth_velocity,"
            " geo_code, source_url, metadata)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET"
            " source_id = excluded.source_id, cluster_id = excluded.cluster_id,"
            " observed_at = excluded.observed_at, published_at = excluded.published_at,"
            " time_provenance = excluded.time_provenance,"
            " identity_source = excluded.identity_source,"
            " observed_title = excluded.observed_title, metric_value = excluded.metric_value,"
            " growth_velocity = excluded.growth_velocity, geo_code = excluded.geo_code,"
            " source_url = excluded.source_url, metadata = excluded.metadata",
            (
                observation.observation_id,
                source_id,
                observation.cluster_id,
                observation.observed_at,
                observation.published_at,
                observation.time_provenance,
                observation.identity_source,
                observation.observed_title,
                observation.metric_value,
                observation.growth_velocity,
                observation.geo_code,
                observation.source_url,
                observation.metadata,
            ),
        )

    def write_evidence(self, mission_id: str, observation_id: str) -> None:
        self._conn.execute(
            "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (mission_id, observation_id) DO NOTHING",
            (str(uuid.uuid4()), mission_id, observation_id, "backfill"),
        )

    def commit(self) -> None:
        self._conn.execute("COMMIT")

    def rollback(self) -> None:
        self._conn.execute("ROLLBACK")

    def close(self) -> None:
        self._conn.close()


def open_target(dsn: str) -> BackfillTarget:
    if dsn.startswith("sqlite"):
        path = dsn.split("///", 1)[1] if "///" in dsn else dsn.replace("sqlite:", "").lstrip(":/")
        if not Path(path).exists():
            raise FileNotFoundError(f"SQLite database not found: {path}")
        return SqliteTarget(path)
    return PostgresTarget(dsn)


def backfill(target: BackfillTarget, apply: bool, after_sources=None) -> Dict[str, Any]:
    """Plan, refuse or write, in one transaction.

    after_sources is a hook the rollback test uses to fail partway through with the sources
    already inserted. There is no other way to prove the transaction boundary is real: a test
    that only checks the happy path cannot tell a transaction from four autocommits.
    """
    if not apply:
        # Enforced by the engine, not by the branch below. A dry run that merely happens not to
        # call a write method is one refactor away from not being a dry run.
        target.enforce_read_only()
    signals, points = target.legacy_rows()
    plan = build_plan(signals, points)

    planned_ids = {o.observation_id for o in plan.observations}
    existing = target.existing_observation_ids()
    target_tables_present = existing is not None
    if existing is None:
        if apply:
            raise BackfillRefused(
                "the target tables do not exist; apply sql/016_source_observation_model.sql first"
            )
        existing = set()
    unexpected = existing - planned_ids
    if unexpected:
        # Almost certainly the live writer, which uses random ids. Backfilling around them is
        # not safe: there is no lineage linking such an observation to the legacy event it may
        # already duplicate, so the run stops rather than doubling a sighting.
        #
        # There is deliberately no override. One existed, and no run that used it could ever
        # reach a verified state: the baseline is the legacy projection, so any observation
        # kept outside it adds a source and an observation the baseline does not contain. A
        # flag that waves the first gate through only to guarantee failing the second is not an
        # escape hatch, it is a way to spend an outage discovering that.
        raise BackfillRefused(
            f"{len(unexpected)} observations already exist that this backfill did not plan;"
            " quiesce ingress and run against a snapshot taken after it stopped"
        )

    summary = {
        "sources": len(plan.sources),
        "observations": len(plan.observations),
        "mission_evidence": plan.evidence_count,
        "cluster_memberships": plan.cluster_count,
        "pre_existing_observations": len(existing & planned_ids),
        "target_tables_present": target_tables_present,
        "applied": False,
    }
    if not apply:
        return summary

    try:
        source_ids: Dict[Tuple[str, str], str] = {}
        for platform, external_id in plan.sources:
            # Whatever the database returns. The row may already exist with a random id, written
            # by the live writer; assuming a derived id here would collide on
            # UNIQUE(platform, external_id) and lose the observations already pointing at it.
            source_ids[(platform, external_id)] = target.upsert_source(platform, external_id)
        if after_sources is not None:
            after_sources()
        for observation in plan.observations:
            target.write_observation(observation, source_ids[observation.identity_key])
        for observation in plan.observations:
            if observation.mission_id:
                target.write_evidence(observation.mission_id, observation.observation_id)
        target.commit()
    except Exception:
        target.rollback()
        raise
    summary["applied"] = True
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="plan and report, write nothing")
    mode.add_argument("--apply", action="store_true", help="write, in one transaction")
    args = parser.parse_args(argv)

    if not args.dsn:
        print("No database given: pass --dsn or set DATABASE_URL.", file=sys.stderr)
        return 2

    try:
        target = open_target(args.dsn)
    except Exception as exc:
        print(f"Could not open the database: {exc}", file=sys.stderr)
        return 2

    try:
        summary = backfill(target, apply=args.apply)
    except BackfillRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    finally:
        target.close()

    verb = "wrote" if summary["applied"] else "would write"
    print(
        f"  {verb} {summary['sources']} sources, {summary['observations']} observations,"
        f" {summary['mission_evidence']} evidence rows,"
        f" {summary['cluster_memberships']} cluster memberships"
    )
    if not summary["applied"]:
        if summary["target_tables_present"]:
            print(
                f"  target schema present, holding"
                f" {summary['pre_existing_observations']} of the planned observations"
            )
        else:
            print("  target schema absent: apply sql/016_source_observation_model.sql first")
        print("  dry run; nothing was written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
