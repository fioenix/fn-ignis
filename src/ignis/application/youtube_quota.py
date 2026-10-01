from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.exceptions import ConnectorQuotaExceededException
from ignis.domain.value_objects import IngressTrigger
from ignis.domain.youtube_quota import (
    YouTubeQuotaBucket,
    YouTubeQuotaPolicy,
    YouTubeQuotaSnapshot,
    YouTubeQuotaUsage,
    quota_window,
)


class YouTubeQuotaManager:
    """Admit requested YouTube calls against the shared persisted quota ledger."""

    def __init__(
        self,
        repository: ITrendRepository,
        policy: YouTubeQuotaPolicy,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _snapshot(self, usage: YouTubeQuotaUsage, reset_at: datetime) -> YouTubeQuotaSnapshot:
        return YouTubeQuotaSnapshot(
            quota_day=usage.quota_day,
            bucket=usage.bucket,
            used=usage.used,
            scheduled_used=usage.scheduled_used,
            limit=self._policy.daily_limit(usage.bucket),
            exhausted=usage.exhausted,
            reset_at=reset_at,
        )

    async def reserve(
        self,
        bucket: YouTubeQuotaBucket,
        trigger: IngressTrigger = IngressTrigger.REQUESTED,
        cost: int = 1,
    ) -> YouTubeQuotaSnapshot:
        if cost < 1:
            raise ValueError("YouTube quota reservation cost must be positive.")
        if trigger != IngressTrigger.REQUESTED:
            raise ValueError("YouTube quota can only be reserved for requested work.")
        now = self._now()
        window = quota_window(now)
        result = await self._repository.reserve_youtube_quota(
            quota_day=window.quota_day,
            bucket=bucket,
            cost=cost,
            trigger=trigger,
            daily_limit=self._policy.daily_limit(bucket),
            now=now,
        )
        snapshot = self._snapshot(result.usage, window.reset_at)
        if not result.admitted:
            raise ConnectorQuotaExceededException(
                bucket=bucket.value,
                used=snapshot.used,
                limit=snapshot.limit,
                reset_at=snapshot.reset_at,
                exhausted=snapshot.exhausted,
            )
        return snapshot

    async def mark_exhausted(
        self, bucket: YouTubeQuotaBucket
    ) -> YouTubeQuotaSnapshot:
        now = self._now()
        window = quota_window(now)
        usage = await self._repository.mark_youtube_quota_exhausted(
            quota_day=window.quota_day,
            bucket=bucket,
            now=now,
        )
        return self._snapshot(usage, window.reset_at)

    async def status(self) -> Dict[str, object]:
        now = self._now()
        window = quota_window(now)
        rows = {
            row.bucket: row
            for row in await self._repository.get_youtube_quota_usage(window.quota_day)
        }
        buckets: Dict[str, Dict[str, object]] = {}
        for bucket in YouTubeQuotaBucket:
            usage = rows.get(
                bucket,
                YouTubeQuotaUsage(
                    quota_day=window.quota_day,
                    bucket=bucket,
                    used=0,
                    scheduled_used=0,
                    exhausted=False,
                    updated_at=now,
                ),
            )
            snapshot = self._snapshot(usage, window.reset_at)
            buckets[bucket.value] = {
                "used": snapshot.used,
                "scheduled_used": snapshot.scheduled_used,
                "limit": snapshot.limit,
                "exhausted": snapshot.exhausted,
            }
        return {
            "quota_day": window.quota_day.isoformat(),
            "next_reset_at": window.reset_at.isoformat(),
            "buckets": buckets,
        }
