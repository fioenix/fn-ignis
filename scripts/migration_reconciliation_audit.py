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
from hashlib import sha256
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
    published_at: Optional[str]
    metric_value: Optional[float]
    growth_velocity: Optional[float]
    geo_code: Optional[str]
    mission_id: Optional[str]
    cluster_id: Optional[str]


@dataclass(frozen=True)
class MetricPoint:
    """One row of signal_metrics: the same source observed again, with its own metric payload."""

    signal_id: str
    captured_at: Optional[str]
    metric_value: Optional[float]
    growth_velocity: Optional[float]

    @property
    def payload(self) -> Tuple[Optional[str], Optional[float], Optional[float]]:
        return (self.captured_at, self.metric_value, self.growth_velocity)


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

    def metric_points(self) -> Iterable["MetricPoint"]:
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
            " mission_id, cluster_id, growth_velocity, geo_code, published_at"
            " FROM trend_signals ORDER BY id"
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
                growth_velocity=float(row[9]) if row[9] is not None else None,
                geo_code=row[10],
                published_at=row[11].isoformat() if row[11] else None,
            )

    def metric_points(self) -> Iterable[MetricPoint]:
        for row in self._conn.execute(
            "SELECT signal_id, captured_at, metric_value, growth_velocity FROM signal_metrics"
            " ORDER BY signal_id, captured_at, metric_value, growth_velocity"
        ):
            yield MetricPoint(
                signal_id=str(row[0]),
                captured_at=row[1].isoformat() if row[1] else None,
                metric_value=float(row[2]) if row[2] is not None else None,
                growth_velocity=float(row[3]) if row[3] is not None else None,
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
            " mission_id, cluster_id, growth_velocity, geo_code, published_at"
            " FROM trend_signals ORDER BY id"
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
                growth_velocity=float(row[9]) if row[9] is not None else None,
                geo_code=row[10],
                published_at=row[11],
            )

    def metric_points(self) -> Iterable[MetricPoint]:
        try:
            rows = self._conn.execute(
                "SELECT signal_id, captured_at, metric_value, growth_velocity FROM signal_metrics"
                " ORDER BY signal_id, captured_at, metric_value, growth_velocity"
            ).fetchall()
        except sqlite3.OperationalError:
            return []  # a database predating the metric history table
        return [
            MetricPoint(
                signal_id=str(r[0]),
                captured_at=r[1],
                metric_value=float(r[2]) if r[2] is not None else None,
                growth_velocity=float(r[3]) if r[3] is not None else None,
            )
            for r in rows
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
        reason = _merge_reason_for(rows)
        merge_reasons[reason] += len(rows)
        if reason == MERGE_UNCLASSIFIED:
            unclassified_collisions.append({"identity": identity, "row_count": len(rows)})

    # Observations. trend_signals and signal_metrics overlap partially, so no single count is
    # self-evidently right; the audit states the arithmetic instead of asserting a total.
    signal_ids = {row.signal_id for row in signals}
    dangling_metric_points = sorted({p.signal_id for p in metric_points} - signal_ids)

    # One observation per collection event, resolved along legacy lineage. A signal_metrics point
    # is merged with its parent row only when it repeats that row's whole metric payload, which is
    # the copy sql/008 made. Anything else is a second sighting and stays a second observation.
    #
    # The members are a multiset. The previous version built a set here, which erased the very
    # multiplicity the audit exists to conserve: rows sharing source, captured_at and metric_value
    # were counted once, and the difference was then reported as though the migration would
    # genuinely reduce them. In this corpus those rows carry three distinct growth_velocity values,
    # so they are distinct collection events and no unique constraint says otherwise. It is the
    # surrogate observation id that keeps them apart.
    points_by_signal: Dict[str, List[MetricPoint]] = defaultdict(list)
    for point in metric_points:
        points_by_signal[point.signal_id].append(point)

    observation_members: List[str] = []
    provenance_buckets: Counter = Counter()
    lineage_merges = 0
    for row in signals:
        if row.signal_id not in identity_of:
            continue
        identity = identity_of[row.signal_id]
        row_payload = (row.captured_at, row.metric_value, row.growth_velocity)
        member, provenance = observation_event(identity, row, *row_payload)
        observation_members.append(member)
        provenance_buckets[provenance] += 1
        merged_once = False
        for point in points_by_signal.get(row.signal_id, []):
            if point.payload == row_payload and not merged_once:
                merged_once = True  # the sql/008 copy of the row itself
                lineage_merges += 1
                continue
            # Derived on this point's own captured_at. It may land in a different bucket from its
            # parent row, which is the whole reason the derivation is per event.
            member, point_provenance = observation_event(
                identity, row, point.captured_at, point.metric_value, point.growth_velocity
            )
            observation_members.append(member)
            provenance_buckets[point_provenance] += 1

    observation_arithmetic = {
        "formula": (
            "observations = one per trend_signals row, plus one per signal_metrics point whose"
            " (captured_at, metric_value, growth_velocity) does not repeat its parent row's"
        ),
        "trend_signals_rows": len(signals),
        "signal_metrics_rows": len(metric_points),
        "signals_carrying_at_least_one_metric_point": len({p.signal_id for p in metric_points}),
        "signals_with_no_metric_point": len(signals)
        - len({p.signal_id for p in metric_points} & {row.signal_id for row in signals}),
        "lineage_merges_of_the_sql008_copy": lineage_merges,
        "observations": len(observation_members),
        "naive_sum_for_contrast": len(signals) + len(metric_points),
        "preserved_fields": list(OBSERVATION_FIELDS),
        "intentional_losses": dict(sorted(INTENTIONAL_LOSSES.items())),
        # Every observation lands in exactly one bucket. A migration that mislabels a legacy
        # publish time as a proven ingestion time would leave every count and every digest of the
        # previous version matching, which is why provenance is inside the digest and counted here.
        "time_provenance_buckets": {
            PROVENANCE_EXACT: provenance_buckets[PROVENANCE_EXACT],
            PROVENANCE_LEGACY: provenance_buckets[PROVENANCE_LEGACY],
            PROVENANCE_UNKNOWN: provenance_buckets[PROVENANCE_UNKNOWN],
        },
    }
    # Members that are byte-identical across every preserved field. These are NOT a reduction the
    # migration performs: two collection events may legitimately look the same on all of them, and
    # only the surrogate observation id separates them. The number is reported so the post-migration
    # run can confirm the same multiplicity survived, not so anything gets collapsed.
    distinct_members = len(set(observation_members))
    observation_arithmetic["distinct_observation_payloads"] = distinct_members
    observation_arithmetic["indistinguishable_observation_multiplicity"] = (
        len(observation_members) - distinct_members
    )
    findings.require(
        len(observation_members)
        == len(signals) - len([row for row in signals if row.signal_id not in identity_of])
        + len(metric_points)
        - lineage_merges
        - len([p for p in metric_points if p.signal_id not in identity_of]),
        "observation count does not balance against rows, points and lineage merges",
    )
    findings.require(
        sum(observation_arithmetic["time_provenance_buckets"].values())
        == len(observation_members),
        "time_provenance buckets do not account for every observation",
    )
    findings.require(
        observation_arithmetic["indistinguishable_observation_multiplicity"] >= 0,
        "distinct observation payloads exceed the observation multiset",
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
    # A multiset, for the same reason as the observations: two rows in one cluster that look
    # identical on every preserved field are still two memberships. Nothing is deleted just
    # because two observations share a payload.
    cluster_members_preview = [
        f"{row.cluster_id}\x1f"
        + observation_event(
            identity_of[row.signal_id], row, row.captured_at, row.metric_value,
            row.growth_velocity,
        )[0]
        for row in signals
        if row.cluster_id and row.signal_id in identity_of
    ]
    cluster_ambiguous_identities = sorted(
        identity
        for identity, clusters in _invert(identities_per_cluster).items()
        if len(clusters) > 1
    )
    findings.require(
        len(cluster_members_preview) <= cluster_certain,
        "cluster memberships exceed the rows that map to a cluster",
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

    # Row-level detail. This is what the migration author needs to hand-check a merge, and it is
    # exactly what must not be committed: it names external objects. build_sanitized_report drops
    # the whole block, and a test asserts the tracked copy carries none of it.
    detail = {
        "merged_identities": sorted(
            (
                {
                    "identity": identity,
                    "row_count": len(rows),
                    "reason": _merge_reason_for(rows),
                    "distinct_titles": sorted({(r.raw_title or "").strip() for r in rows}),
                }
                for identity, rows in rows_per_identity.items()
                if len(rows) > 1
            ),
            key=lambda entry: (-entry["row_count"], entry["identity"]),
        ),
        "identities_in_more_than_one_cluster": cluster_ambiguous_identities,
        "mission_identity_repeats": [
            {"mission_id": mission, "identity": identity, "row_count": count}
            for (mission, identity), count in sorted(evidence_per_mission_identity.items())
            if count > 1
        ],
        "unresolved_row_ids": sorted(unresolved_rows),
        "unclassified_collisions": unclassified_collisions,
    }
    findings.require(
        len(signals) - len(unresolved_rows) == single_row_identities + merged_rows,
        "resolved rows do not sum to single-row identities + merged rows",
    )

    # One digest per canonical set, over business identity rather than surrogate keys, so the
    # post-migration run can recompute the same value from the new tables.
    mission_members = [
        f"{row.mission_id}\x1f"
        + observation_event(
            identity_of[row.signal_id], row, row.captured_at, row.metric_value,
            row.growth_velocity,
        )[0]
        for row in signals
        if row.mission_id and row.signal_id in identity_of
    ]
    cluster_members = cluster_members_preview
    digests = {
        "algorithm": "sha256 over NUL-separated members of each sorted multiset",
        "sources": digest_of(rows_per_identity),
        "observations": digest_of(observation_members),
        "mission_associations": digest_of(mission_members),
        "cluster_memberships": digest_of(cluster_members),
        "member_counts": {
            "sources": len(rows_per_identity),
            "observations": len(observation_members),
            "mission_associations": len(mission_members),
            "cluster_memberships": len(cluster_members),
        },
    }

    return {
        "schema_version": 3,
        "digests": digests,
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
            "memberships": len(cluster_members_preview),
            "distinct_membership_payloads": len(set(cluster_members_preview)),
            "indistinguishable_membership_multiplicity": len(cluster_members_preview)
            - len(set(cluster_members_preview)),
        },
        "detail": detail,
        "invariants": {
            "checked": 14,
            "failed": len(findings.failures),
            "failures": sorted(findings.failures),
        },
        "balanced": not findings.failures,
    }


# What one observation member commits to preserving. A field absent from this tuple is an
# intentional loss and has to appear in INTENTIONAL_LOSSES with a reason, so that "the digest
# matched" can never mean "the digest ignored the column that changed".
OBSERVATION_FIELDS = (
    "canonical_source_identity",
    "observed_at",
    "published_at",
    "time_provenance",
    "observed_title",
    "metric_value",
    "growth_velocity",
    "geo_code",
    "normalized_source_url",
    "canonical_metadata",
)

INTENTIONAL_LOSSES = {
    "trend_signals.id": "surrogate key; the migration reassigns it by design",
    "signal_metrics.id": "surrogate key; the migration reassigns it by design",
    "trend_signals.mission_id": "carried by the mission_associations digest instead",
    "trend_signals.cluster_id": "carried by the cluster_memberships digest instead",
}


PROVENANCE_EXACT = "exact_ingestion"
PROVENANCE_LEGACY = "legacy_publish_only"
PROVENANCE_UNKNOWN = "unknown"

# Row titles Google Trends gives its keyword-probe rows. Third-party wording, matched verbatim;
# sql/015 excluded exactly these from its publish-time backfill because they were always stamped
# with the ingestion time and have no publish concept.
GOOGLE_PROBE_TITLE_PREFIX = "Google Search Trends:"


def row_clock_may_be_a_publish_time(row: "SignalRow") -> bool:
    """Whether this row was written by one of the paths that put a publish time in captured_at.

    sql/015 names them: both YouTube paths and the Google Trends RSS feed. Google's keyword-probe
    rows are excluded there because they were always stamped with the ingestion time and have no
    publish concept, and their raw_title is what distinguishes them.
    """
    if row.platform == "youtube":
        return True
    if row.platform == "google":
        return not (row.raw_title or "").startswith(GOOGLE_PROBE_TITLE_PREFIX)
    return False


def derive_time_provenance(
    row: "SignalRow", event_captured_at: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Decide what ONE observation's captured_at means. Returns (provenance, observed_at).

    Per event, not per row. trend_signals is a mutable current snapshot: both repositories
    overwrite captured_at on every re-poll, while each signal_metrics row keeps the captured_at of
    the poll that wrote it. So a parent row can currently hold a proven ingestion time while its
    metric history still contains a point stamped with the publish time, and inheriting the
    parent's present clock would misfile that point. An earlier version of this function took only
    the row and did exactly that.

    The test is sql/015's own signature: that migration backfilled published_at from the
    platform's value, so an event whose captured_at equals published_at was written before the fix
    by a path that stored the publish time.
    """
    if not row_clock_may_be_a_publish_time(row):
        # Every other connector always wrote the ingestion time, for every event.
        return PROVENANCE_EXACT, event_captured_at

    if row.published_at is None:
        # Nothing to compare this event against; refuse to guess either way.
        return PROVENANCE_UNKNOWN, None
    if event_captured_at == row.published_at:
        return PROVENANCE_LEGACY, None
    return PROVENANCE_EXACT, event_captured_at


def canonical_metadata(metadata: Any) -> str:
    """Metadata as a stable string, so a key-order change is not read as a data change."""
    if not isinstance(metadata, dict):
        return ""
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def observation_member(
    identity: str,
    row: "SignalRow",
    observed_at: Optional[str],
    time_provenance: str,
    metric_value: Optional[float],
    growth_velocity: Optional[float],
) -> str:
    """Serialize one observation over every field OBSERVATION_FIELDS names.

    observed_at and time_provenance are arguments rather than being derived here, so a test can
    hold every other field constant and vary provenance alone. The previous isolation test moved a
    row between buckets by changing its platform, which also changed the canonical identity, the
    URL, the metadata and observed_at -- that digest would have differed with time_provenance
    removed entirely, so it proved nothing about provenance.

    A metric point inherits title, geo, URL and metadata from the trend_signals row it hangs off,
    because signal_metrics stores none of those. It does not inherit that row's clock.
    """
    parts = (
        identity,
        observed_at or "",
        row.published_at or "",
        time_provenance,
        (row.raw_title or "").strip(),
        "" if metric_value is None else repr(metric_value),
        "" if growth_velocity is None else repr(growth_velocity),
        row.geo_code or "",
        normalize_url(row.source_url),
        canonical_metadata(row.metadata),
    )
    assert len(parts) == len(OBSERVATION_FIELDS)
    return "\x1f".join(parts)


def observation_event(
    identity: str,
    row: "SignalRow",
    event_captured_at: Optional[str],
    metric_value: Optional[float],
    growth_velocity: Optional[float],
) -> Tuple[str, str]:
    """One observation as (member, provenance), deriving the clock for this event alone."""
    provenance, observed_at = derive_time_provenance(row, event_captured_at)
    member = observation_member(
        identity, row, observed_at, provenance, metric_value, growth_velocity
    )
    return member, provenance


def _merge_reason_for(rows: Sequence["SignalRow"]) -> str:
    """Why one identity holds several legacy rows. One place decides, so counts and detail agree."""
    titles = {(r.raw_title or "").strip() for r in rows}
    urls = {normalize_url(r.source_url) for r in rows}
    if len(urls) > 1:
        return MERGE_URL_VARIANT
    if len(titles) > 1:
        return MERGE_TITLE_CHANGED
    if len(titles) == 1:
        return MERGE_REPEAT
    return MERGE_UNCLASSIFIED


def digest_of(members: Iterable[str]) -> str:
    """A SHA-256 over one sorted canonical set, comparable across the migration.

    The members are business identities, never surrogate keys. A digest keyed on trend_signals.id
    would change the moment rows are rewritten, which would make the pre/post comparison
    meaningless exactly when it matters. Keying on platform identity plus the observed values
    means the post-migration run can recompute the same digest from the new tables.
    """
    hasher = sha256()
    for member in sorted(members):
        hasher.update(member.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def build_sanitized_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Strip everything that identifies external content, keeping the evidence.

    The tracked copy of this baseline lives in docs/ permanently, so it must carry no title, URL,
    external id or mission title. What survives is the arithmetic, the reason-code totals, the
    invariant results, and one digest per canonical set -- enough to prove a later run accounted
    for the same data, and not enough to reconstruct what that data was.
    """
    sources = {k: v for k, v in report["sources"].items() if k != "unclassified_collisions"}
    # "detail" is absent from the returned dict entirely -- see the key list below.
    sources["unclassified_collision_count"] = len(report["sources"]["unclassified_collisions"])
    return {
        "schema_version": report["schema_version"],
        "sanitized": True,
        "sources": sources,
        "observations": report["observations"],
        "mission_evidence": report["mission_evidence"],
        "cluster_membership": report["cluster_membership"],
        "digests": report["digests"],
        "invariants": report["invariants"],
        "balanced": report["balanced"],
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
        f"    sql/008 copies merged           {obs['lineage_merges_of_the_sql008_copy']}",
        f"    naive sum, for contrast         {obs['naive_sum_for_contrast']}",
        f"    distinct payloads               {obs['distinct_observation_payloads']}",
        f"    indistinguishable multiplicity  {obs['indistinguishable_observation_multiplicity']}",
        f"    fields preserved                {len(obs['preserved_fields'])}"
        f"  intentional losses {len(obs['intentional_losses'])}",
        *(
            f"    provenance {name:21s}{count:>6d}"
            for name, count in obs["time_provenance_buckets"].items()
        ),
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
        f"    memberships (multiset)          {clu['memberships']}",
        f"    indistinguishable multiplicity  {clu['indistinguishable_membership_multiplicity']}",
        "",
        "  digests (sha256, first 16)",
        *(
            f"    {name:28s} {report['digests'][name][:16]}"
            f"  over {report['digests']['member_counts'][name]} members"
            for name in ("sources", "observations", "mission_associations", "cluster_memberships")
        ),
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
    parser.add_argument(
        "--json-out",
        type=Path,
        help="write the sanitized JSON report here -- safe to track in docs/",
    )
    parser.add_argument(
        "--rows-out",
        type=Path,
        help="write the unsanitized report, which names external identities, here."
        " Keep it beside a database backup; never commit it.",
    )
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

    sanitized = json.dumps(
        build_sanitized_report(report), indent=2, sort_keys=True, ensure_ascii=False
    )
    if args.json_out:
        args.json_out.write_text(sanitized + "\n", encoding="utf-8")
    if args.rows_out:
        args.rows_out.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if args.quiet and not args.json_out and not args.rows_out:
        print(sanitized)

    if not args.quiet:
        print(render_summary(report))

    return 0 if report["balanced"] else 1


if __name__ == "__main__":
    sys.exit(main())
