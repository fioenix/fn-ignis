"""T024: many voices or one voice, per mission and channel, without saying whose (SC-002, SC-003).

Twelve TikTok sightings per pass: seven from one author, three from another and two with no
author at all. Analysis must count two voices, keep the two unknown sightings apart, give the
same authors unrelated markers in another mission, and say plainly when no key was available.
"""

import sqlite3
from datetime import datetime, timezone

import psycopg
import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.config import settings
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.connectors.registry import SearchPassResult
from test_mission_progress_ingress import _NoClusters

pytestmark = pytest.mark.asyncio

AUTHORS = ["sentinel.author.one"] * 7 + ["sentinel.author.two"] * 3 + [None, None]


class _KnownDistributionRegistry:
    async def search_with_outcomes(self, **_kwargs):
        now = datetime.now(timezone.utc)
        signals = []
        for index, author in enumerate(AUTHORS):
            item = 7500000000000000000 + index
            metadata = {"item_id": str(item)}
            if author:
                metadata["author"] = author
            signals.append(
                TrendSignal(
                    platform=PlatformType.TIKTOK, raw_title=f"Áo khoác {index}", metric_value=100.0 + index,
                    source_url=f"https://www.tiktok.com/share/video/{item}", geo_code=GeoCode.VN,
                    captured_at=now, metadata=metadata,
                )
            )
        return SearchPassResult(signals=signals)


async def _collected(repository):
    mission = ResearchMission(
        title="Concentration", keywords=["áo khoác"], platforms=[PlatformType.TIKTOK],
        geo_code=GeoCode.VN, timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    result = await ExecuteMissionUseCase(
        repository=repository, registry=_KnownDistributionRegistry(), clusterer=_NoClusters()
    ).execute(mission.id)
    assert result["status"] == "COMPLETED"
    return mission


def _markers(case, mission):
    query = "SELECT author_marker FROM mission_evidence WHERE mission_id = {} AND author_marker IS NOT NULL"
    if case.name.startswith("sqlite"):
        with sqlite3.connect(case.repository._db_path) as conn:
            return {row[0] for row in conn.execute(query.format("?"), (str(mission.id),))}
    with psycopg.connect(case.dsn) as conn:
        return {row[0] for row in conn.execute(query.format("%s"), (str(mission.id),))}


@pytest.fixture
def persistent_key(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "spec-015-concentration-encryption-key")


async def test_ten_sightings_from_two_authors_count_as_two_voices(repository_case, persistent_key):
    repository = repository_case.repository
    mission = await _collected(repository)

    analysis = await GetMissionAnalysisUseCase(repository).execute(mission.id)

    assert analysis["author_concentration"] == {
        "tiktok": {"distinct_authors": 2, "unknown": 2, "unavailable": 0, "top_share": 0.7}
    }, repository_case.name
    assert "author_concentration_limitation" not in analysis, repository_case.name
    assert "sentinel.author" not in str(analysis), repository_case.name


async def test_the_same_authors_share_no_marker_across_missions(repository_case, persistent_key):
    repository = repository_case.repository
    first = _markers(repository_case, await _collected(repository))
    second = _markers(repository_case, await _collected(repository))

    assert len(first) == len(second) == 2, repository_case.name
    assert first.isdisjoint(second), repository_case.name


async def test_without_an_encryption_key_concentration_is_unavailable_and_says_so(repository_case, monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "")
    repository = repository_case.repository
    mission = await _collected(repository)

    analysis = await GetMissionAnalysisUseCase(repository).execute(mission.id)

    assert analysis["author_concentration"] == {
        "tiktok": {"distinct_authors": 0, "unknown": 2, "unavailable": 10, "top_share": None}
    }, repository_case.name
    assert "unavailable" in analysis["author_concentration_limitation"], repository_case.name


async def test_the_quality_scorecard_measures_creator_diversity_from_markers(repository_case, persistent_key):
    """Diversity used to read channel_title, which is no longer stored; markers replace it."""
    from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator

    repository = repository_case.repository
    mission = await _collected(repository)
    signals = await repository.get_mission_signals(mission.id)

    scorecard = QualityEvaluator().evaluate_quality(signals, geo=GeoCode.VN, timeframe_days=7)

    # Two voices across ten attributed sightings.
    assert scorecard.creator_diversity_score == 20.0, repository_case.name
