"""T010: get_watchlist_period_snapshot over real storage (Spec 016, US2; SC-001-SC-004, SC-006).

Each day of two complete weeks is one watchlist run -- one Attention mission -- as a daily
routine would make it. Every run completes a YouTube and a TikTok collection; Reels misses the
first three days. Runs on SQLite and PostgreSQL through `repository_case`.
"""

import dataclasses
import json
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from ignis.application.ports.research_workspace_port import RunJournal
from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.domain.entities import TrendSignal
from ignis.domain.listening_period import LISTENING_TZ
from ignis.domain.research_workspace import EvidenceQualification, MissionProbeOutcome, compute_frame_fingerprint
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
from ignis.interfaces.mcp import server as mcp_server

pytestmark = pytest.mark.asyncio

AUTHORITY = {"public_http": True, "official_api": True, "browser_session": False, "paid_quota": False}
PREVIOUS = [date(2026, 9, 28) + timedelta(days=i) for i in range(7)]
CURRENT = [date(2026, 10, 5) + timedelta(days=i) for i in range(7)]
DEFINITION = {"topics": [{"name": "Matcha drinks", "categories": ["đồ uống"], "keywords": ["matcha latte"]}]}


def at(day, hour=12):
    return datetime(day.year, day.month, day.day, hour, tzinfo=LISTENING_TZ)


@pytest_asyncio.fixture
async def listening(repository_case, tmp_path, monkeypatch):
    repository = repository_case.repository
    store = WorkspaceRepository(repository=repository)
    creator = CreateResearchWorkspaceUseCase(store=store)
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = await creator.confirm(await creator.propose(root, "Listening"), confirmation=True)
    components = {"repository": repository, "workspace_store": store,
                  "create_attention_mission_use_case": CreateAttentionMissionUseCase(repository, store)}
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)
    saved = await call("handle_save_watchlist", workspace_id=str(workspace.workspace_id), name="Matcha",
                       definition=DEFINITION)
    return repository, store, workspace, saved["watchlist_id"]


async def call(handler, **kwargs):
    return json.loads(await getattr(mcp_server, handler)(**kwargs))


def signal(platform, key, title, published, observed, metric, **metadata):
    urls = {PlatformType.YOUTUBE: f"https://www.youtube.com/watch?v={key:0<11}"[:43],
            PlatformType.TIKTOK: f"https://www.tiktok.com/share/video/{key}"}
    return TrendSignal(platform=platform, raw_title=title, metric_value=float(metric), source_url=urls[platform],
                       geo_code=GeoCode.VN, captured_at=observed, published_at=published,
                       metadata={"connector_surface": platform.value, "keyword": "matcha latte", **metadata})


SURFACES = {"youtube": "youtube", "tiktok_video_grid": "tiktok", "reels": "reels"}


async def daily_run(repository, store, workspace, watchlist_id, day, signals=(), failed=()):
    """One routine firing: a run, its completed collection on `day`, and judged evidence."""
    run = await call("handle_start_watchlist_run", watchlist_id=watchlist_id,
                     allowed_resources=list(SURFACES), authority_boundary=AUTHORITY)
    mission = await repository.get_mission(run["mission_id"])
    journal = RunJournal(run_id=uuid4(), mission_id=mission.id, workspace_id=workspace.workspace_id,
                         journal_path=workspace.journal_dir / f"run-{mission.id}.json", sequence=1,
                         status="STARTED", started_at=at(day, 21))
    await store.record_run_journal(journal)
    await store.record_probe_outcomes(journal.run_id, [
        MissionProbeOutcome(run_id=journal.run_id, platform=platform, connector_surface=surface,
                            status="FAILED" if surface in failed else "EMPTY_NO_DATA", signals_collected=0,
                            queried_keywords=() if surface in failed else ("matcha latte",),
                            query_fingerprint="q" * 64, completed_at=at(day, 22),
                            scope_attestation=None if surface in failed else
                            {"geo": "VN", "timeframe": "7d", "keywords": ["matcha latte"]},
                            note="Fixture outcome.", collection_plan_digest="p" * 64)
        for surface, platform in SURFACES.items()
    ])
    await store.record_run_journal(dataclasses.replace(journal, status="COMPLETED", completed_at=at(day, 22)))
    if signals:
        for item in signals:
            item.mission_id = mission.id
        await repository.save_signals(list(signals))
        frame = compute_frame_fingerprint(mission, None)
        held = await repository.get_mission_signals(mission.id)
        await store.save_evidence_qualifications(mission.id, [
            EvidenceQualification(mission_id=mission.id, observation_id=s.observation_id, frame_fingerprint=frame,
                                  relation="CONTEXT_ONLY", purpose="CONTEXT", confidence=0.9,
                                  reason_code="DIRECT_TO_FRAME", judged_by="contract-test", model="fixture")
            for s in held if "irrelevant" not in s.raw_title
        ])
    return mission


