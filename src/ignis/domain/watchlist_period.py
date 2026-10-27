"""Comparing two complete listening periods of a watchlist (Spec 016, US2).

Pure assembly: the use case loads a watchlist's runs, their observations, qualifications and probe
outcomes, and this module turns them into the period snapshot. Every channel keeps its own
indicator in its own unit (research R4, R11); nothing here adds values across channels.
"""

from __future__ import annotations

import re
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ignis.domain.author_identity import scrub_handle_links
from ignis.domain.listening_period import (
    LISTENING_TZ,
    MAX_MISSING_SHARE,
    Period,
    comparable,
    counted_value,
    local_date,
    missing_days,
    place_observation,
)
from ignis.domain.watchlist import ListeningPlan, plan_in_effect

# R3: only a collection that measured something, or measured a zero, completes a channel-day.
COMPLETING_STATUSES = frozenset({"HEALTHY", "EMPTY_NO_DATA"})
CHANNEL_ORDER = ("google", "youtube", "tiktok", "threads", "reels")
# Channels whose figures come from the posts Ignis happened to collect, not the whole platform.
SAMPLED_CHANNELS = frozenset({"tiktok", "threads", "reels"})
MAX_ITEMS = 3
MAX_TERMS = 10
EXCERPT_LENGTH = 280
# Threads trending topics carry a post count, or a placeholder of 1000 when it is missing (R11).
THREADS_TRENDING_SOURCE = "threads_trending_topics"

# (kind, unit) per channel, in display order. YouTube's indicator is a count of uploads.
INDICATORS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "google": (("interest", "approximate searches (Google Trends RSS), mean per item"),),
    "youtube": (("new_uploads", "items"),),
    "tiktok": (("views", "plays"), ("interactions", "likes + comments + shares")),
    "threads": (("views", "views"), ("interactions", "likes + replies + reposts + quotes")),
    "reels": (("views", "plays"), ("interactions", "likes + comments")),
}
INTERACTION_FIELDS: Dict[str, Tuple[Tuple[str, ...], ...]] = {
    # Each tuple lists the alternative names one counter is stored under.
    "tiktok": (("likes",), ("comments",), ("shares",)),
    "threads": (("like_count",), ("reply_count",), ("reposts",), ("quotes",)),
    "reels": (("like_count", "likes"), ("comment_count", "comments")),
}


@dataclass(frozen=True)
class PeriodCoverage:
    """One probe outcome of a watchlist run, reduced to what coverage needs (R3)."""

    channel: str
    status: str
    queried_keywords: Tuple[str, ...]
    completed_at: datetime
    # Whether every observation this run collected on the channel carries a judgment. Unjudged
    # evidence is never counted (FR-010), so its day cannot stand as a measured one.
    judged: bool = True
    path_metadata: Mapping[str, Any] | None = field(default=None, kw_only=True)


@dataclass(frozen=True)
class PeriodItem:
    """One source as the watchlist's runs saw it: every observation, with its own metadata."""

    source_id: str
    channel: str
    published_at: Optional[datetime]
    title: str
    excerpt: str
    # Identity-free already, or None for "link unavailable".
    link: Optional[str]
    # A current qualification of QUALIFIED_SUPPORT or CONTEXT_ONLY in one of the runs (R4).
    relevant: bool
    # The keywords whose query returned it, where the connector recorded them.
    query_keywords: Tuple[str, ...]
    observations: Tuple[Tuple[Optional[datetime], float, Mapping[str, Any]], ...]
    # The source's first sighting in any run of the watchlist, read beyond the compared periods,
    # so an item without a publication time keeps one period whichever comparison is asked.
    first_seen: Optional[datetime] = None


@dataclass(frozen=True)
class TermsPolicy:
    rising_min_count: int = 2
    rising_min_growth: float = 0.5
    noise: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class SeenSnapshot(PeriodCoverage):
    """One run/channel outcome at its exact completion time, with only that run's items."""

    items: Tuple[PeriodItem, ...] = ()


