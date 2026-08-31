import logging
from typing import List, Optional
from uuid import UUID

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import ResearchMission
from ignis.domain.value_objects import GeoCode, PlatformType

logger = logging.getLogger(__name__)


class CreateMissionUseCase:
    """Use Case tạo mới một bài toán nghiên cứu xu hướng với mapping Agent & SessionID."""

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
        logger.info(f"Đã tạo Research Mission mới: {mission_id} (Shortcode: {mission.shortcode}, Agent: {agent}, Session: {session_id})")
        return mission
