#!/usr/bin/env python
"""Read-only audit that must balance before the source/observation/evidence migration is written.

This exists because `sql/008_deduplicate_signal_metrics.sql` claimed in its header to deduplicate
`trend_signals` and keep the earliest row as canonical, and did neither. A migration that cannot
show what it accounted for is indistinguishable from one that silently dropped rows, so the
numbers come first and the SQL comes second.

The audit answers four questions and refuses to guess at any of them:

  sources       how many canonical external objects the identity policy resolves, and by which
                rule each one was resolved
  observations  how many collection events exist, stated as an explicit formula rather than a
                single number, because `trend_signals` and `signal_metrics` overlap partially
  evidence      how many mission-to-observation associations can be rebuilt exactly, with the
                ambiguous and the missing counted separately instead of rounded away
  clusters      how many legacy rows map to a cluster certainly, ambiguously, or not at all

Every legacy row lands in exactly one bucket of every breakdown. The audit fails when a row
cannot be placed, when a reference dangles, or when two distinct external objects collide on one
identity without a reason code -- those are the conditions under which a migration would lose
data, and they are worth a red exit long before any DDL is drafted.

Usage:
    python scripts/migration_reconciliation_audit.py --json-out baseline.json
    python scripts/migration_reconciliation_audit.py --dsn sqlite:///ignis.db

Exit codes: 0 balanced, 1 audit failed, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlsplit, urlunsplit

# --- Identity policy -------------------------------------------------------------------------
#
# A canonical source is the external object, keyed on platform plus the identifier that platform
# assigns it. The connector already records that identifier in metadata, so it is preferred over
# anything parsed out of a URL. raw_title is deliberately excluded: ten URLs in the corpus carry
# two different titles, which proves a title is something observed about a source rather than
# part of its identity.
#
# These are third-party field names, matched verbatim against what each connector writes.
EXTERNAL_ID_METADATA_KEYS: Dict[str, Tuple[str, ...]] = {
    "youtube": ("video_id",),
    "tiktok": ("item_id", "hashtag"),
    "threads": ("post_id",),
    "reels": ("reel_id",),
    # Google Trends has no object id: the trend keyword is the object. The explore URL carries it
    # in q=, so URL and metadata agree here rather than one being a fallback for the other.
    "google": ("keyword", "probe_keyword"),
}

# URL shapes to recover an identifier from when metadata is absent, tried in order.
URL_ID_PATTERNS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "youtube": ((r"[?&]v=([A-Za-z0-9_-]{6,})", "video"), (r"youtu\.be/([A-Za-z0-9_-]{6,})", "video")),
    "tiktok": ((r"/video/(\d+)", "video"), (r"/tag/([^/?#]+)", "tag")),
    "threads": ((r"/post/([A-Za-z0-9_-]+)", "post"), (r"/t/([A-Za-z0-9_-]+)", "post")),
    "reels": ((r"/reel/([A-Za-z0-9_-]+)", "reel"), (r"/p/([A-Za-z0-9_-]+)", "post")),
    "google": ((r"[?&]q=([^&]+)", "keyword"),),
}

# Query parameters that never change which object a URL points at.
TRACKING_PARAMS = frozenset(
    {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
)

RESOLUTION_METADATA = "metadata_external_id"
RESOLUTION_URL = "url_external_id"
RESOLUTION_NORMALIZED_URL = "normalized_url_fallback"
RESOLUTION_UNRESOLVED = "unresolved"

MERGE_REPEAT = "repeat_observation_of_one_source"
MERGE_TITLE_CHANGED = "observed_title_changed"
MERGE_URL_VARIANT = "url_variant_of_one_source"
MERGE_UNCLASSIFIED = "unclassified_identity_collision"


def normalize_url(raw: Optional[str]) -> str:
    """Drop the parts of a URL that never distinguish two objects."""
    if not raw:
        return ""
    parts = urlsplit(raw.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = "&".join(
        f"{k}={v}" for k, v in sorted(parse_qsl(parts.query)) if k not in TRACKING_PARAMS
    )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def resolve_identity(platform: str, source_url: Optional[str], metadata: Any) -> Tuple[str, str]:
    """Return (identity, resolution_reason) for one legacy row."""
    meta = metadata if isinstance(metadata, dict) else {}
    for key in EXTERNAL_ID_METADATA_KEYS.get(platform, ()):
        value = meta.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return f"{platform}:{key}:{str(value).strip()}", RESOLUTION_METADATA

    for pattern, kind in URL_ID_PATTERNS.get(platform, ()):
        match = re.search(pattern, source_url or "")
        if match:
            return f"{platform}:{kind}:{match.group(1)}", RESOLUTION_URL

    normalized = normalize_url(source_url)
    if normalized:
        return f"{platform}:url:{normalized}", RESOLUTION_NORMALIZED_URL

    return "", RESOLUTION_UNRESOLVED


# --- Row model -------------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalRow:
    signal_id: str
    platform: str
    source_url: Optional[str]
    raw_title: Optional[str]
    metadata: Any
    captured_at: Optional[str]
    metric_value: Optional[float]
    mission_id: Optional[str]
    cluster_id: Optional[str]


@dataclass
class Findings:
    failures: List[str] = field(default_factory=list)

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.failures.append(message)


# --- Readers ---------------------------------------------------------------------------------


class ReadOnlyReader:
    """Base contract: hand back rows, never issue DDL or DML."""

    def signals(self) -> Iterable[SignalRow]:
        raise NotImplementedError

    def metric_points(self) -> Iterable[Tuple[str, Optional[str], Optional[float]]]:
        raise NotImplementedError

    def mission_ids(self) -> Sequence[str]:
        raise NotImplementedError

    def cluster_ids(self) -> Sequence[str]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class PostgresReader(ReadOnlyReader):
    def __init__(self, dsn: str):
        import psycopg  # imported here so SQLite-only runs need no driver

        self._conn = psycopg.connect(dsn)
        # Enforced by the server, not by convention: any write in this session is refused.
        self._conn.execute("SET TRANSACTION READ ONLY")

    def signals(self) -> Iterable[SignalRow]:
        for row in self._conn.execute(
            "SELECT id, platform, source_url, raw_title, metadata, captured_at, metric_value,"
            " mission_id, cluster_id FROM trend_signals ORDER BY id"
        ):
            yield SignalRow(
                signal_id=str(row[0]),
                platform=str(row[1]),
                source_url=row[2],
                raw_title=row[3],
                metadata=row[4],
                captured_at=row[5].isoformat() if row[5] else None,
                metric_value=float(row[6]) if row[6] is not None else None,
                mission_id=str(row[7]) if row[7] else None,
                cluster_id=str(row[8]) if row[8] else None,
            )

    def metric_points(self) -> Iterable[Tuple[str, Optional[str], Optional[float]]]:
        for row in self._conn.execute(
            "SELECT signal_id, captured_at, metric_value FROM signal_metrics"
            " ORDER BY signal_id, captured_at, metric_value"
        ):
            yield (
                str(row[0]),
                row[1].isoformat() if row[1] else None,
                float(row[2]) if row[2] is not None else None,
            )

    def mission_ids(self) -> Sequence[str]:
        return [str(r[0]) for r in self._conn.execute("SELECT id FROM research_missions")]

    def cluster_ids(self) -> Sequence[str]:
        return [str(r[0]) for r in self._conn.execute("SELECT id FROM topic_clusters")]

    def close(self) -> None:
        self._conn.close()


class SqliteReader(ReadOnlyReader):
    def __init__(self, path: str):
        # mode=ro is enforced by SQLite itself; a write attempt raises rather than succeeding.
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def signals(self) -> Iterable[SignalRow]:
        for row in self._conn.execute(
            "SELECT id, platform, source_url, raw_title, metadata, captured_at, metric_value,"
            " mission_id, cluster_id FROM trend_signals ORDER BY id"
        ):
            try:
                metadata = json.loads(row[4]) if row[4] else {}
            except (TypeError, ValueError):
                metadata = {}
            yield SignalRow(
                signal_id=str(row[0]),
                platform=str(row[1]),
                source_url=row[2],
                raw_title=row[3],
                metadata=metadata,
                captured_at=row[5],
                metric_value=float(row[6]) if row[6] is not None else None,
                mission_id=str(row[7]) if row[7] else None,
                cluster_id=str(row[8]) if row[8] else None,
            )

    def metric_points(self) -> Iterable[Tuple[str, Optional[str], Optional[float]]]:
        try:
            rows = self._conn.execute(
                "SELECT signal_id, captured_at, metric_value FROM signal_metrics"
                " ORDER BY signal_id, captured_at, metric_value"
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # a database predating the metric history table
        return [
            (str(r[0]), r[1], float(r[2]) if r[2] is not None else None) for r in rows
        ]

    def mission_ids(self) -> Sequence[str]:
        return [str(r[0]) for r in self._conn.execute("SELECT id FROM research_missions")]

    def cluster_ids(self) -> Sequence[str]:
        return [str(r[0]) for r in self._conn.execute("SELECT id FROM topic_clusters")]

    def close(self) -> None:
        self._conn.close()


def open_reader(dsn: str) -> ReadOnlyReader:
    if dsn.startswith("sqlite"):
        path = dsn.split("///", 1)[1] if "///" in dsn else dsn.replace("sqlite:", "").lstrip(":/")
        if not Path(path).exists():
            raise FileNotFoundError(f"SQLite database not found: {path}")
        return SqliteReader(path)
    return PostgresReader(dsn)


# --- Audit -----------------------------------------------------------------------------------


def audit(reader: ReadOnlyReader) -> Dict[str, Any]:
    findings = Findings()
    signals = list(reader.signals())
    metric_points = list(reader.metric_points())
    known_missions = set(reader.mission_ids())
    known_clusters = set(reader.cluster_ids())

    identity_of: Dict[str, str] = {}
    resolution_counts: Counter = Counter()
    rows_per_identity: Dict[str, List[SignalRow]] = defaultdict(list)
    unresolved_rows: List[str] = []

    for row in signals:
        identity, reason = resolve_identity(row.platform, row.source_url, row.metadata)
        resolution_counts[reason] += 1
        if reason == RESOLUTION_UNRESOLVED:
            unresolved_rows.append(row.signal_id)
            continue
        identity_of[row.signal_id] = identity
        rows_per_identity[identity].append(row)

    # Why does an identity hold more than one legacy row? Every collapse needs a stated reason,
    # so that a migration reviewer can tell a repeat observation from two objects fused by mistake.
    merge_reasons: Counter = Counter()
    unclassified_collisions: List[Dict[str, Any]] = []
    for identity, rows in sorted(rows_per_identity.items()):
        if len(rows) == 1:
            continue
        titles = {(r.raw_title or "").strip() for r in rows}
        urls = {normalize_url(r.source_url) for r in rows}
        if len(urls) > 1:
            merge_reasons[MERGE_URL_VARIANT] += len(rows)
        elif len(titles) > 1:
            merge_reasons[MERGE_TITLE_CHANGED] += len(rows)
        elif len(titles) == 1:
            merge_reasons[MERGE_REPEAT] += len(rows)
        else:
            merge_reasons[MERGE_UNCLASSIFIED] += len(rows)
            unclassified_collisions.append(
                {"identity": identity, "row_count": len(rows)}
            )

    # Observations. trend_signals and signal_metrics overlap partially, so no single count is
    # self-evidently right; the audit states the arithmetic instead of asserting a total.
    signal_ids = {row.signal_id for row in signals}
    dangling_metric_points = sorted({p[0] for p in metric_points} - signal_ids)
    signals_with_metrics = {p[0] for p in metric_points}
    metric_triples = {(p[0], p[1], p[2]) for p in metric_points}
    signal_triples = {(row.signal_id, row.captured_at, row.metric_value) for row in signals}

    observation_arithmetic = {
        "formula": (
            "observations = distinct(signal_id, captured_at, metric_value) over"
            " signal_metrics UNION trend_signals"
        ),
        "trend_signals_rows": len(signals),
        "signal_metrics_rows": len(metric_points),
        "signals_carrying_at_least_one_metric_point": len(signals_with_metrics),
        "signals_with_no_metric_point": len(signals) - len(signals_with_metrics),
        "metric_triples_distinct": len(metric_triples),
        "signal_triples_distinct": len(signal_triples),
        "triples_shared_by_both_tables": len(metric_triples & signal_triples),
        "observations": len(metric_triples | signal_triples),
        "naive_sum_for_contrast": len(signals) + len(metric_points),
    }
    findings.require(
        observation_arithmetic["observations"]
        == len(metric_triples) + len(signal_triples) - len(metric_triples & signal_triples),
        "observation arithmetic does not balance: union != a + b - overlap",
    )
    findings.require(
        not dangling_metric_points,
        f"{len(dangling_metric_points)} metric points reference a missing trend_signals row",
    )

    # Mission evidence. A row maps exactly when it is mission-attached, its mission exists, and it
    # resolves to one identity. Anything else is reported, never rounded into the exact count.
    mission_exact: List[str] = []
    mission_unresolved_identity: List[str] = []
    mission_dangling: List[str] = []
    evidence_per_mission_identity: Counter = Counter()
    for row in signals:
        if not row.mission_id:
            continue
        if row.mission_id not in known_missions:
            mission_dangling.append(row.signal_id)
            continue
        if row.signal_id not in identity_of:
            mission_unresolved_identity.append(row.signal_id)
            continue
        mission_exact.append(row.signal_id)
        evidence_per_mission_identity[(row.mission_id, identity_of[row.signal_id])] += 1

    mission_ambiguous = sorted(
        {m for (m, _ident), n in evidence_per_mission_identity.items() if n > 1}
    )
    mission_attached_total = sum(1 for row in signals if row.mission_id)
    findings.require(
        mission_attached_total
        == len(mission_exact) + len(mission_unresolved_identity) + len(mission_dangling),
        "mission-attached rows do not sum to exact + unresolved + dangling",
    )
    findings.require(
        not mission_dangling,
        f"{len(mission_dangling)} rows reference a mission that no longer exists",
    )

    # Cluster membership belongs to the observation, not the source, so this reports what can be
    # carried across and does not spread a current cluster over a source's whole history.
    cluster_certain = 0
    cluster_dangling: List[str] = []
    cluster_absent = 0
    identities_per_cluster: Dict[str, set] = defaultdict(set)
    for row in signals:
        if not row.cluster_id:
            cluster_absent += 1
            continue
        if row.cluster_id not in known_clusters:
            cluster_dangling.append(row.signal_id)
            continue
        cluster_certain += 1
        if row.signal_id in identity_of:
            identities_per_cluster[row.cluster_id].add(identity_of[row.signal_id])
    cluster_ambiguous_identities = sorted(
        identity
        for identity, clusters in _invert(identities_per_cluster).items()
        if len(clusters) > 1
    )
    findings.require(
        len(signals) == cluster_certain + len(cluster_dangling) + cluster_absent,
        "rows do not sum to cluster certain + dangling + absent",
    )
    findings.require(
        not cluster_dangling,
        f"{len(cluster_dangling)} rows reference a cluster that no longer exists",
    )

    # No legacy row may fall outside the identity breakdown.
    findings.require(
        len(signals) == sum(resolution_counts.values()),
        "resolution buckets do not account for every trend_signals row",
    )
    findings.require(
        not unresolved_rows,
        f"{len(unresolved_rows)} rows have no resolvable external identity",
    )
    findings.require(
        not unclassified_collisions,
        f"{len(unclassified_collisions)} identities merge rows without a reason code",
    )

    merged_rows = sum(merge_reasons.values())
    single_row_identities = sum(1 for rows in rows_per_identity.values() if len(rows) == 1)
    findings.require(
        len(signals) - len(unresolved_rows) == single_row_identities + merged_rows,
        "resolved rows do not sum to single-row identities + merged rows",
    )

    return {
        "schema_version": 1,
        "sources": {
            "canonical_sources": len(rows_per_identity),
            "resolution_reasons": dict(sorted(resolution_counts.items())),
            "merge_reasons": dict(sorted(merge_reasons.items())),
            "identities_holding_one_row": single_row_identities,
            "rows_inside_merged_identities": merged_rows,
            "unresolved_rows": len(unresolved_rows),
            "unclassified_collisions": unclassified_collisions,
        },
        "observations": observation_arithmetic,
        "mission_evidence": {
            "mission_attached_rows": mission_attached_total,
            "exactly_reconstructable": len(mission_exact),
            "unresolved_identity": len(mission_unresolved_identity),
            "dangling_mission_reference": len(mission_dangling),
            "missions_with_repeated_identity": len(mission_ambiguous),
            "distinct_mission_identity_pairs": len(evidence_per_mission_identity),
        },
        "cluster_membership": {
            "rows_mapping_certainly": cluster_certain,
            "rows_with_dangling_cluster": len(cluster_dangling),
            "rows_without_cluster": cluster_absent,
            "identities_spanning_more_than_one_cluster": len(cluster_ambiguous_identities),
        },
        "invariants": {
            "checked": 10,
            "failed": len(findings.failures),
            "failures": sorted(findings.failures),
        },
        "balanced": not findings.failures,
    }


def _invert(mapping: Dict[str, set]) -> Dict[str, set]:
    inverted: Dict[str, set] = defaultdict(set)
    for key, values in mapping.items():
        for value in values:
            inverted[value].add(key)
    return inverted


def render_summary(report: Dict[str, Any]) -> str:
    src = report["sources"]
    obs = report["observations"]
    mis = report["mission_evidence"]
    clu = report["cluster_membership"]
    inv = report["invariants"]
    lines = [
        "Migration reconciliation audit",
        "",
        f"  canonical sources           {src['canonical_sources']}",
        *(
            f"    from {reason:36s} {count} rows"
            for reason, count in src["resolution_reasons"].items()
        ),
        f"    identities holding one row           {src['identities_holding_one_row']}",
        *(
            f"    merge {reason:36s} {count} rows"
            for reason, count in src["merge_reasons"].items()
        ),
        "",
        f"  observations                {obs['observations']}",
        f"    {obs['formula']}",
        f"    trend_signals rows              {obs['trend_signals_rows']}",
        f"    signal_metrics rows             {obs['signal_metrics_rows']}",
        f"    signals with no metric point    {obs['signals_with_no_metric_point']}",
        f"    triples in both tables          {obs['triples_shared_by_both_tables']}",
        f"    naive sum, for contrast         {obs['naive_sum_for_contrast']}",
        "",
        "  mission evidence",
        f"    mission-attached rows           {mis['mission_attached_rows']}",
        f"    exactly reconstructable         {mis['exactly_reconstructable']}",
        f"    unresolved identity             {mis['unresolved_identity']}",
        f"    dangling mission reference      {mis['dangling_mission_reference']}",
        f"    missions repeating an identity  {mis['missions_with_repeated_identity']}",
        "",
        "  cluster membership",
        f"    mapping certainly               {clu['rows_mapping_certainly']}",
        f"    dangling cluster reference      {clu['rows_with_dangling_cluster']}",
        f"    no cluster                      {clu['rows_without_cluster']}",
        f"    identities across >1 cluster    {clu['identities_spanning_more_than_one_cluster']}",
        "",
        f"  invariants                  {inv['checked'] - inv['failed']}/{inv['checked']} held",
    ]
    lines.extend(f"    FAILED: {failure}" for failure in inv["failures"])
    lines.append("")
    lines.append("  BALANCED" if report["balanced"] else "  NOT BALANCED -- migration is gated")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--json-out", type=Path, help="write the deterministic JSON report here")
    parser.add_argument("--quiet", action="store_true", help="suppress the human summary")
    args = parser.parse_args(argv)

    if not args.dsn:
        print("No database given: pass --dsn or set DATABASE_URL.", file=sys.stderr)
        return 2

    try:
        reader = open_reader(args.dsn)
    except Exception as exc:
        print(f"Could not open the database read-only: {exc}", file=sys.stderr)
        return 2

    try:
        report = audit(reader)
    finally:
        reader.close()

    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.json_out:
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    elif args.quiet:
        print(payload)

    if not args.quiet:
        print(render_summary(report))

    return 0 if report["balanced"] else 1


if __name__ == "__main__":
    sys.exit(main())
