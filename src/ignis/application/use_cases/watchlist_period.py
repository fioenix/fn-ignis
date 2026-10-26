"""The watchlist-period snapshot: one complete period against the one before it (Spec 016, US2).

A read only: it loads the watchlist's runs -- each an Attention mission -- with their observations,
current qualifications and the probe outcomes of their latest completed collection, and hands them
to the pure comparison in `ignis.domain.watchlist_period`. It starts no collection and writes
nothing.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.application.use_cases.recorded_content import recorded_excerpt
from ignis.application.use_cases.watchlists import _refused, _uuid
from ignis.domain.listening_period import PeriodKind, latest_complete_period, local_date, period_of
from ignis.domain.research_workspace import QualificationRelation, compute_frame_fingerprint
from ignis.domain.source_identity import identity_free_source_url
from ignis.domain.watchlist import plan_in_effect
from ignis.domain.watchlist_period import (
    COMPLETING_STATUSES, PeriodCoverage, PeriodItem, SeenSnapshot, TermsPolicy, compare_periods,
    compare_seen_periods, period_listening_plans,
)
from ignis.infrastructure.security.pii_sanitizer import render_mention_tokens, sanitize_pii_text

# R4: what counts toward a volume indicator. Unassessed and irrelevant observations do not.
RELEVANT_RELATIONS = frozenset({QualificationRelation.QUALIFIED_SUPPORT, QualificationRelation.CONTEXT_ONLY})
# Where connectors record the keyword whose query returned an item.
QUERY_KEYWORD_FIELDS = ("keyword", "matched_keyword")
# runtime_configs keys (data-model.md), with the defaults the spec chose when a key is absent.
RISING_MIN_COUNT = ("listening.terms.rising_min_count", 2)
RISING_MIN_GROWTH = ("listening.terms.rising_min_growth", 0.5)
COUNTER_DAYS = ("listening.counter_observation_days", 7)
MAX_COUNTER_DAYS = 31
NOISE_DOMAINS = ("noise_blacklist", "foreign_stopwords")


def _query_keywords(metadata: Dict[str, Any]) -> tuple:
    found = [metadata.get(name) for name in QUERY_KEYWORD_FIELDS]
    many = metadata.get("matched_keywords")
    if isinstance(many, (list, tuple)):
        found.extend(many)
    return tuple(k for k in found if isinstance(k, str) and k.strip())


def _utc(moment: Optional[datetime]) -> Optional[datetime]:
    """A stored time without an offset is UTC: SQLite keeps one that PostgreSQL would convert."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=timezone.utc)


