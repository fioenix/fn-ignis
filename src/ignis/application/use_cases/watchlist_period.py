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
from ignis.domain.watchlist_period import PeriodCoverage, PeriodItem, TermsPolicy, compare_periods
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

    async def execute(self, watchlist_id: Any, period_kind: Any, period_start: Any = None) -> Dict[str, Any]:
        target = _uuid(watchlist_id)
        if target is None:
            return _refused("INVALID", "INVALID_REQUEST", "watchlist_id must be a UUID.")
        try:
            kind = PeriodKind(str(period_kind).strip().lower())
        except ValueError:
            return _refused("INVALID", "INVALID_PERIOD_KIND", "period_kind is day, week or month.")
        now = self._clock()
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
        versions: Dict[date, set] = {period.start: set(), period.previous().start: set()}
        # The first sighting of each source in any run up to the later period's counting window:
        # an item without a publication time takes its period from it.
        first_seen: Dict[str, datetime] = {}
        for run in watchlist.runs:
            # A run's day is the day its collection completed; a run that never completed one
            # covers no day and holds no counted evidence.
            outcomes = await self._store.get_latest_completed_probe_outcomes(run.mission_id)
            if not outcomes:
                continue
            collected = local_date(max(_utc(o.completed_at) for o in outcomes))
            if collected > last_day:
                continue
            if collected < first_day:
                for signal in await self._repo.get_mission_signals(run.mission_id):
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
            signals = await self._repo.get_mission_signals(mission.id)
            # A channel holding any unjudged observation cannot stand as measured for its day.
            unjudged = {_platform(s.platform) for s in signals if s.observation_id not in assessed}
            names = {a.id: a.declared_name for a in await self._repo.list_mission_declared_accounts(mission.id)}
            coverage.extend(
                PeriodCoverage(channel=o.platform, status=_platform(o.status),
                               queried_keywords=tuple(o.queried_keywords), completed_at=_utc(o.completed_at),
                               judged=_platform(o.platform) not in unjudged)
                for o in outcomes
            )
            for signal in signals:
                if signal.source_id is None:
                    continue
                _note_sighting(first_seen, signal)
                metadata = dict(signal.metadata or {})
                channel = _platform(signal.platform)
                excerpt = recorded_excerpt(metadata)
                items.append(PeriodItem(
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

        items = [dataclasses.replace(item, first_seen=first_seen.get(item.source_id)) for item in items]
        snapshot = compare_periods(
            topics=topics,
            items=items,
            coverage=coverage,
            period=period,
            now=now,
            policy=await self._policy(),
            versions={start: sorted(found) for start, found in versions.items()},
            window_days=window_days,
        )
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
