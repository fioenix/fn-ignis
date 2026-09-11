#!/usr/bin/env python
"""Read-only check that the new tables hold what the baseline says they must.

This exists because the reconciliation audit reads `trend_signals` and `signal_metrics`, and
those tables survive the migration untouched. Run the audit after a backfill and it still
reports BALANCED -- it would report BALANCED with `sources`, `observations` and
`mission_evidence` completely empty, because it never looks at them. A migration checked only
by that audit is not checked at all.

So this reads the three new tables directly and rebuilds the same four digests from what was
actually stored. The values are serialized exactly as found, in particular `observed_at` and
`time_provenance`: deriving either one again here would let the verifier repair a migration
that wrote the wrong value, and a green run would then mean nothing.

Usage:
    python scripts/post_migration_verification.py --baseline docs/migrations/<file>.json
    python scripts/post_migration_verification.py --dsn sqlite:///ignis.db

Exit codes: 0 every digest and count matches, 1 a mismatch, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ignis.infrastructure.migration.legacy_projection import (  # noqa: E402
    digest_of,
    serialize_observation,
)

DEFAULT_BASELINE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "migrations"
    / "2026-09-10-source-observation-baseline.json"
)


@dataclass(frozen=True)
class StoredObservation:
    observation_id: str
    identity: str
    observed_at: Optional[str]
    published_at: Optional[str]
    time_provenance: Optional[str]
    observed_title: Optional[str]
    metric_value: Optional[float]
    growth_velocity: Optional[float]
    geo_code: Optional[str]
    source_url: Optional[str]
    metadata: Any
    identity_source: Optional[str]
    cluster_id: Optional[str]

    @property
    def member(self) -> str:
        return serialize_observation(
            identity=self.identity,
            observed_at=self.observed_at,
            published_at=self.published_at,
            time_provenance=self.time_provenance,
            observed_title=self.observed_title,
            metric_value=self.metric_value,
            growth_velocity=self.growth_velocity,
            geo_code=self.geo_code,
            source_url=self.source_url,
            metadata=self.metadata,
            identity_source=self.identity_source,
        )


class StoredReader:
    """Reads the migrated model. Read-only, enforced by the engine rather than by convention."""

    def sources(self) -> Sequence[str]:
        raise NotImplementedError

    def observations(self) -> Sequence[StoredObservation]:
        raise NotImplementedError

    def evidence(self) -> Sequence[tuple]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def _as_metadata(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


class PostgresStoredReader(StoredReader):
    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn)
        self._conn.execute("SET TRANSACTION READ ONLY")

    def sources(self) -> Sequence[str]:
        return [
            f"{row[0]}:{row[1]}"
            for row in self._conn.execute(
                "SELECT platform, external_id FROM sources ORDER BY platform, external_id"
            )
        ]

    def observations(self) -> Sequence[StoredObservation]:
        rows = self._conn.execute(
            "SELECT o.id, s.platform, s.external_id, o.observed_at, o.published_at,"
            " o.time_provenance, o.observed_title, o.metric_value, o.growth_velocity,"
            " o.geo_code, o.source_url, o.metadata, o.identity_source, o.cluster_id"
            " FROM observations o JOIN sources s ON s.id = o.source_id ORDER BY o.id"
        ).fetchall()
        return [
            StoredObservation(
                observation_id=str(r[0]),
                identity=f"{r[1]}:{r[2]}",
                observed_at=r[3].isoformat() if r[3] else None,
                published_at=r[4].isoformat() if r[4] else None,
                time_provenance=r[5],
                observed_title=r[6],
                metric_value=float(r[7]) if r[7] is not None else None,
                growth_velocity=float(r[8]) if r[8] is not None else None,
                geo_code=r[9],
                source_url=r[10],
                metadata=_as_metadata(r[11]),
                identity_source=r[12],
                cluster_id=str(r[13]) if r[13] else None,
            )
            for r in rows
        ]

    def evidence(self) -> Sequence[tuple]:
        return [
            (str(r[0]), str(r[1]))
            for r in self._conn.execute(
                "SELECT mission_id, observation_id FROM mission_evidence"
            )
        ]

    def close(self) -> None:
        self._conn.close()


class SqliteStoredReader(StoredReader):
    def __init__(self, path: str):
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def sources(self) -> Sequence[str]:
        return [
            f"{row[0]}:{row[1]}"
            for row in self._conn.execute(
                "SELECT platform, external_id FROM sources ORDER BY platform, external_id"
            )
        ]

    def observations(self) -> Sequence[StoredObservation]:
        rows = self._conn.execute(
            "SELECT o.id, s.platform, s.external_id, o.observed_at, o.published_at,"
            " o.time_provenance, o.observed_title, o.metric_value, o.growth_velocity,"
            " o.geo_code, o.source_url, o.metadata, o.identity_source, o.cluster_id"
            " FROM observations o JOIN sources s ON s.id = o.source_id ORDER BY o.id"
        ).fetchall()
        return [
            StoredObservation(
                observation_id=str(r[0]),
                identity=f"{r[1]}:{r[2]}",
                observed_at=r[3],
                published_at=r[4],
                time_provenance=r[5],
                observed_title=r[6],
                metric_value=float(r[7]) if r[7] is not None else None,
                growth_velocity=float(r[8]) if r[8] is not None else None,
                geo_code=r[9],
                source_url=r[10],
                metadata=_as_metadata(r[11]),
                identity_source=r[12],
                cluster_id=str(r[13]) if r[13] else None,
            )
            for r in rows
        ]

    def evidence(self) -> Sequence[tuple]:
        return [
            (str(r[0]), str(r[1]))
            for r in self._conn.execute(
                "SELECT mission_id, observation_id FROM mission_evidence"
            )
        ]

    def close(self) -> None:
        self._conn.close()


def open_stored_reader(dsn: str) -> StoredReader:
    if dsn.startswith("sqlite"):
        path = dsn.split("///", 1)[1] if "///" in dsn else dsn.replace("sqlite:", "").lstrip(":/")
        if not Path(path).exists():
            raise FileNotFoundError(f"SQLite database not found: {path}")
        return SqliteStoredReader(path)
    return PostgresStoredReader(dsn)


def verify(reader: StoredReader, baseline: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild the four digests from the migrated tables and compare them with the baseline."""
    source_members = list(reader.sources())
    observations = list(reader.observations())
    member_of = {o.observation_id: o.member for o in observations}

    observation_members = [o.member for o in observations]
    cluster_members = [
        f"{o.cluster_id}\x1f{o.member}" for o in observations if o.cluster_id
    ]
    mission_members: List[str] = []
    dangling_evidence = 0
    for mission_id, observation_id in reader.evidence():
        member = member_of.get(observation_id)
        if member is None:
            dangling_evidence += 1
            continue
        mission_members.append(f"{mission_id}\x1f{member}")

    actual = {
        "sources": digest_of(source_members),
        "observations": digest_of(observation_members),
        "mission_associations": digest_of(mission_members),
        "cluster_memberships": digest_of(cluster_members),
        "member_counts": {
            "sources": len(source_members),
            "observations": len(observation_members),
            "mission_associations": len(mission_members),
            "cluster_memberships": len(cluster_members),
        },
    }

    expected = baseline["digests"]
    comparisons = []
    for name in ("sources", "observations", "mission_associations", "cluster_memberships"):
        comparisons.append(
            {
                "set": name,
                "expected_digest": expected[name],
                "actual_digest": actual[name],
                "expected_members": expected["member_counts"][name],
                "actual_members": actual["member_counts"][name],
                "matches": expected[name] == actual[name]
                and expected["member_counts"][name] == actual["member_counts"][name],
            }
        )

    provenance: Dict[str, int] = {}
    for observation in observations:
        key = observation.time_provenance or "missing"
        provenance[key] = provenance.get(key, 0) + 1

    expected_provenance = baseline["observations"]["time_provenance_buckets"]
    provenance_matches = all(
        provenance.get(bucket, 0) == count for bucket, count in expected_provenance.items()
    )

    return {
        "baseline_schema_version": baseline.get("schema_version"),
        "comparisons": comparisons,
        "dangling_evidence": dangling_evidence,
        "time_provenance": {
            "expected": expected_provenance,
            "actual": provenance,
            "matches": provenance_matches,
        },
        "verified": (
            all(c["matches"] for c in comparisons)
            and dangling_evidence == 0
            and provenance_matches
        ),
    }


