"""Listening periods: calendar days, weeks and months in Vietnam time (Spec 016, US2).

A period is complete once its last local day has ended. An observation belongs to the period of
its publication date when the platform reports a plausible one, and otherwise to its collection
date, flagged. A channel-day without a completed collection is missing, never zero, and a channel
is compared only while neither period misses more than a fifth of its days.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

LISTENING_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
# A platform date before this is a placeholder, not a publication (research R2).
EARLIEST_PLAUSIBLE_PUBLICATION = date(2005, 1, 1)
MAX_MISSING_SHARE = 0.2


class PeriodKind(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


def _aware(moment: datetime) -> datetime:
    """A naive timestamp would take the host's own zone and land on a host-dependent day."""
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError("Listening periods need timezone-aware timestamps.")
    return moment


def local_date(moment: datetime) -> date:
    return _aware(moment).astimezone(LISTENING_TZ).date()


@dataclass(frozen=True)
class Period:
    kind: PeriodKind
    start: date

    @property
    def last_day(self) -> date:
        if self.kind is PeriodKind.DAY:
            return self.start
        if self.kind is PeriodKind.WEEK:
            return self.start + timedelta(days=6)
        return self.start.replace(day=calendar.monthrange(self.start.year, self.start.month)[1])

    @property
    def days(self) -> List[date]:
        return [self.start + timedelta(days=i) for i in range((self.last_day - self.start).days + 1)]

    @property
    def completes_at(self) -> datetime:
        return datetime.combine(self.last_day + timedelta(days=1), time(0), tzinfo=LISTENING_TZ)

    def is_complete(self, now: datetime) -> bool:
        return _aware(now) >= self.completes_at

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.last_day

    def previous(self) -> "Period":
        return period_of(self.kind, self.start - timedelta(days=1))

    def to_payload(self) -> dict:
        return {
            "kind": self.kind.value,
            "start": self.start.isoformat(),
            "end": self.last_day.isoformat(),
            "timezone": str(LISTENING_TZ),
        }


def period_of(kind: PeriodKind, day: date) -> Period:
    kind = PeriodKind(kind)
    if kind is PeriodKind.DAY:
        return Period(kind, day)
    if kind is PeriodKind.WEEK:
        return Period(kind, day - timedelta(days=day.weekday()))
    return Period(kind, day.replace(day=1))


def latest_complete_period(kind: PeriodKind, now: datetime) -> Period:
    return period_of(kind, local_date(now)).previous()


def place_observation(
    published_at: Optional[datetime], observed_at: Optional[datetime]
) -> Optional[Tuple[date, str]]:
    """(local date, basis) for an observation, or None when it has no collection time."""
    if observed_at is None:
        return None
    _aware(observed_at)
    if (
        published_at is not None
        and _aware(published_at) <= observed_at
        and local_date(published_at) >= EARLIEST_PLAUSIBLE_PUBLICATION
    ):
        return local_date(published_at), "published"
    return local_date(observed_at), "collection_date"


def missing_days(period: Period, complete_days: Iterable[date]) -> List[date]:
    complete = set(complete_days)
    return [day for day in period.days if day not in complete]


def comparable(period: Period, missing: Sequence[date]) -> bool:
    return len(missing) <= MAX_MISSING_SHARE * len(period.days)


def counted_value(
    published_at: Optional[datetime],
    observations: Iterable[Tuple[datetime, float]],
    *,
    window_days: int,
) -> Optional[float]:
    """The value of the latest observation collected from publication to window_days after it.

    Fixing each item's exposure window keeps an earlier period's figure from growing when the item
    is collected again later. None when the item has no publication time or no such observation.
    """
    if published_at is None:
        return None
    limit = _aware(published_at) + timedelta(days=window_days)
    # An observation dated before its publication contradicts it and measures no exposure window.
    eligible = [
        (at, value) for at, value in observations if at is not None and published_at <= _aware(at) <= limit
    ]
    return max(eligible, key=lambda pair: pair[0])[1] if eligible else None
