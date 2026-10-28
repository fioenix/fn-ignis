"""T010: a sentinel mission leaves no author identity anywhere Ignis writes or answers (SC-001, SC-007).

Fake connectors, one per registered connector and one for the host browser path, plant the
sentinel identities from T002 in every author field and link the real connectors emit. After the
mission runs, the test scans every table, every file under the research folder, the generated
report, the MCP responses and the captured logs. No undeclared sentinel may appear in any of them.

Two controls keep the scan honest: a registry-coverage test fails when a connector is added
without a fixture, and a leaking connector -- one that hides a handle under a key the policy does
not know -- must be caught by the same scan. Since T030 the scan also covers `@mention` sentinels
written inside the content.
"""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List

import psycopg
import pytest
from psycopg import sql

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.config import settings
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
from ignis.infrastructure.connectors.registry import SearchPassResult

from tests.fixtures.author_identity_sentinels import (
    HOST_BROWSER_HANDLE_URL,
    REELS_HANDLE_URL,
    SENTINEL_TIKTOK_HANDLE,
    THREADS_HANDLE_URL,
    TIKTOK_HANDLE_URL,
    YOUTUBE_VIDEO_ID,
    google_trends_metadata,
    mention_sentinels,
    reels_metadata,
    threads_metadata,
    tiktok_metadata,
    undeclared_sentinels,
    youtube_metadata,
)
from test_host_browser_mission import assignment, staged_answer

NOW = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)
CONNECTORS_DIR = Path(__file__).resolve().parents[2] / "src" / "ignis" / "infrastructure" / "connectors"


def _signal(platform: PlatformType, url: str, metadata: dict, title: str) -> TrendSignal:
    return TrendSignal(
        platform=platform,
        raw_title=title,
        metric_value=100.0,
        source_url=url,
        geo_code=GeoCode.VN,
        captured_at=NOW,
        metadata=metadata,
    )


# One fixture per connector class, in the shapes that connector emits today.
CONNECTOR_FIXTURES: Dict[str, Callable[[], TrendSignal]] = {
    "GoogleTrendsRssPlugin": lambda: _signal(
        PlatformType.GOOGLE_TRENDS,
        "https://trends.google.com/trends/explore?q=matcha&geo=VN",
        google_trends_metadata(),
        "Matcha latte",
    ),
    "TikTokCreativeCenterPlugin": lambda: _signal(
        PlatformType.TIKTOK,
        "https://www.tiktok.com/tag/aokhoac",
        {"hashtag": "#aokhoac", "rank": 1, "category": "Apparel", "source": "tiktok_creative_center"},
        "#aokhoac",
    ),
    "TikTokPlugin": lambda: _signal(
        PlatformType.TIKTOK, TIKTOK_HANDLE_URL, tiktok_metadata(), "Review áo khoác chống nắng đi xe máy"
    ),
    "ThreadsPlugin": lambda: _signal(
        PlatformType.THREADS, THREADS_HANDLE_URL, threads_metadata(), "Áo khoác nào mặc mát vậy"
    ),
    "ReelsPlugin": lambda: _signal(
        PlatformType.REELS, REELS_HANDLE_URL, reels_metadata(), "Reel phối áo khoác"
    ),
    "YouTubeDataPlugin": lambda: _signal(
        PlatformType.YOUTUBE,
        f"https://www.youtube.com/watch?v={YOUTUBE_VIDEO_ID}",
        youtube_metadata(),
        "Đánh giá áo khoác chống nắng",
    ),
}

# Modules outside the connector folders that define a connector subclass.
EXTRA_CONNECTOR_MODULES = ("ignis.infrastructure.follow_up_provider_bridge",)

# Connectors whose payload names no person at all: a trend keyword and a hashtag chart.
AUTHOR_FREE_CONNECTORS = frozenset({"GoogleTrendsRssPlugin", "TikTokCreativeCenterPlugin"})


