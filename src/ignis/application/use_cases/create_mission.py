import logging
from typing import List, Optional

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import ResearchMission
from ignis.domain.value_objects import GeoCode, PlatformType, timeframe_to_days

logger = logging.getLogger(__name__)


class CreateMissionUseCase:
    """Use Case for creating a new targeted Research Mission with Agent and Session mapping."""

    def __init__(self, repository: ITrendRepository):
        self._repo = repository

    async def execute(
        self,
        title: str,
        keywords: List[str],
        agent: str = "claude",
        session_id: Optional[str] = None,
        platforms: Optional[List[PlatformType]] = None,
        geo: GeoCode = GeoCode.VN,
        timeframe: str = "7d",
    ) -> ResearchMission:
        # The canonical refusal, called for its exception rather than its value. Timeframe
        # ._missing_ manufactures a member for any string, so an unvalidated timeframe used to
        # reach the database intact and fail only when analysis asked it for a span -- leaving a
        # stored mission nobody could window. Validating in the use case covers every caller
        # rather than whichever handler was patched.
        timeframe_to_days(timeframe)

        mission = ResearchMission(
            title=title,
            keywords=keywords,
            agent=agent,
            session_id=session_id,
            platforms=platforms or [
                PlatformType.GOOGLE_TRENDS,
                PlatformType.YOUTUBE,
                PlatformType.TIKTOK,
                PlatformType.THREADS,
                PlatformType.REELS,
            ],
            geo_code=geo,
            timeframe=timeframe,
            status="PENDING",
        )

        mission_id = await self._repo.create_mission(mission)
        logger.info(f"Created new Research Mission: {mission_id} (Shortcode: {mission.shortcode}, Agent: {agent}, Session: {session_id})")
        return mission