def render(report: Dict[str, Any]) -> str:
    lines = [
        "",
        f"  post-migration verification against baseline schema_version "
        f"{report['baseline_schema_version']}",
        "",
    ]
    for comparison in report["comparisons"]:
        mark = "ok " if comparison["matches"] else "BAD"
        lines.append(
            f"  {mark} {comparison['set']:<22}"
            f" expected {comparison['expected_digest'][:16]} over"
            f" {comparison['expected_members']:>6}"
            f"  ·  actual {comparison['actual_digest'][:16]} over"
            f" {comparison['actual_members']:>6}"
        )
    lines.append("")
    provenance = report["time_provenance"]
    lines.append(f"  time provenance expected {provenance['expected']}")
    lines.append(f"                  actual   {provenance['actual']}")
    if report["dangling_evidence"]:
        lines.append(
            f"  {report['dangling_evidence']} evidence rows point at no observation"
        )
    lines.append("")
    lines.append("  VERIFIED" if report["verified"] else "  MISMATCH")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)

    if not args.dsn:
        print("No database given: pass --dsn or set DATABASE_URL.", file=sys.stderr)
        return 2

    try:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Could not read the baseline: {exc}", file=sys.stderr)
        return 2

    try:
        reader = open_stored_reader(args.dsn)
    except Exception as exc:
        print(f"Could not open the database: {exc}", file=sys.stderr)
        return 2

    try:
        report = verify(reader, baseline)
    except Exception as exc:
        print(f"Verification could not run: {exc}", file=sys.stderr)
        return 2
    finally:
        reader.close()

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(render(report))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
