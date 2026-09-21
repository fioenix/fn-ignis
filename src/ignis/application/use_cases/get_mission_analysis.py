import logging
from typing import Dict, Any, Optional
from uuid import UUID
from collections import defaultdict

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.research_workspace import (
    EvidenceRole,
    MissionLineage,
    ResearchSurface,
    resolve_surface,
)

logger = logging.getLogger(__name__)


class GetMissionAnalysisUseCase:
    """
    Use Case for retrieving Token-Efficient Mission Analysis data.
    Condenses datasets, extracts top signals, and strips redundant metadata to prevent LLM context bloat.
    """

    def __init__(self, repository: ITrendRepository):
        self._repo = repository

    async def execute(
        self,
        mission_id: UUID,
        limit: int = 25,
        platform_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Research Mission {mission_id} does not exist.")

        signals = await self._repo.get_mission_signals(mission_id)

        # Which question these observations were collected to answer. A Market mission's own
        # evidence is what its Brief is judged against; an Attention mission's is context for a
        # question nobody has framed yet. A mission with no recorded surface gets no label,
        # because labelling it would claim a framing it never had.
        surface = resolve_surface(mission.surface)
        evidence_role = None
        if surface is ResearchSurface.MARKET:
            evidence_role = EvidenceRole.MARKET_EVIDENCE.value
        elif surface is ResearchSurface.ATTENTION:
            evidence_role = EvidenceRole.ATTENTION_CONTEXT.value
        lineage = MissionLineage.of_mission(mission)

        # Apply optional platform filter
        if platform_filter:
            signals = [
                s for s in signals 
                if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)).lower() == platform_filter.lower()
            ]

        # Calculate platform distribution and channel breakdown
        platform_breakdown = defaultdict(int)
        channel_counts = defaultdict(int)
        total_views = 0.0

        for s in signals:
            p_val = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            platform_breakdown[p_val] += 1
            
            ch = s.metadata.get("channel_title")
            if ch:
                channel_counts[ch] += 1
            if p_val == "youtube":
                total_views += s.metric_value

        # Order signals by engagement metrics
        sorted_signals = sorted(signals, key=lambda x: (x.metric_value, x.growth_velocity), reverse=True)
        top_signals = sorted_signals[:limit]

        # Condense metadata to save tokens
        compact_signals = []
        for s in top_signals:
            p_str = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            
            clean_meta = {}
            if "channel_title" in s.metadata:
                clean_meta["channel"] = s.metadata["channel_title"]
            if "likes" in s.metadata:
                clean_meta["likes"] = s.metadata["likes"]
            if "comments" in s.metadata:
                clean_meta["comments"] = s.metadata["comments"]
            if "related_queries" in s.metadata:
                clean_meta["related_queries"] = s.metadata["related_queries"][:5]
            if "keyword" in s.metadata:
                clean_meta["keyword"] = s.metadata["keyword"]

            compact_signals.append({
                # The canonical evidence identity, so a reader can address the observation
                # rather than matching on a title or a URL.
                "observation_id": str(s.observation_id) if s.observation_id else None,
                "evidence_role": evidence_role,
                "platform": p_str,
                "title": s.raw_title,
                "metric_value": s.metric_value,
                "velocity_per_hour": s.growth_velocity,
                "url": s.source_url,
                "metadata": clean_meta,
            })

        # Top 5 most active creators
        top_channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "mission": {
                "id": str(mission.id),
                "title": mission.title,
                "keywords": mission.keywords,
                "geo": mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code),
                "timeframe": mission.timeframe,
                "status": mission.status,
                "summary": mission.summary,
                "surface": surface.value if surface else None,
                "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
                "lineage": None if lineage.is_empty else lineage.to_payload(),
            },
            "stats": {
                "total_signals_collected": len(signals),
                "platform_breakdown": dict(platform_breakdown),
                "total_youtube_views": int(total_views),
                "top_creators": [{"channel": ch, "video_count": cnt} for ch, cnt in top_channels],
                "signals_returned": len(compact_signals),
                "note": f"Displaying top {len(compact_signals)} highest engagement signals. Use generate_mission_artifact to view the complete HTML dossier."
            },
            "top_signals": compact_signals,
        }