def _registered_connector_classes() -> List[str]:
    """Every concrete connector class in the source tree, found by file rather than by package.

    Some connector folders are namespace packages, which `pkgutil.walk_packages` skips; a glob
    over the plugin files cannot miss one.
    """
    for path in sorted(CONNECTORS_DIR.rglob("*_plugin.py")):
        module = ".".join(("ignis",) + path.relative_to(CONNECTORS_DIR.parents[1]).with_suffix("").parts)
        importlib.import_module(module)
    # Connector subclasses defined outside the connector folders, so the scan does not depend on
    # which other tests happened to import them first.
    for module in EXTRA_CONNECTOR_MODULES:
        importlib.import_module(module)

    def subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from subclasses(sub)

    return sorted(
        {
            cls.__name__
            for cls in subclasses(IConnectorPlugin)
            if not inspect.isabstract(cls) and cls.__module__.startswith("ignis.")
            # A subclass emits its parent's payload unless it overrides it; the parent's fixture
            # covers it. One that changes the payload must get a fixture of its own.
            and not any(base.__name__ in CONNECTOR_FIXTURES for base in cls.__mro__[1:])
        }
    )


class _FixtureRegistry:
    """Returns the given signals as one collection pass."""

    def __init__(self, factories: Iterable[Callable[[], TrendSignal]]):
        self._factories = list(factories)

    async def search_with_outcomes(self, **_kwargs):
        return SearchPassResult(signals=[factory() for factory in self._factories])


# --- the scan -------------------------------------------------------------------------------------


def _table_texts(case) -> Dict[str, str]:
    if case.name.startswith("sqlite"):
        with sqlite3.connect(case.repository._db_path) as conn:
            names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            return {
                name: " ".join(repr(tuple(row)) for row in conn.execute(f'SELECT * FROM "{name}"'))
                for name in names
            }
    with psycopg.connect(case.dsn) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        ]
        return {
            name: " ".join(
                row[0]
                for row in conn.execute(
                    sql.SQL("SELECT t::text FROM public.{} t").format(sql.Identifier(name))
                )
            )
            for name in names
        }


def _file_texts(root: Path) -> Dict[str, str]:
    texts = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix not in (".sqlite", ".db", ".sqlite-wal", ".sqlite-shm"):
            texts[str(path.relative_to(root))] = path.read_text(encoding="utf-8", errors="replace")
    return texts


def _leaks(surfaces: Dict[str, str], sentinels: Iterable[str]) -> List[str]:
    return sorted(
        f"{where}: {sentinel}"
        for where, text in surfaces.items()
        for sentinel in sentinels
        if sentinel in text
    )


@pytest.fixture
def persistent_key(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "spec-015-conformance-encryption-key")


async def _mcp_responses(case, mission, tmp_path, monkeypatch) -> Dict[str, str]:
    """What the mission-bound tools answer, and the report they write, over this repository."""
    from ignis.interfaces.mcp import server as mcp_server

    monkeypatch.setattr(mcp_server, "create_repository", lambda *args, **kwargs: case.repository)
    components = mcp_server._init_components()

    async def _skip_lexicon_sync(_components):
        return None

    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    monkeypatch.setattr(mcp_server, "_sync_lexicons_from_db", _skip_lexicon_sync)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)
    monkeypatch.setattr(mcp_server, "_get_secure_reports_dir", lambda: reports)

    analysis = await mcp_server.handle_get_mission_analysis(str(mission.id))
    artifact = await mcp_server.handle_generate_mission_artifact(str(mission.id))
    payload = json.loads(artifact)
    report = Path(payload["artifact_file"]).read_text(encoding="utf-8")
    return {"get_mission_analysis": analysis, "generate_mission_artifact": artifact, "report_html": report}


