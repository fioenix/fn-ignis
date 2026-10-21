"""T009 and T015 on both backends: a mission pass stores no author identity, only per-mission facts.

The pass classifies each author before stripping, so mission_evidence can still tell many voices
from one voice. Observations and sources keep the content and an identity-free link. Both the
direct writer and the journal writer take the same path.
"""

import re
import sqlite3
from datetime import datetime, timezone

import psycopg
import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.config import settings
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.exceptions import RepositoryException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.infrastructure.connectors.registry import SearchPassResult, SurfaceProbeResult
from conftest import OneSightingRegistry
from test_mission_progress_ingress import ingress_case as _shared_ingress_case
from test_mission_progress_ingress import _NoClusters, _attention

from tests.fixtures.author_identity_sentinels import (
    SENTINEL_TIKTOK_HANDLE,
    TIKTOK_HANDLE_URL,
    TIKTOK_ITEM_ID,
    tiktok_metadata,
    undeclared_sentinels,
    youtube_metadata,
)

ingress_case = _shared_ingress_case
pytestmark = pytest.mark.asyncio

MARKER = re.compile(r"^[0-9a-f]{16}$")


@pytest.fixture
def persistent_key(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "spec-015-pipeline-encryption-key")


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "")


async def _mission(repository):
    mission = ResearchMission(
        title="Author identity pipeline",
        keywords=["áo thun"],
        platforms=[PlatformType.TIKTOK],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    return mission


async def _run(case, metadata, source_url=TIKTOK_HANDLE_URL):
    mission = await _mission(case.repository)
    registry = OneSightingRegistry(
        source_url=source_url, raw_title="Áo thun form rộng mặc mát", metadata=metadata, platform=PlatformType.TIKTOK
    )
    result = await ExecuteMissionUseCase(
        repository=case.repository, registry=registry, clusterer=_NoClusters()
    ).execute(mission.id)
    assert result["status"] == "COMPLETED", case.name
    return mission


def _stored(case, mission):
    query = (
        "SELECT o.source_url, o.metadata, s.external_id, me.author_state, me.author_marker,"
        " me.declared_account_id FROM mission_evidence me JOIN observations o ON o.id = me.observation_id"
        " JOIN sources s ON s.id = o.source_id WHERE me.mission_id = {}"
    )
    if case.name.startswith("sqlite"):
        with sqlite3.connect(case.repository._db_path) as conn:
            return conn.execute(query.format("?"), (str(mission.id),)).fetchone()
    with psycopg.connect(case.dsn) as conn:
        return conn.execute(query.format("%s"), (str(mission.id),)).fetchone()


async def test_a_pass_strips_identity_and_keeps_a_per_mission_marker(repository_case, persistent_key):
    mission = await _run(repository_case, tiktok_metadata())

    source_url, metadata, external_id, state, marker, declared = _stored(repository_case, mission)

    stored = " ".join(str(value) for value in (source_url, metadata, external_id))
    leaked = [value for value in undeclared_sentinels() if value in stored]
    assert leaked == [], repository_case.name
    assert source_url == f"https://www.tiktok.com/share/video/{TIKTOK_ITEM_ID}", repository_case.name
    assert external_id == f"video:{TIKTOK_ITEM_ID}", repository_case.name
    assert state == "KNOWN" and MARKER.match(marker), repository_case.name
    assert declared is None, repository_case.name


async def test_the_same_author_gets_unrelated_markers_in_two_missions(repository_case, persistent_key):
    first = _stored(repository_case, await _run(repository_case, tiktok_metadata()))[4]
    second = _stored(repository_case, await _run(repository_case, tiktok_metadata()))[4]

    assert MARKER.match(first) and MARKER.match(second), repository_case.name
    assert first != second, repository_case.name


async def test_without_an_encryption_key_the_author_is_unavailable(repository_case, no_key):
    mission = await _run(repository_case, tiktok_metadata())

    source_url, metadata, _external_id, state, marker, _declared = _stored(repository_case, mission)

    assert state == "UNAVAILABLE" and marker is None, repository_case.name
    assert SENTINEL_TIKTOK_HANDLE not in f"{source_url} {metadata}", repository_case.name


async def test_content_with_no_author_is_unknown(repository_case, persistent_key):
    mission = await _run(
        repository_case, {"item_id": TIKTOK_ITEM_ID}, source_url=f"https://www.tiktok.com/share/video/{TIKTOK_ITEM_ID}"
    )

    assert _stored(repository_case, mission)[3:5] == ("UNKNOWN", None), repository_case.name


async def test_both_repositories_refuse_a_signal_that_skipped_the_policy(repository_case):
    signal = TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title="Áo thun",
        source_url=TIKTOK_HANDLE_URL,
        geo_code=GeoCode.VN,
        captured_at=datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc),
        metadata=tiktok_metadata(),
    )

    with pytest.raises(RepositoryException) as refused:
        await repository_case.repository.save_signals([signal])

    assert SENTINEL_TIKTOK_HANDLE not in str(refused.value), repository_case.name
    assert repository_case.counts()["observations"] == 0, repository_case.name


class _AuthoredObservationRegistry:
    """One YouTube sighting carrying its channel, through the journaled collection path."""

    async def resolve_execution_requirements(self, **_kwargs):
        return {"resources": ("youtube",), "authority": ("public_http",), "quota_costs": {}}

    async def search_with_outcomes(self, **kwargs):
        metadata = youtube_metadata()
        return SearchPassResult(
            signals=[
                TrendSignal(
                    platform=PlatformType.YOUTUBE,
                    raw_title="Bounded observation",
                    source_url=f"https://www.youtube.com/watch?v={metadata['video_id']}",
                    geo_code=GeoCode.VN,
                    captured_at=datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc),
                    metadata=metadata,
                )
            ],
            outcomes=[
                SurfaceProbeResult(
                    platform="youtube",
                    connector_surface="youtube",
                    status=ChannelHealthStatus.HEALTHY,
                    signals_collected=1,
                    queried_keywords=tuple(kwargs["keywords"]),
                    queried_window=kwargs["custom_timeframe"],
                )
            ],
        )


@pytest.mark.parametrize("ingress_case", ("sqlite-file", "postgres"), indirect=True)
async def test_the_journal_writer_records_the_same_author_facts(ingress_case, tmp_path, persistent_key):
    store, mission, _executor = await _attention(ingress_case, tmp_path)
    executor = ExecuteMissionUseCase(ingress_case.repository, _AuthoredObservationRegistry(), _NoClusters(), store)

    assert (await executor.execute(mission.id))["status"] == "COMPLETED", ingress_case.name

    _source_url, metadata, _external_id, state, marker, _declared = _stored(ingress_case, mission)
    assert state == "KNOWN" and MARKER.match(marker), ingress_case.name
    assert [value for value in undeclared_sentinels() if value in str(metadata)] == [], ingress_case.name