async def two_weeks(listening, extra=None):
    repository, store, workspace, watchlist_id = listening
    plan = {
        PREVIOUS[0]: [signal(PlatformType.YOUTUBE, "yt1", "matcha latte tại nhà", at(PREVIOUS[0], 9), at(PREVIOUS[0], 21), 50),
                      signal(PlatformType.TIKTOK, "7001", "matcha latte review", at(PREVIOUS[0], 9), at(PREVIOUS[0], 21), 100,
                             metric_kind="views", likes=5, comments=1, shares=0)],
        PREVIOUS[4]: [signal(PlatformType.TIKTOK, "7001", "matcha latte review", at(PREVIOUS[0], 9), at(PREVIOUS[4], 21), 400,
                             metric_kind="views", likes=9, comments=2, shares=1)],
        # The same YouTube video seen again this week, and a new one; an irrelevant one never counts.
        CURRENT[1]: [signal(PlatformType.YOUTUBE, "yt1", "matcha latte tại nhà", at(PREVIOUS[0], 9), at(CURRENT[1], 21), 90),
                     signal(PlatformType.YOUTUBE, "yt2", "matcha latte trà sữa", at(CURRENT[1], 9), at(CURRENT[1], 21), 10),
                     signal(PlatformType.YOUTUBE, "yt3", "irrelevant matcha latte clickbait", at(CURRENT[1], 9), at(CURRENT[1], 21), 10)],
        CURRENT[2]: [signal(PlatformType.TIKTOK, "7002", "matcha latte trà sữa", at(CURRENT[2], 9), at(CURRENT[2], 21), 600,
                            metric_kind="views", likes=30, comments=3, shares=2)],
    }
    for day in PREVIOUS + CURRENT:
        failed = ("reels",) if day in PREVIOUS[:3] else ()
        await daily_run(repository, store, workspace, watchlist_id, day, plan.get(day, ()), failed)
    for day, signals in (extra or {}).items():
        await daily_run(repository, store, workspace, watchlist_id, day, signals)
    return await call("handle_get_watchlist_period_snapshot", watchlist_id=watchlist_id,
                      period_kind="week", period_start=CURRENT[0].isoformat())


def channel(snapshot, name):
    return next(c for c in snapshot["topics"][0]["channels"] if c["channel"] == name)


def indicator(cell, kind):
    return next(i for i in cell["indicators"] if i["kind"] == kind)


async def test_a_watchlist_period_compares_deduplicated_relevant_items(listening):
    snapshot = await two_weeks(listening)
    assert snapshot["status"] == "OK" and snapshot["period_kind"] == "week"
    assert snapshot["periods"]["current"]["start"] == "2026-10-05"
    youtube = channel(snapshot, "youtube")
    assert youtube["status"] == "comparable"
    # SC-001: yt1 was seen in two runs and counts once, in the week it was published.
    uploads = indicator(youtube, "new_uploads")
    assert (uploads["previous"], uploads["current"]) == (1, 1)
    tiktok = channel(snapshot, "tiktok")
    assert (indicator(tiktok, "views")["previous"], indicator(tiktok, "views")["current"]) == (400, 600)


async def test_an_incomplete_channel_is_never_compared(listening):
    snapshot = await two_weeks(listening)
    reels = channel(snapshot, "reels")
    # SC-002
    assert reels["status"] == "not_comparable"
    assert reels["missing_days"]["previous"] == [d.isoformat() for d in PREVIOUS[:3]]
    assert "indicators" not in reels


async def test_no_value_is_summed_across_channels(listening):
    snapshot = await two_weeks(listening)
    # SC-003: values live only inside a channel cell.
    topic = snapshot["topics"][0]
    assert set(topic) == {"name", "channels", "items"}
    assert all(set(i) == {"excerpt", "link", "channel", "published_on", "basis"} for i in topic["items"])


async def test_a_later_collection_leaves_the_earlier_period_unchanged(listening):
    later = {CURRENT[6]: [signal(PlatformType.TIKTOK, "7001", "matcha latte review", at(PREVIOUS[0], 9),
                                 at(CURRENT[6], 21), 50000, metric_kind="views", likes=900, comments=90, shares=9)]}
    snapshot = await two_weeks(listening, extra=later)
    # SC-004: the post published 28/09 counts its value from within 7 days, never the 11/10 one.
    tiktok = channel(snapshot, "tiktok")
    assert indicator(tiktok, "views")["previous"] == 400
    assert indicator(tiktok, "interactions")["previous"] == 12


async def test_refusals(listening):
    _, _, _, watchlist_id = listening
    open_week = await call("handle_get_watchlist_period_snapshot", watchlist_id=watchlist_id, period_kind="week",
                           period_start="2999-01-04")
    assert open_week["status"] == "REFUSED" and open_week["reason_code"] == "PERIOD_INCOMPLETE"
    assert (await call("handle_get_watchlist_period_snapshot", watchlist_id=watchlist_id,
                       period_kind="year"))["reason_code"] == "INVALID_PERIOD_KIND"
    assert (await call("handle_get_watchlist_period_snapshot", watchlist_id=str(uuid4()),
                       period_kind="week"))["status"] == "NOT_FOUND"


async def test_a_publication_time_without_an_offset_is_read_as_utc(listening):
    # The RSS connector can return a naive time; SQLite keeps it naive, PostgreSQL converts it.
    naive = datetime(CURRENT[3].year, CURRENT[3].month, CURRENT[3].day, 2)
    later = {CURRENT[3]: [signal(PlatformType.TIKTOK, "7003", "matcha latte mới", naive, at(CURRENT[3], 21), 50,
                                 metric_kind="views", likes=1, comments=0, shares=0)]}
    snapshot = await two_weeks(listening, extra=later)
    assert snapshot["status"] == "OK"
    assert indicator(channel(snapshot, "tiktok"), "views")["current"] == 600 + 50
