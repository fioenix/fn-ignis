"""The one definition of what a legacy row means as an observation.

Three callers must agree exactly, or the migration cannot be checked at all:

  the audit    turns legacy rows into the members it digests, to state what should exist
  the backfill turns the same rows into the observations it writes
  the verifier digests what was actually written, and compares

If the backfill restated any of this, the audit would be measuring a corpus the backfill does
not produce, and a matching digest would mean nothing. So the projection lives here and the
scripts import it.

What the projection deliberately does not decide: how a source is identified. That is
ignis.domain.source_identity, which the live write path uses too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from ignis.domain.source_identity import normalize_url

# The fields an observation conserves across the migration, in the order they are serialized.
# Anything dropped from here has to be declared an intentional loss with a reason, so that
# "the digests match" can never mean "the digest ignored the column that changed".
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
    "identity_source",
)

PROVENANCE_EXACT = "exact_ingestion"
PROVENANCE_LEGACY = "legacy_publish_only"
PROVENANCE_UNKNOWN = "unknown"

# Row titles Google Trends gives its keyword-probe rows. Third-party wording, matched verbatim;
# sql/015 excluded exactly these from its publish-time backfill because they were always stamped
# with the ingestion time and have no publish concept.
GOOGLE_PROBE_TITLE_PREFIX = "Google Search Trends:"


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
    # signal_metrics.id. Not part of the business digest -- it is a surrogate key the migration
    # reassigns -- but the backfill needs it to derive a deterministic observation id, and the
    # lineage rule below needs it to pick the same row on every run.
    metric_id: Optional[str] = None

    @property
    def payload(self) -> Tuple[Optional[str], Optional[float], Optional[float]]:
        return (self.captured_at, self.metric_value, self.growth_velocity)


def row_clock_may_be_a_publish_time(row: SignalRow) -> bool:
    """Whether this row came from a code path that stamped captured_at with a publish time.

    Measured in sql/015: of the fifteen places a connector set captured_at, three set the
    content's publish time instead -- both YouTube sites and the Google Trends RSS feed. The
    Google keyword probes on the same platform were always stamped with the ingestion time.
    """
    if row.platform == "youtube":
        return True
    if row.platform == "google":
        return not (row.raw_title or "").startswith(GOOGLE_PROBE_TITLE_PREFIX)
    return False


def derive_time_provenance(
    row: SignalRow, event_captured_at: Optional[str]
) -> Tuple[str, Optional[str]]:
    """(provenance, observed_at) for one collection event.

    Derived per event, not per row. Both repositories overwrite trend_signals.captured_at on
    every poll while each signal_metrics row keeps the clock it was written with, so a row whose
    own clock is a publish time can still carry a metric point collected at a known time.
    """
    if not row_clock_may_be_a_publish_time(row):
        return PROVENANCE_EXACT, event_captured_at
    if row.published_at is None:
        return PROVENANCE_UNKNOWN, None
    if event_captured_at == row.published_at:
        return PROVENANCE_LEGACY, None
    return PROVENANCE_EXACT, event_captured_at


def canonical_metadata(metadata: Any) -> str:
    """Metadata as one comparable string, key order and spacing removed."""
    if not isinstance(metadata, dict):
        return ""
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def observation_member(
    identity: str,
    identity_source: str,
    row: SignalRow,
    observed_at: Optional[str],
    time_provenance: str,
    metric_value: Optional[float],
    growth_velocity: Optional[float],
) -> str:
    """Serialize one observation over every field OBSERVATION_FIELDS names.

    observed_at, time_provenance and identity_source are arguments rather than being derived
    here, so a test can hold every other field constant and vary one alone.

    A metric point inherits title, geo, URL, metadata and route from the trend_signals row it
    hangs off, because signal_metrics stores none of those. It does not inherit that row's clock.
    """
    return serialize_observation(
        identity=identity,
        observed_at=observed_at,
        published_at=row.published_at,
        time_provenance=time_provenance,
        observed_title=row.raw_title,
        metric_value=metric_value,
        growth_velocity=growth_velocity,
        geo_code=row.geo_code,
        source_url=row.source_url,
        metadata=row.metadata,
        identity_source=identity_source,
    )


def serialize_observation(
    identity: str,
    observed_at: Optional[str],
    published_at: Optional[str],
    time_provenance: str,
    observed_title: Optional[str],
    metric_value: Optional[float],
    growth_velocity: Optional[float],
    geo_code: Optional[str],
    source_url: Optional[str],
    metadata: Any,
    identity_source: Optional[str],
) -> str:
    """The single serializer, called with legacy values and with stored ones.

    The post-migration verifier passes what the new tables actually hold -- observed_at and
    time_provenance especially -- rather than deriving them again. Deriving on the way out would
    let the verifier silently repair a migration that wrote the wrong value, which is the one
    failure the whole reconciliation exists to catch.
    """
    parts = (
        identity,
        observed_at or "",
        published_at or "",
        time_provenance or "",
        (observed_title or "").strip(),
        "" if metric_value is None else repr(metric_value),
        "" if growth_velocity is None else repr(growth_velocity),
        geo_code or "",
        normalize_url(source_url),
        canonical_metadata(metadata),
        identity_source or "",
    )
    assert len(parts) == len(OBSERVATION_FIELDS)
    return "\x1f".join(parts)


def observation_event(
    identity: str,
    identity_source: str,
    row: SignalRow,
    event_captured_at: Optional[str],
    metric_value: Optional[float],
    growth_velocity: Optional[float],
) -> Tuple[str, str]:
    """One observation as (member, provenance), deriving the clock for this event alone."""
    provenance, observed_at = derive_time_provenance(row, event_captured_at)
    member = observation_member(
        identity, identity_source, row, observed_at, provenance, metric_value, growth_velocity
    )
    return member, provenance


@dataclass(frozen=True)
class ObservationEvent:
    """One collection event the migration has to produce, with the lineage it came from."""

    row: SignalRow
    identity: str
    identity_source: str
    observed_at: Optional[str]
    time_provenance: str
    metric_value: Optional[float]
    growth_velocity: Optional[float]
    # Which legacy row this event is: the trend_signals row itself, or one signal_metrics point.
    # The backfill derives a deterministic observation id from it, so a second run reproduces
    # the same ids instead of a second set of observations.
    lineage_table: str
    lineage_id: str

    @property
    def member(self) -> str:
        return observation_member(
            self.identity,
            self.identity_source,
            self.row,
            self.observed_at,
            self.time_provenance,
            self.metric_value,
            self.growth_velocity,
        )


def observation_events_for_row(
    row: SignalRow,
    identity: str,
    identity_source: str,
    points: Iterable[MetricPoint],
) -> Iterator[ObservationEvent]:
    """Every collection event one legacy row stands for, parent first.

    One observation per trend_signals row, plus one per signal_metrics point that does not
    repeat its parent row's whole metric payload. Exactly one repeating point is dropped: it is
    the copy sql/008 made of the row itself, not a second sighting.

    When several points share that payload, the dropped one is chosen by the lowest
    signal_metrics.id rather than by iteration order, so two runs drop the same row. Which one is
    dropped cannot change the resulting multiset -- they are identical on every conserved field
    -- but it does change which observation id survives, and an id that moves between runs is an
    id the migration cannot be re-run against.
    """
    row_payload = (row.captured_at, row.metric_value, row.growth_velocity)
    provenance, observed_at = derive_time_provenance(row, row.captured_at)
    yield ObservationEvent(
        row=row,
        identity=identity,
        identity_source=identity_source,
        observed_at=observed_at,
        time_provenance=provenance,
        metric_value=row.metric_value,
        growth_velocity=row.growth_velocity,
        lineage_table="trend_signals",
        lineage_id=row.signal_id,
    )

    ordered = list(points)
    repeats = [p for p in ordered if p.payload == row_payload]
    dropped = min(repeats, key=_metric_sort_key) if repeats else None
    for point in ordered:
        if dropped is not None and point is dropped:
            continue
        point_provenance, point_observed_at = derive_time_provenance(row, point.captured_at)
        yield ObservationEvent(
            row=row,
            identity=identity,
            identity_source=identity_source,
            observed_at=point_observed_at,
            time_provenance=point_provenance,
            metric_value=point.metric_value,
            growth_velocity=point.growth_velocity,
            lineage_table="signal_metrics",
            lineage_id=point.metric_id or "",
        )


def _metric_sort_key(point: MetricPoint) -> Tuple[int, str]:
    """Numeric where signal_metrics.id is a BIGSERIAL, lexicographic otherwise."""
    raw = point.metric_id or ""
    try:
        return (0, f"{int(raw):020d}")
    except (TypeError, ValueError):
        return (1, raw)


def digest_of(members: Iterable[str]) -> str:
    """A SHA-256 over one sorted multiset, comparable across the migration.

    Members are hashed one at a time from a sorted sequence, so repeated members count. A set
    here would erase the multiplicity the whole reconciliation exists to conserve: two
    collection events identical on every conserved field are still two events.
    """
    hasher = sha256()
    for member in sorted(members):
        hasher.update(member.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def group_points_by_signal(points: Iterable[MetricPoint]) -> Dict[str, List[MetricPoint]]:
    grouped: Dict[str, List[MetricPoint]] = {}
    for point in points:
        grouped.setdefault(point.signal_id, []).append(point)
    return grouped