async def _run_connector_mission(case, factories, tmp_path, monkeypatch, caplog) -> Dict[str, str]:
    caplog.set_level(logging.DEBUG)
    mission = ResearchMission(
        title="Conformance",
        keywords=["áo khoác chống nắng"],
        platforms=list(PlatformType),
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await case.repository.save_mission(mission)
    result = await ExecuteMissionUseCase(
        repository=case.repository, registry=_FixtureRegistry(factories), clusterer=SemanticClusterer()
    ).execute(mission.id)
    assert result["status"] == "COMPLETED", case.name

    surfaces = {f"table {name}": text for name, text in _table_texts(case).items()}
    surfaces.update({f"mcp {name}": text for name, text in (await _mcp_responses(case, mission, tmp_path, monkeypatch)).items()})
    surfaces.update({f"file {name}": text for name, text in _file_texts(tmp_path).items()})
    surfaces["captured logs"] = caplog.text
    surfaces["mission result"] = json.dumps(result, ensure_ascii=False, default=str)
    return surfaces


# --- coverage --------------------------------------------------------------------------------------


def test_every_registered_connector_has_a_fixture():
    missing = sorted(set(_registered_connector_classes()) - set(CONNECTOR_FIXTURES))
    assert missing == [], f"connectors without a Spec 015 conformance fixture: {missing}"


def test_every_fixture_that_can_name_a_person_plants_a_sentinel():
    for name, factory in CONNECTOR_FIXTURES.items():
        signal = factory()
        planted = [value for value in undeclared_sentinels() if value in f"{signal.source_url} {signal.metadata}"]
        if name in AUTHOR_FREE_CONNECTORS:
            assert planted == [], name
        else:
            assert planted, f"{name} fixture plants no sentinel, so its scan would pass vacuously"


# --- the mission ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_sentinel_mission_leaves_no_author_identity_anywhere(
    repository_case, tmp_path, monkeypatch, caplog, persistent_key
):
    surfaces = await _run_connector_mission(
        repository_case, CONNECTOR_FIXTURES.values(), tmp_path, monkeypatch, caplog
    )

    assert _leaks(surfaces, undeclared_sentinels() + mention_sentinels()) == [], repository_case.name
    # The content survives: the mission still holds an observation per fixture.
    assert repository_case.counts()["observations"] == len(CONNECTOR_FIXTURES), repository_case.name


@pytest.mark.asyncio
async def test_a_host_browser_submission_leaves_no_author_identity_anywhere(
    repository_case, tmp_path, monkeypatch, caplog, persistent_key
):
    caplog.set_level(logging.DEBUG)
    store, _workspace, mission, executor = await assignment(repository_case.repository, tmp_path)
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True)
        payload = staged_answer(request)
        for answer in payload["answers"]:
            for record in answer["records"]:
                record["source_url"] = HOST_BROWSER_HANDLE_URL
        service.stage(request["request_id"], payload)
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
    finally:
        service.close()

    surfaces = {f"table {name}": text for name, text in _table_texts(repository_case).items()}
    surfaces.update({f"file {name}": text for name, text in _file_texts(tmp_path).items()})
    surfaces["mcp submit_host_browser_search"] = json.dumps(receipt, ensure_ascii=False, default=str)
    surfaces["captured logs"] = caplog.text

    assert _leaks(surfaces, undeclared_sentinels() + mention_sentinels()) == [], repository_case.name
    assert repository_case.counts()["observations"] >= 1, repository_case.name


# --- the negative control (SC-007) ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_scan_catches_a_connector_that_leaks(
    repository_case, tmp_path, monkeypatch, caplog, persistent_key
):
    """A handle under a key the policy does not know gets through; the scan must say so."""

    def leaking():
        return _signal(
            PlatformType.TIKTOK,
            "https://www.tiktok.com/share/video/1",
            {"item_id": "1", "posted_by_handle": SENTINEL_TIKTOK_HANDLE},
            "Áo khoác",
        )

    surfaces = await _run_connector_mission(repository_case, [leaking], tmp_path, monkeypatch, caplog)

    leaks = _leaks(surfaces, undeclared_sentinels())
    assert f"table observations: {SENTINEL_TIKTOK_HANDLE}" in leaks, repository_case.name