def collection_path_identity(metadata: Mapping[str, Any] | None) -> dict:
    """Classify persisted measurement proof only; never infer a path from channel or dates."""
    metadata = metadata or {}
    path = metadata.get("collection_path")
    legacy = metadata.get("source") == "threads_browser_session" and metadata.get("tier") == "TIER_1_BROWSER_SESSION"
    basis = "observation_metadata" if metadata.get("collection_path_basis") == "observation_metadata" else "explicit_metadata"
    if legacy and path and path != "playwright:threads_session":
        return {"collection_path": None, "basis": "conflicting_metadata"}
    if not path and legacy:
        path, basis = "playwright:threads_session", "legacy_source_and_tier"
    if not isinstance(path, str) or not re.fullmatch(r"[a-z_]+:[A-Za-z0-9_.:-]+", path):
        return {"collection_path": None, "basis": "unknown"}
    sampling = metadata.get("sampling", {})
    if not isinstance(sampling, Mapping):
        return {"collection_path": None, "basis": "conflicting_metadata"}
    # Measurement semantics only. Random request/session ids, ports and capture clocks are not identity.
    sampling = {k: sampling[k] for k in ("ordering", "limit", "result_limit", "window", "selection") if k in sampling}
    if any(not isinstance(v, (str, int, float, bool, type(None))) for v in sampling.values()):
        return {"collection_path": None, "basis": "conflicting_metadata"}
    revision = metadata.get("connector_revision") or path.split(":", 1)[1]
    if not isinstance(revision, str):
        return {"collection_path": None, "basis": "conflicting_metadata"}
    return {"collection_path": path, "connector_revision": revision, "sampling": sampling, "basis": basis}


def _path_gate(paths: Mapping[str, list]) -> tuple[dict, list]:
    """Preserve unknown legacy pairs; refuse a possible change or a mixed measurement path."""
    sets, identities, reasons = {}, {}, []
    for which, facts in paths.items():
        descriptors = [collection_path_identity(fact) for fact in facts] or [collection_path_identity(None)]
        unique = {json.dumps(d, sort_keys=True): d for d in descriptors}
        sets[which] = [unique[k] for k in sorted(unique)]
        identities[which] = {json.dumps({k: v for k, v in d.items() if k != "basis"}, sort_keys=True)
                             for d in descriptors if d["collection_path"] is not None}
        unknown = any(d["collection_path"] is None for d in descriptors)
        if (len(identities[which]) > 1 or (identities[which] and unknown)) and "collection_path_mixed" not in reasons:
            reasons.append("collection_path_mixed")
    if identities["current"] and identities["previous"] and identities["current"] != identities["previous"]:
        reasons.append("collection_path_changed")
    if bool(identities["current"]) != bool(identities["previous"]):
        reasons.append("collection_path_unknown")
    # No proof on either side preserves the old response as well as the old comparison.
    return (sets if any(identities.values()) else {}), reasons


def _counter_views(paths):
    """Keep displayed components apart from exact aggregates, including when a path gate refuses."""
    return {which: [[{k: c.get(k) for k in ("kind", "unit", "raw_display", "value", "precision")}
                      for c in fact.get("counters", ()) if isinstance(c, Mapping)]
                    for fact in facts if fact and "counters" in fact] for which, facts in paths.items()}


def _snapshot_entries(snapshot, queries, single_topic):
    """One source-membership authority shared by measurements and the raw provenance gate."""
    return [e for e in _merge(snapshot.items, dated_google=False)
            if e.channel == snapshot.channel and _belongs(e, queries, single_topic)]


