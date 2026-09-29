from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo


PACIFIC_TIME = ZoneInfo("America/Los_Angeles")


class YouTubeQuotaBucket(str, Enum):
    SEARCH_LIST = "search_list"
    DEFAULT_UNITS = "default_units"


@dataclass(frozen=True)
class YouTubeQuotaPolicy:
    search_daily_limit: int = 100
    scheduled_search_daily_limit: int = 70
    other_daily_unit_limit: int = 10_000

    def __post_init__(self) -> None:
        if self.search_daily_limit < 1 or self.other_daily_unit_limit < 1:
            raise ValueError("YouTube daily quota limits must be positive.")
        if not 0 <= self.scheduled_search_daily_limit <= self.search_daily_limit:
            raise ValueError(
                "Scheduled YouTube search limit must be between zero and the total search limit."
            )

    def daily_limit(self, bucket: YouTubeQuotaBucket) -> int:
        if bucket == YouTubeQuotaBucket.SEARCH_LIST:
            return self.search_daily_limit
        return self.other_daily_unit_limit

    def scheduled_limit(self, bucket: YouTubeQuotaBucket) -> Optional[int]:
        if bucket == YouTubeQuotaBucket.SEARCH_LIST:
            return self.scheduled_search_daily_limit
        return None


@dataclass(frozen=True)
class YouTubeQuotaWindow:
    quota_day: date
    reset_at: datetime


@dataclass(frozen=True)
class YouTubeQuotaUsage:
    quota_day: date
    bucket: YouTubeQuotaBucket
    used: int
    scheduled_used: int
    exhausted: bool
    updated_at: datetime


@dataclass(frozen=True)
class YouTubeQuotaReservation:
    admitted: bool
    usage: YouTubeQuotaUsage


@dataclass(frozen=True)
class YouTubeQuotaSnapshot:
    quota_day: date
    bucket: YouTubeQuotaBucket
    used: int
    scheduled_used: int
    limit: int
    scheduled_limit: Optional[int]
    exhausted: bool
    reset_at: datetime


def quota_window(now: datetime) -> YouTubeQuotaWindow:
    if now.tzinfo is None:
        raise ValueError("Quota clocks must be timezone-aware.")
    local_now = now.astimezone(PACIFIC_TIME)
    next_day = local_now.date() + timedelta(days=1)
    next_midnight = datetime.combine(next_day, time.min, tzinfo=PACIFIC_TIME)
    return YouTubeQuotaWindow(
        quota_day=local_now.date(),
        reset_at=next_midnight.astimezone(timezone.utc),
    )