@pytest.mark.asyncio
async def test_threads_host_receipt_tables_journal_logs_have_no_header_or_media_identity(
    repository_case, tmp_path, monkeypatch, caplog, persistent_key
):
    from ignis.application.use_cases import host_browser_search as module
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from tests.fixtures.author_identity_sentinels import SENTINEL_THREADS_ATTRIBUTED_NAME, SENTINEL_THREADS_HANDLE
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    store, _, mission, executor = await assignment(repository_case.repository, tmp_path, required=("threads",))
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source="threads")
        payload = host_answer(request)
        for item in payload["answers"]:
            item["records"][0]["source_url"] = f"https://www.threads.com/@{SENTINEL_THREADS_HANDLE}/post/Synthetic020Q0"
        service.stage(request["request_id"], payload)
        staged = repr(service._tickets[request["request_id"]]["receipt"])
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
        surfaces = {f"table {name}": text for name, text in _table_texts(repository_case).items()}
        surfaces.update({f"file {name}": text for name, text in _file_texts(tmp_path).items()})
        surfaces.update(receipt=json.dumps(receipt, default=str), staged=staged, logs=caplog.text)
        surfaces.update(await _mcp_responses(repository_case, mission, tmp_path, monkeypatch))
        assert _leaks(surfaces, [SENTINEL_THREADS_HANDLE, SENTINEL_THREADS_ATTRIBUTED_NAME, "synthetic.mention"]) == []
        assert repository_case.counts()["observations"] == 1
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["tiktok", "threads"])
async def test_review_host_policy_keeps_marker_and_declared_mentions_without_identity_leaks(
    repository_case, tmp_path, monkeypatch, caplog, persistent_key, source
):
    from unittest.mock import AsyncMock
    from datetime import timedelta
    from ignis.domain.author_identity import AuthorState, DeclaredAccount
    from tests.fixtures.author_identity_sentinels import SENTINEL_HOST_BROWSER_HANDLE, SENTINEL_MENTIONED_HANDLE
    from ignis.application.use_cases import host_browser_search as module
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    caplog.set_level(logging.DEBUG)
    store, _, mission, executor = await assignment(repository_case.repository, tmp_path,
        required=("threads",) if source == "threads" else ("tiktok_video",))
    declared_id = "f042bb35-cbbc-4d38-bf21-e49c0ed1a009"
    declaration = DeclaredAccount(declared_id, str(mission.id), source, SENTINEL_MENTIONED_HANDLE,
                                  "Synthetic declared account", datetime.now(timezone.utc) - timedelta(days=1))
    monkeypatch.setattr(repository_case.repository, "list_mission_declared_accounts", AsyncMock(return_value=[declaration]))
    service = HostBrowserSearchService()
    try:
        request = await service.prepare_mission(executor, mission.id, "task", "chrome", 60, True, source=source)
        payload = host_answer(request)
        for item in payload["answers"]:
            row = item["records"][0]
            row["source_url"] = (f"https://www.threads.com/@{SENTINEL_HOST_BROWSER_HANDLE}/post/Synthetic020Q0"
                                 if source == "threads" else f"https://www.tiktok.com/@{SENTINEL_HOST_BROWSER_HANDLE}/video/7417820067028536584")
            row["excerpt"] = f"Synthetic body @{SENTINEL_MENTIONED_HANDLE}"
        reply = service.stage(request["request_id"], payload)
        staged = repr(service._tickets[request["request_id"]]["receipt"])
        receipt = await service.submit_mission(executor, request["request_id"], "task", "chrome")
        signals = await repository_case.repository.get_mission_signals(mission.id)
        assert signals[0].author_assignment.state is AuthorState.KNOWN
        assert signals[0].author_assignment.marker
        assert f"@[declared:{declared_id}]" in signals[0].raw_title
        assert service._tickets[request["request_id"]].get("author_records") is None
        surfaces = {f"table {name}": text for name, text in _table_texts(repository_case).items()}
        surfaces.update({f"file {name}": text for name, text in _file_texts(tmp_path).items()})
        surfaces.update(receipt=repr(receipt), staged=staged, relay_reply=repr(reply), logs=caplog.text)
        assert _leaks(surfaces, [SENTINEL_HOST_BROWSER_HANDLE, SENTINEL_MENTIONED_HANDLE]) == []
    finally:
        service.close()
