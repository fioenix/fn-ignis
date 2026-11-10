"""Install pre-retirement Market evidence fixtures without using new-mission admission."""

from dataclasses import replace
from uuid import uuid4

from ignis.application.use_cases.create_attention_mission import _platforms_from_resources
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import MarketBriefRevision
from ignis.domain.value_objects import GeoCode


async def store_historical_market(store, *, workspace_id, confirmed_by, keywords, manifest, **brief):
    mission_id = uuid4()
    revision = MarketBriefRevision(
        brief_revision_id=uuid4(), workspace_id=workspace_id, mission_id=mission_id,
        revision_number=1, confirmed_by=confirmed_by, **brief,
    )
    manifest = replace(manifest, mission_id=mission_id)
    mission = ResearchMission(
        id=mission_id, title=brief['decision'], keywords=list(keywords), workspace_id=workspace_id,
        surface='MARKET', status='PENDING', geo_code=GeoCode(brief['geo']), timeframe=brief['timeframe'],
        platforms=_platforms_from_resources(manifest.allowed_resources),
        brief_revision_id=revision.brief_revision_id,
    )
    mission, revision, _ = await store.create_market_mission_with_brief_and_manifest(mission, revision, manifest)
    return mission, revision