def _snapshot_paths(snapshot, queries, single_topic):
    selected = {(e.channel, e.source_id) for e in _snapshot_entries(snapshot, queries, single_topic)}
    rows = [i for i in snapshot.items if i.relevant and (i.channel, i.source_id) in selected]
    facts = [metadata for i in rows for _, _, metadata in i.observations]
    if snapshot.path_metadata is not None:
        facts.append(snapshot.path_metadata)
    return facts or [None]


def _created_paths(raw_items, placed, completing, channel, queries, single_topic, spans, window_days):
    paths = {which: [c.path_metadata for c in completing if span.contains(local_date(c.completed_at))]
             for which, span in spans.items()}
    # Placement is source-wide, but every original qualified observation supplies its own path
    # before latest-counter selection. Dedup must not hide two methods for the same post.
    anchors = {(e.source_id, e.published_at if channel == "google" else None): (day, anchor)
               for e, day, _, anchor in placed if e.channel == channel}
    for item in raw_items:
        if item.channel != channel or not item.relevant:
            continue
        key = (item.source_id, item.published_at if channel == "google" else None)
        if key not in anchors:
            continue
        day, anchor = anchors[key]
        for which, span in spans.items():
            if span.contains(day):
                paths[which].extend(metadata for observed, _, metadata in item.observations
                                    if observed is not None and anchor <= observed <= anchor + timedelta(days=window_days))
    sets, reasons = _path_gate(paths)
    return sets, reasons, _counter_views(paths)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _plain(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(value, 4)


def channel_values(channel: str, metric_value: Any, metadata: Mapping[str, Any]) -> Dict[str, float]:
    """The indicator values one observation holds, each read from the field that means it (R11).

    A value the observation does not carry is absent, never zero, so the item is listed and not
    counted for that indicator.
    """
    metadata = metadata or {}
    if "counters" in metadata:
        # Structured host components supersede legacy copies. Share never aliases quotes.
        required = {"likes", "replies", "reposts", "quotes"} if channel == "threads" else set()
        components = metadata.get("counters") or []
        exact = {c.get("kind"): _number(c.get("value")) for c in components
                 if isinstance(c, Mapping) and c.get("precision") == "exact"}
        return ({"interactions": sum(exact[k] for k in required)}
                if required and required.issubset(exact) and all(exact[k] is not None for k in required) else {})
    values: Dict[str, float] = {}
    if channel == "google":
        interest = _number(metric_value)
        if interest:
            values["interest"] = interest
        return values
    if channel == "tiktok":
        if metadata.get("metric_kind") == "views" and metadata.get("metric_known") is not False:
            views = _number(metric_value)
            if views is not None:
                values["views"] = views
    elif channel == "threads":
        if metadata.get("source") == THREADS_TRENDING_SOURCE:
            return {}
        views = _number(metadata.get("views"))
        if views:
            values["views"] = views
    elif channel == "reels":
        plays = _number(metadata.get("play_count"))
        if plays:
            values["views"] = plays
    else:
        return values
    counters = [
        next((_number(metadata.get(name)) for name in names if _number(metadata.get(name)) is not None), None)
        for names in INTERACTION_FIELDS[channel]
    ]
    present = [counter for counter in counters if counter is not None]
    # The Threads Graph API writes 0 for every counter when insights are missing (R11).
    unreported = channel == "threads" and not values and not any(present)
    if present and not unreported:
        values["interactions"] = sum(present)
    return values


@dataclass
class _Merged:
    source_id: str
    channel: str
    published_at: Optional[datetime]
    title: str
    excerpt: str
    link: Optional[str]
    relevant: bool
    query_keywords: set
    observations: List[Tuple[datetime, float, Mapping[str, Any]]]
    first_seen: Optional[datetime] = None


def _merge(items: Iterable[PeriodItem], *, dated_google: bool = True) -> List[_Merged]:
    """One entry per source, so two runs that saw the same post count it once (SC-001)."""
    merged: Dict[Tuple[str, str, Optional[datetime]], _Merged] = {}
    for item in items:
        # A Google Trends source is a search term; each appearance is its own dated measurement.
        key = (item.channel, item.source_id, item.published_at if dated_google and item.channel == "google" else None)
        entry = merged.get(key)
        if entry is None:
            entry = merged[key] = _Merged(item.source_id, item.channel, item.published_at, item.title,
                                          item.excerpt, item.link, False, set(), [])
        entry.published_at = entry.published_at or item.published_at
        entry.title, entry.excerpt = entry.title or item.title, entry.excerpt or item.excerpt
        entry.link = entry.link or item.link
        entry.relevant = entry.relevant or item.relevant
        entry.query_keywords.update(keyword.casefold() for keyword in item.query_keywords)
        # A Google Trends source is a search term measured per dated appearance (above), so a
        # source-wide first sighting would misplace a later appearance; it applies to posts only.
        if item.channel != "google" and item.first_seen is not None and (
                entry.first_seen is None or item.first_seen < entry.first_seen):
            entry.first_seen = item.first_seen
        # Only an observation judged relevant can be counted; another run's judgment of the same
        # source does not qualify it (FR-010).
        if item.relevant:
            entry.observations.extend(obs for obs in item.observations if obs[0] is not None)
    return [entry for entry in merged.values() if entry.observations]


def _mentions(text: str, keyword: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text) is not None


def _belongs(entry: _Merged, queries: frozenset, single_topic: bool) -> bool:
    """The query that found the item decides, even after its topic left the watchlist. Without a
    recorded query, a one-topic watchlist holds the item; otherwise its text decides, word by word."""
    if entry.query_keywords:
        return bool(set(k.casefold() for k in entry.query_keywords) & queries)
    if single_topic:
        return True
    text = f"{entry.title} {entry.excerpt}".casefold()
    return any(_mentions(text, keyword) for keyword in queries)


def _placed(entry: _Merged) -> Tuple[date, str, datetime]:
    """(local day, basis, counting anchor). Without a plausible publication time the first
    collection anchors the counting window as well as the day."""
    first = min([observed for observed, _, _ in entry.observations]
                + ([entry.first_seen] if entry.first_seen is not None else []))
    day, basis = place_observation(entry.published_at, first)
    return day, basis, entry.published_at if basis == "published" else first


def _change(current: Optional[float], previous: Optional[float]) -> Optional[Dict[str, Any]]:
    if current is None or previous is None:
        return None
    return {"absolute": _plain(current - previous),
            "relative": round((current - previous) / previous, 4) if previous else None}


_TOKEN = re.compile(r"\w+", re.UNICODE)
# Links, @mentions and the stored mention tokens (@[user], @[declared:<id>]) are never terms.
_NOT_WORDS = re.compile(r"https?://\S+|@\[[^\]]*\]|@\S+|\[link\]", re.IGNORECASE)


def _terms(entry: _Merged, keywords: frozenset, noise: frozenset) -> set:
    """Two-word terms: one Vietnamese syllable rarely carries the meaning a term needs."""
    pairs = set()
    # Title and excerpt are paired apart, so no term spans the boundary between them.
    for field_text in (entry.title, entry.excerpt):
        text = _NOT_WORDS.sub(" ", field_text or "").casefold()
        tokens = [t for t in _TOKEN.findall(text) if len(t) > 1 and not t.isdigit() and t not in noise]
        pairs.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    return {pair for pair in pairs if not any(pair in keyword for keyword in keywords)}


def _term_lists(current: Sequence[Tuple[_Merged, str]], previous: Sequence[_Merged],
                keywords: frozenset, policy: TermsPolicy, *,
                current_snapshots: int = 1, previous_snapshots: int = 1) -> Tuple[List[dict], List[dict]]:
    now_counts: Dict[str, int] = defaultdict(int)
    basis: Dict[str, Dict[str, int]] = defaultdict(lambda: {"published": 0, "collection_date": 0})
    for entry, entry_basis in current:
        for term in _terms(entry, keywords, policy.noise):
            now_counts[term] += 1
            basis[term][entry_basis] += 1
    before: Dict[str, int] = defaultdict(int)
    for entry in previous:
        for term in _terms(entry, keywords, policy.noise):
            before[term] += 1
    new, rising = [], []
    for term, count in now_counts.items():
        count = count / current_snapshots
        prior = before[term] / previous_snapshots
        row = {"term": term, "current_items": _plain(count), "previous_items": _plain(prior),
               "basis": {key: _plain(value / current_snapshots) for key, value in basis[term].items()}}
        if not before[term]:
            new.append(row)
        elif (count - prior >= policy.rising_min_count
              and count >= prior * (1 + policy.rising_min_growth)):
            rising.append(row)
    order = lambda row: (-row["current_items"], row["term"])  # noqa: E731
    return sorted(rising, key=order)[:MAX_TERMS], sorted(new, key=order)[:MAX_TERMS]


def _indicator(channel: str, kind: str, unit: str, current: List[Tuple[_Merged, str, datetime]],
               previous: List[Tuple[_Merged, str, datetime]], window_days: int) -> Dict[str, Any]:
    def measure(rows):
        if kind == "new_uploads":
            return float(len(rows)), 0
        counted = []
        for entry, _, anchor in rows:
            series = [(observed, channel_values(channel, metric, metadata).get(kind))
                      for observed, metric, metadata in entry.observations]
            value = counted_value(anchor, [(at, v) for at, v in series if v is not None], window_days=window_days)
            if value is not None:
                counted.append(value)
        uncounted = len(rows) - len(counted)
        if not rows and kind != "interest":
            # A comparable channel measured every day and found nothing: a measured zero.
            return 0.0, 0
        if not counted:
            return None, uncounted
        return (sum(counted) / len(counted) if kind == "interest" else sum(counted)), uncounted

    now_value, now_uncounted = measure(current)
    before_value, before_uncounted = measure(previous)
    return {"kind": kind, "unit": unit, "current": _plain(now_value), "previous": _plain(before_value),
            "change": _change(now_value, before_value),
            "uncounted_items": {"current": now_uncounted, "previous": before_uncounted}}


def _representative(rows: List[Tuple[_Merged, str, datetime]], window_days: int) -> List[dict]:
    def weight(row):
        entry, _, anchor = row
        for kind in ("views", "interactions", "interest"):
            series = [(observed, channel_values(entry.channel, metric, metadata).get(kind))
                      for observed, metric, metadata in entry.observations]
            value = counted_value(anchor, [(at, v) for at, v in series if v is not None], window_days=window_days)
            if value is not None:
                return value
        return 0.0

    # Units differ between channels, so rank within a channel and take channels in turn.
    by_channel: Dict[str, List[Tuple[_Merged, str, datetime]]] = defaultdict(list)
    for row in rows:
        by_channel[row[0].channel].append(row)
    queues = [sorted(found, key=lambda row: (-weight(row), -row[2].timestamp(), row[0].source_id))
              for _, found in sorted(by_channel.items(), key=lambda pair: (
                  CHANNEL_ORDER.index(pair[0]) if pair[0] in CHANNEL_ORDER else len(CHANNEL_ORDER), pair[0]))]
    picked: List[Tuple[_Merged, str, datetime]] = []
    while len(picked) < MAX_ITEMS and any(queues):
        for queue in queues:
            if queue and len(picked) < MAX_ITEMS:
                picked.append(queue.pop(0))
    shown = []
    for entry, basis, _ in picked:
        excerpt = scrub_handle_links((entry.title or entry.excerpt or "").strip())
        shown.append({
            "excerpt": excerpt[:EXCERPT_LENGTH],
            "link": entry.link,
            "channel": entry.channel,
            "published_on": local_date(entry.published_at).isoformat() if basis == "published" else None,
            "basis": basis,
        })
    return shown


def compare_periods(
    *,
    topics: Sequence[Mapping[str, Any]],
    items: Iterable[PeriodItem],
    coverage: Iterable[PeriodCoverage],
    period: Period,
    now: datetime,
    policy: TermsPolicy,
    versions: Mapping[date, Sequence[int]],
    window_days: int = 7,
) -> Dict[str, Any]:
    """The snapshot comparing `period` with the one before it, or a refusal while it is open."""
    previous = period.previous()
    if not period.is_complete(now):
        return {"status": "REFUSED", "reason_code": "PERIOD_INCOMPLETE", "period": period.to_payload(),
                "completes_at": period.completes_at.isoformat(),
                "error": "Only complete periods can be compared; this one is still open."}
    coverage = list(coverage)
    items = list(items)
    merged = _merge(items)
    channels = sorted({c.channel for c in coverage} | {e.channel for e in merged},
                      key=lambda c: (CHANNEL_ORDER.index(c) if c in CHANNEL_ORDER else len(CHANNEL_ORDER), c))
    single_topic = len(topics) == 1
    topic_rows = []
    for topic in topics:
        keywords = frozenset(k.casefold() for k in topic.get("keywords", ()))
        # A run also queries each brand by its declared name (research R1).
        queries = keywords | {str(b.get("declared_name", "")).casefold() for b in topic.get("brands", ()) or ()} - {""}
        mine = [e for e in merged if e.relevant and _belongs(e, queries, single_topic)]
        placed = [(e, *_placed(e)) for e in mine]
        topic_items: List[Tuple[_Merged, str, datetime]] = []
        cells = []
        for channel in channels:
            completing = [c for c in coverage
                          if c.channel == channel and c.status in COMPLETING_STATUSES
                          and (not c.queried_keywords or {k.casefold() for k in c.queried_keywords} & queries)]
            days = {local_date(c.completed_at) for c in completing}
            unjudged_days = {local_date(c.completed_at) for c in completing if not c.judged}
            gaps = {"current": missing_days(period, days), "previous": missing_days(previous, days)}
            # A day with any unjudged run would be undercounted, or read as a measured zero: keep it
            # apart until every run of that day is judged.
            unjudged = {which: [d for d in span.days if d in unjudged_days]
                        for which, span in (("current", period), ("previous", previous))}
            in_period = {
                which: [(e, basis, anchor) for e, day, basis, anchor in placed
                        if e.channel == channel and span.contains(day)]
                for which, span in (("current", period), ("previous", previous))
            }
            cell: Dict[str, Any] = {
                "axis": "created",
                "channel": channel,
                "measured_on_sample": channel in SAMPLED_CHANNELS,
                "missing_days": {which: [d.isoformat() for d in gap] for which, gap in gaps.items()},
            }
            reasons = [f"{which}_period_missing_days" for which, span in (("current", period), ("previous", previous))
                       if not comparable(span, gaps[which])]
            reasons += [f"{which}_period_unjudged_days" for which in ("current", "previous") if unjudged[which]]
            if any(unjudged.values()):
                cell["unjudged_days"] = {which: [d.isoformat() for d in found] for which, found in unjudged.items()}
            path_sets, path_reasons, components = _created_paths(items, placed, completing, channel, queries, single_topic,
                {"current": period, "previous": previous}, window_days)
            if path_sets:
                cell["collection_paths"] = path_sets
            if any(components.values()):
                cell["counter_components"] = components
            reasons.extend(path_reasons)
            topic_items.extend(in_period["current"])
            if reasons:
                cells.append({**cell, "status": "not_comparable", "reasons": reasons})
                continue
            rising, new = _term_lists([(e, b) for e, b, _ in in_period["current"]],
                                      [e for e, _, _ in in_period["previous"]], keywords, policy)
            cells.append({
                **cell,
                "status": "comparable",
                "indicators": [_indicator(channel, kind, unit, in_period["current"], in_period["previous"], window_days)
                               for kind, unit in INDICATORS.get(channel, ())],
                "basis": {which: {"published": sum(1 for _, b, _ in rows if b == "published"),
                                  "collection_date": sum(1 for _, b, _ in rows if b == "collection_date")}
                          for which, rows in in_period.items()},
                "rising_terms": rising,
                "new_terms": new,
            })
        topic_rows.append({"name": topic.get("name"), "channels": cells,
                           "items": _representative(topic_items, window_days)})
    return {
        "status": "OK",
        "periods": {
            "current": {**period.to_payload(), "versions": sorted(versions.get(period.start, ()))},
            "previous": {**previous.to_payload(), "versions": sorted(versions.get(previous.start, ()))},
        },
        "topics": topic_rows,
    }


def period_listening_plans(plans: Sequence[ListeningPlan], period: Period) -> Dict[str, Optional[ListeningPlan]]:
    """Read the history at each period's local midnight, never at display time."""
    return {which: plan_in_effect(plans, datetime.combine(span.start, time.min, LISTENING_TZ))
            for which, span in (("current", period), ("previous", period.previous()))}


def compare_seen_periods(
    *, topics: Sequence[Mapping[str, Any]], snapshots: Sequence[SeenSnapshot],
    plans: Sequence[ListeningPlan], period: Period, policy: TermsPolicy,
    first_snapshots: Optional[Mapping[Tuple[str, str], datetime]] = None,
) -> List[List[Dict[str, Any]]]:
    """Per-topic channel cells; successful run/channel snapshots are the denominator.

    Sources deduplicate within a snapshot, never across snapshots. Missing counters stay unknown;
    an empty, judged snapshot measures zero. No created-view counting window applies here.
    """
    # Supplied by the use case across the entire watchlist history, including older runs.
    # Pure callers can instead supply the whole snapshot history, including irrelevant items.
    first = dict(first_snapshots or {})
    for snapshot in snapshots:
        if snapshot.status not in COMPLETING_STATUSES:
            continue
        for item in snapshot.items:
            key = (snapshot.channel, item.source_id)
            first[key] = min(first.get(key, snapshot.completed_at), snapshot.completed_at)
    spans = {"current": period, "previous": period.previous()}
    effective = period_listening_plans(plans, period)
    called_for = {which: plan.snapshots_per_period if plan and plan.period_kind == period.kind.value else None
                  for which, plan in effective.items()}
    channels = sorted({s.channel for s in snapshots},
                      key=lambda c: (CHANNEL_ORDER.index(c) if c in CHANNEL_ORDER else len(CHANNEL_ORDER), c))
    rows = []
    for topic in topics:
        keywords = frozenset(k.casefold() for k in topic.get("keywords", ()))
        queries = keywords | {str(b.get("declared_name", "")).casefold()
                              for b in topic.get("brands", ()) or ()} - {""}
        cells = []
        for channel in channels:
            held = {which: [s for s in snapshots if s.channel == channel and s.status in COMPLETING_STATUSES
                            and span.contains(local_date(s.completed_at))
                            and {k.casefold() for k in s.queried_keywords} & queries]
                    for which, span in spans.items()}
            counts = {which: len(found) for which, found in held.items()}
            cell = {"axis": "seen", "channel": channel, "measured_on_sample": channel in SAMPLED_CHANNELS,
                    "snapshots": counts, "snapshots_called_for": dict(called_for)}
            reasons = []
            if any(value is None for value in called_for.values()):
                reasons.append("seen_period_without_cadence")
            if any(expected is not None and expected - counts[which] > MAX_MISSING_SHARE * expected
                   for which, expected in called_for.items()):
                reasons.append("seen_period_missing_snapshots")
            if any(not s.judged for found in held.values() for s in found):
                reasons.append("seen_period_unjudged_snapshots")
            path_facts = {which: [fact for s in found
                for fact in _snapshot_paths(s, queries, len(topics) == 1)] for which, found in held.items()}
            path_sets, path_reasons = _path_gate(path_facts)
            components = _counter_views(path_facts)
            if path_sets:
                cell["collection_paths"] = path_sets
            if any(components.values()):
                cell["counter_components"] = components
            reasons.extend(path_reasons)
            if reasons:
                cells.append({**cell, "status": "not_comparable", "reasons": reasons})
                continue
            # Keep one merged entry per source in each snapshot, using only its own qualified
            # observations and query bindings. Repeated appearances still count in each snapshot.
            entries = {which: [(s, e) for s in found for e in _snapshot_entries(s, queries, len(topics) == 1)]
                       for which, found in held.items()}
            measurements = {which: _seen_values(entries[which], span, counts[which], first)
                            for which, span in spans.items()}
            indicators = []
            for kind, unit in (("relevant_shown", "items per snapshot"),
                               ("views_visible", "views per snapshot"),
                               ("interactions_visible", "interactions per snapshot"),
                               ("first_seen", "items per snapshot"),
                               ("created_in_period", "items per snapshot")):
                current, uncounted_now = measurements["current"][kind]
                previous, uncounted_before = measurements["previous"][kind]
                indicators.append({"kind": kind, "unit": unit, "current": _plain(current),
                                   "previous": _plain(previous), "change": _change(current, previous),
                                   "uncounted_items": {"current": uncounted_now, "previous": uncounted_before}})
            rising, new = _term_lists([(e, "collection_date") for _, e in entries["current"]],
                                      [e for _, e in entries["previous"]], keywords, policy,
                                      current_snapshots=counts["current"], previous_snapshots=counts["previous"])
            cells.append({**cell, "status": "comparable", "indicators": indicators,
                          "rising_terms": rising, "new_terms": new})
        rows.append(cells)
    return rows


def _seen_channel_values(channel: str, metric_value: Any, metadata: Mapping[str, Any]) -> Dict[str, float]:
    """Read snapshot counters without changing the created view's channel indicators."""
    if channel != "youtube":
        return channel_values(channel, metric_value, metadata)
    values: Dict[str, float] = {}
    views = _number(metadata.get("views"))
    if views is not None:
        values["views"] = views
    likes, comments = _number(metadata.get("likes")), _number(metadata.get("comments"))
    # A partial total is unknown; explicit zero counters still measure zero interactions.
    if likes is not None and comments is not None:
        values["interactions"] = likes + comments
    return values


def _seen_values(entries: Sequence[Tuple[SeenSnapshot, _Merged]], period: Period,
                 snapshots: int, first_snapshots: Mapping[Tuple[str, str], datetime],
                 ) -> Dict[str, Tuple[Optional[float], int]]:
    """Average sums by snapshots held; report absent counters rather than inventing them."""
    values = {"relevant_shown": (len(entries) / snapshots, 0)}
    first_seen = created = 0
    counters: Dict[str, List[float]] = {"views_visible": [], "interactions_visible": []}
    for snapshot, entry in entries:
        _, metric, metadata = max(entry.observations, key=lambda obs: obs[0])
        if first_snapshots.get((entry.channel, entry.source_id)) == snapshot.completed_at:
            first_seen += 1
        placed = place_observation(entry.published_at, snapshot.completed_at)
        if placed is not None and placed[1] == "published" and period.contains(placed[0]):
            created += 1
        visible = _seen_channel_values(entry.channel, metric, metadata)
        for kind in counters:
            value = visible.get(kind.removesuffix("_visible"))
            if value is not None:
                counters[kind].append(value)
    values["first_seen"] = (first_seen / snapshots, 0)
    values["created_in_period"] = (created / snapshots, 0)
    for kind, found in counters.items():
        value = sum(found) / snapshots if found or not entries else None
        values[kind] = (value, len(entries) - len(found))
    return values