def _platform(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


class GetWatchlistPeriodSnapshotUseCase:
    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._repo = repository
        self._store = store
        self._clock = clock

    async def execute(self, watchlist_id: Any, period_kind: Any = None, period_start: Any = None) -> Dict[str, Any]:
        target = _uuid(watchlist_id)
        if target is None:
            return _refused("INVALID", "INVALID_REQUEST", "watchlist_id must be a UUID.")
        now = self._clock()
        plans = await self._repo.list_listening_plans(target)
        if period_kind is None:
            current_plan = plan_in_effect(plans, now)
            if current_plan is None:
                return _refused("INVALID", "PERIOD_KIND_REQUIRED",
                                "State period_kind or record a listening plan first.")
            period_kind = current_plan.period_kind
        try:
            kind = PeriodKind(str(period_kind).strip().lower())
        except ValueError:
            return _refused("INVALID", "INVALID_PERIOD_KIND", "period_kind is day, week or month.")
        if period_start is None:
            period = latest_complete_period(kind, now)
        else:
            try:
                period = period_of(kind, date.fromisoformat(str(period_start)))
                period.previous()  # Year 1 has no period before it.
            except (ValueError, OverflowError):
                return _refused("INVALID", "INVALID_PERIOD_START", "period_start is a date, YYYY-MM-DD.")
        watchlist = await self._repo.get_watchlist(target)
        if watchlist is None:
            return _refused("NOT_FOUND", "NOT_FOUND", "No watchlist has this id.", watchlist_id=str(target))
        base = {"watchlist_id": str(watchlist.id), "name": watchlist.name, "period_kind": kind.value}
        # Bounded so a misconfigured value cannot overflow the date arithmetic.
        window_days = min(MAX_COUNTER_DAYS, max(1, int(await self._config(*COUNTER_DAYS))))
        topics = [topic.to_payload() for topic in watchlist.current.definition.topics]
        policy = TermsPolicy()
        if not period.is_complete(now):
            # Refuse before reading a single run.
            return {**base, **compare_periods(topics=topics, items=(), coverage=(), period=period, now=now,
                                              policy=policy, versions={})}
        # A collection before the earlier period cannot hold its posts; one after the counting
        # window of the later period cannot change a counted value or a covered day.
        first_day = period.previous().start
        last_day = period.last_day + timedelta(days=window_days)

        items: List[PeriodItem] = []
        coverage: List[PeriodCoverage] = []
        seen_snapshots: List[SeenSnapshot] = []
        versions: Dict[date, set] = {period.start: set(), period.previous().start: set()}
        # The first sighting of each source in any run up to the later period's counting window:
        # an item without a publication time takes its period from it.
        first_seen: Dict[str, datetime] = {}
        first_snapshots: Dict[tuple, datetime] = {}
        for run in watchlist.runs:
            # A run's day is the day its collection completed; a run that never completed one
            # covers no day and holds no counted evidence.
            outcomes = await self._store.get_latest_completed_probe_outcomes(run.mission_id)
            if not outcomes:
                continue
            # Seen first-sighting history is channel-scoped and independent of the created
            # view's run-wide window. Read it before applying any created-view date filter.
            signals = await self._repo.get_mission_signals(run.mission_id)
            _note_snapshot_sightings(first_snapshots, signals, outcomes)
            collected = local_date(max(_utc(o.completed_at) for o in outcomes))
            # Keep created-view run eligibility unchanged. The seen axis reads each channel's
            # own completion time, even when another channel completes after the window.
            include_created = first_day <= collected <= last_day
            if collected > last_day and not any(
                    first_day <= local_date(_utc(o.completed_at)) <= period.last_day for o in outcomes):
                continue
            if collected < first_day:
                for signal in signals:
                    _note_sighting(first_seen, signal)
                continue
            for span in (period, period.previous()):
                if span.contains(collected):
                    versions[span.start].add(run.version)
            mission = await self._repo.get_mission(run.mission_id)
            if mission is None:
                continue
            frame = compute_frame_fingerprint(mission, None)
            judgments = [q for q in await self._store.list_evidence_qualifications(mission.id)
                         if q.frame_fingerprint == frame]
            relevant = {q.observation_id for q in judgments if q.relation in RELEVANT_RELATIONS}
            assessed = {q.observation_id for q in judgments if q.relation != QualificationRelation.UNASSESSED}
            # A channel holding any unjudged observation cannot stand as measured for its day.
            unjudged = {_platform(s.platform) for s in signals if s.observation_id not in assessed}
            names = {a.id: a.declared_name for a in await self._repo.list_mission_declared_accounts(mission.id)}
            run_coverage = [
                PeriodCoverage(channel=o.platform, status=_platform(o.status),
                               queried_keywords=tuple(o.queried_keywords), completed_at=_utc(o.completed_at),
                               judged=_platform(o.platform) not in unjudged)
                for o in outcomes
            ]
            if include_created:
                coverage.extend(run_coverage)
            run_items: List[PeriodItem] = []
            for signal in signals:
                if signal.source_id is None:
                    continue
                if include_created:
                    _note_sighting(first_seen, signal)
                metadata = dict(signal.metadata or {})
                channel = _platform(signal.platform)
                excerpt = recorded_excerpt(metadata)
                run_items.append(PeriodItem(
                    source_id=str(signal.source_id),
                    channel=channel,
                    published_at=_utc(signal.published_at),
                    # Mentions render as Spec 015 renders them everywhere else.
                    title=render_mention_tokens(signal.raw_title or "", names),
                    excerpt=sanitize_pii_text(render_mention_tokens(str(excerpt), names)) if excerpt else "",
                    link=identity_free_source_url(channel, signal.source_url, metadata),
                    relevant=signal.observation_id in relevant,
                    query_keywords=_query_keywords(metadata),
                    observations=((_utc(signal.captured_at), signal.metric_value, metadata),),
                ))
            if include_created:
                items.extend(run_items)
            seen_snapshots.extend(SeenSnapshot(
                c.channel, c.status, c.queried_keywords, c.completed_at, c.judged,
                tuple(item for item in run_items if item.channel == c.channel),
            ) for c in run_coverage)

        items = [dataclasses.replace(item, first_seen=first_seen.get(item.source_id)) for item in items]
        policy = await self._policy()
        snapshot = compare_periods(
            topics=topics,
            items=items,
            coverage=coverage,
            period=period,
            now=now,
            policy=policy,
            versions={start: sorted(found) for start, found in versions.items()},
            window_days=window_days,
        )
        seen = compare_seen_periods(topics=topics, snapshots=seen_snapshots, plans=plans, period=period,
                                    policy=policy, first_snapshots=first_snapshots)
        for topic, cells in zip(snapshot["topics"], seen):
            topic["seen"] = cells
        snapshot["listening_plan"] = {which: plan.to_payload() if plan else None
                                      for which, plan in period_listening_plans(plans, period).items()}
        return {**base, **snapshot}

    async def _config(self, key: str, default: float) -> float:
        try:
            raw = await self._repo.get_runtime_config(key)
            if raw in (None, ""):
                return default
            value = float(raw)
            return type(default)(value) if math.isfinite(value) and value >= 0 else default
        except (ValueError, TypeError, OverflowError, NotImplementedError):
            return default

    async def _policy(self) -> TermsPolicy:
        # The noise vocabulary lives in market_lexicons, never in code.
        noise: set = set()
        for domain in NOISE_DOMAINS:
            try:
                rows = await self._repo.get_domain_lexicons(domain) or []
            except NotImplementedError:
                rows = []
            noise.update(str(row.get("term") or "").strip().casefold() for row in rows)
        noise.discard("")
        return TermsPolicy(rising_min_count=int(await self._config(*RISING_MIN_COUNT)),
                           rising_min_growth=float(await self._config(*RISING_MIN_GROWTH)),
                           noise=frozenset(noise))


def _note_sighting(first_seen: Dict[str, datetime], signal: Any) -> None:
    if signal.source_id is None or signal.captured_at is None:
        return
    key, seen = str(signal.source_id), _utc(signal.captured_at)
    if key not in first_seen or seen < first_seen[key]:
        first_seen[key] = seen


def _note_snapshot_sightings(first: Dict[tuple, datetime], signals: list, outcomes: list) -> None:
    """First successful snapshot per channel/source, independent of capture or judgment order."""
    completed = {_platform(o.platform): _utc(o.completed_at) for o in outcomes
                 if _platform(o.status) in COMPLETING_STATUSES}
    for signal in signals:
        at = completed.get(_platform(signal.platform))
        if signal.source_id is not None and at is not None:
            key = (_platform(signal.platform), str(signal.source_id))
            first[key] = min(first.get(key, at), at)
