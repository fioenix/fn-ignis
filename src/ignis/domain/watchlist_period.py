"""Comparing two complete listening periods of a watchlist (Spec 016, US2).

Pure assembly: the use case loads a watchlist's runs, their observations, qualifications and probe
outcomes, and this module turns them into the period snapshot. Every channel keeps its own
indicator in its own unit (research R4, R11); nothing here adds values across channels.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ignis.domain.author_identity import scrub_handle_links
from ignis.domain.listening_period import (
    Period,
    comparable,
    counted_value,
    local_date,
    missing_days,
    place_observation,
)

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


@dataclass(frozen=True)
class TermsPolicy:
    rising_min_count: int = 2
    rising_min_growth: float = 0.5
    noise: frozenset = field(default_factory=frozenset)


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
    if present:
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


def _merge(items: Iterable[PeriodItem]) -> List[_Merged]:
    """One entry per source, so two runs that saw the same post count it once (SC-001)."""
    merged: Dict[Tuple[str, str], _Merged] = {}
    for item in items:
        key = (item.channel, item.source_id)
        entry = merged.get(key)
        if entry is None:
            entry = merged[key] = _Merged(item.source_id, item.channel, item.published_at, item.title,
                                          item.excerpt, item.link, False, set(), [])
        entry.published_at = entry.published_at or item.published_at
        entry.title, entry.excerpt = entry.title or item.title, entry.excerpt or item.excerpt
        entry.link = entry.link or item.link
        entry.relevant = entry.relevant or item.relevant
        entry.query_keywords.update(keyword.casefold() for keyword in item.query_keywords)
        entry.observations.extend(obs for obs in item.observations if obs[0] is not None)
    return [entry for entry in merged.values() if entry.observations]


def _belongs(entry: _Merged, keywords: frozenset, single_topic: bool) -> bool:
    if entry.query_keywords & keywords:
        return True
    text = f"{entry.title} {entry.excerpt}".casefold()
    if any(keyword in text for keyword in keywords):
        return True
    # A one-topic watchlist collected every item for that topic.
    return single_topic and not entry.query_keywords


def _placed(entry: _Merged) -> Tuple[date, str, datetime]:
    """(local day, basis, counting anchor). Without a plausible publication time the first
    collection anchors the counting window as well as the day."""
    first = min(observed for observed, _, _ in entry.observations)
    day, basis = place_observation(entry.published_at, first)
    return day, basis, entry.published_at if basis == "published" else first


def _change(current: Optional[float], previous: Optional[float]) -> Optional[Dict[str, Any]]:
    if current is None or previous is None:
        return None
    return {"absolute": _plain(current - previous),
            "relative": round((current - previous) / previous, 4) if previous else None}


_TOKEN = re.compile(r"\w+", re.UNICODE)


def _terms(entry: _Merged, keywords: frozenset, noise: frozenset) -> set:
    """Two-word terms: one Vietnamese syllable rarely carries the meaning a term needs."""
    text = scrub_handle_links(f"{entry.title} {entry.excerpt}").casefold()
    tokens = [t for t in _TOKEN.findall(text) if len(t) > 1 and not t.isdigit() and t not in noise]
    pairs = {f"{a} {b}" for a, b in zip(tokens, tokens[1:])}
    return {pair for pair in pairs if not any(pair in keyword for keyword in keywords)}


def _term_lists(current: Sequence[Tuple[_Merged, str]], previous: Sequence[_Merged],
                keywords: frozenset, policy: TermsPolicy) -> Tuple[List[dict], List[dict]]:
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
        row = {"term": term, "current_items": count, "previous_items": before[term], "basis": basis[term]}
        if not before[term]:
            new.append(row)
        elif (count - before[term] >= policy.rising_min_count
              and count >= before[term] * (1 + policy.rising_min_growth)):
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

    ranked = sorted(rows, key=lambda row: (-weight(row), -row[2].timestamp(), row[0].source_id))
    shown = []
    for entry, basis, _ in ranked[:MAX_ITEMS]:
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
    merged = _merge(items)
    channels = sorted({c.channel for c in coverage} | {e.channel for e in merged},
                      key=lambda c: (CHANNEL_ORDER.index(c) if c in CHANNEL_ORDER else len(CHANNEL_ORDER), c))
    single_topic = len(topics) == 1
    topic_rows = []
    for topic in topics:
        keywords = frozenset(k.casefold() for k in topic.get("keywords", ()))
        mine = [e for e in merged if e.relevant and _belongs(e, keywords, single_topic)]
        placed = [(e, *_placed(e)) for e in mine]
        topic_items: List[Tuple[_Merged, str, datetime]] = []
        cells = []
        for channel in channels:
            days = {local_date(c.completed_at) for c in coverage
                    if c.channel == channel and c.status in COMPLETING_STATUSES
                    and (not c.queried_keywords or {k.casefold() for k in c.queried_keywords} & keywords)}
            gaps = {"current": missing_days(period, days), "previous": missing_days(previous, days)}
            in_period = {
                which: [(e, basis, anchor) for e, day, basis, anchor in placed
                        if e.channel == channel and span.contains(day)]
                for which, span in (("current", period), ("previous", previous))
            }
            cell: Dict[str, Any] = {
                "channel": channel,
                "measured_on_sample": channel in SAMPLED_CHANNELS,
                "missing_days": {which: [d.isoformat() for d in gap] for which, gap in gaps.items()},
            }
            reasons = [f"{which}_period_missing_days" for which, span in (("current", period), ("previous", previous))
                       if not comparable(span, gaps[which])]
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
