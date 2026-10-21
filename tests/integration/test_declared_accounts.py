"""T021: accounts a requester declares for one mission are the only identities Ignis keeps (SC-009).

`set_mission_declared_accounts` replaces a mission's declaration set. A declared account's content
collected after the declaration is attributed to it by name; every other account keeps nothing,
and a mission without declarations keeps nothing at all. Withdrawal removes the name everywhere
without rewriting evidence.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.set_mission_declared_accounts import SetMissionDeclaredAccountsUseCase
from ignis.config import settings
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.connectors.registry import SearchPassResult

from tests.fixtures.author_identity_sentinels import (
    DECLARED_BRAND_HANDLE,
    DECLARED_BRAND_NAME,
    SENTINEL_TIKTOK_HANDLE,
    undeclared_sentinels,
)
from test_mission_progress_ingress import _NoClusters

pytestmark = pytest.mark.asyncio

UNDECLARED_BUSINESS = "sentinel.shop.official"


@pytest.fixture
def persistent_key(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "spec-015-declared-encryption-key")


class _FreshRegistry:
    """Sightings collected now, from a declared brand, an undeclared shop and an ordinary person."""

    async def search_with_outcomes(self, **_kwargs):
        now = datetime.now(timezone.utc)

        def sighting(handle, item):
            return TrendSignal(
                platform=PlatformType.TIKTOK,
                raw_title=f"Áo khoác {item}",
                metric_value=100.0,
                source_url=f"https://www.tiktok.com/@{handle}/video/{item}",
                geo_code=GeoCode.VN,
                captured_at=now,
                metadata={"item_id": str(item), "author": handle, "nickname": handle.upper()},
            )

        return SearchPassResult(
            signals=[
                sighting(DECLARED_BRAND_HANDLE, 7400000000000000001),
                sighting(UNDECLARED_BUSINESS, 7400000000000000002),
                sighting(SENTINEL_TIKTOK_HANDLE, 7400000000000000003),
            ]
        )


async def _mission(repository, title="Declared accounts"):
    mission = ResearchMission(
        title=title, keywords=["áo khoác"], platforms=[PlatformType.TIKTOK],
        geo_code=GeoCode.VN, timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    return mission


def _declare(repository, mission, accounts):
    return SetMissionDeclaredAccountsUseCase(repository).execute(str(mission.id), accounts)


async def _collect(repository, mission):
    result = await ExecuteMissionUseCase(repository=repository, registry=_FreshRegistry(), clusterer=_NoClusters()).execute(
        mission.id
    )
    assert result["status"] == "COMPLETED"


def _rows(case, query_sqlite, query_postgres, params=()):
    if case.name.startswith("sqlite"):
        with sqlite3.connect(case.repository._db_path) as conn:
            return conn.execute(query_sqlite, params).fetchall()
    with psycopg.connect(case.dsn) as conn:
        return conn.execute(query_postgres, params).fetchall()


def _evidence(case, mission):
    query = (
        "SELECT o.observed_title, e.author_state, e.declared_account_id FROM mission_evidence e"
        " JOIN observations o ON o.id = e.observation_id WHERE e.mission_id = {} ORDER BY o.observed_title"
    )
    return [tuple(row) for row in _rows(case, query.format("?"), query.format("%s"), (str(mission.id),))]


def _all_text(case) -> str:
    if case.name.startswith("sqlite"):
        with sqlite3.connect(case.repository._db_path) as conn:
            names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            return {name: " ".join(map(repr, conn.execute(f'SELECT * FROM "{name}"'))) for name in names}
    with psycopg.connect(case.dsn) as conn:
        names = [r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )]
        return {name: " ".join(r[0] for r in conn.execute(f'SELECT t::text FROM public."{name}" t')) for name in names}


async def test_a_declaration_set_is_normalised_kept_replaced_and_withdrawn(repository_case):
    repository = repository_case.repository
    mission = await _mission(repository)

    first = await _declare(repository, mission, [{"platform": "TikTok", "account": "@BrandX", "declared_name": "Brand X"}])
    second = await _declare(
        repository, mission,
        [
            {"platform": "tiktok", "account": "brandx", "declared_name": "Brand X Official"},
            {"platform": "threads", "account": "@rival", "declared_name": "Rival"},
        ],
    )
    cleared = await _declare(repository, mission, [])

    assert [(a["platform"], a["account"], a["declared_name"]) for a in first["accounts"]] == [("tiktok", "brandx", "Brand X")]
    assert first["withdrawn"] == 0 and "declared_at" in first["accounts"][0]
    kept = next(a for a in second["accounts"] if a["account"] == "brandx")
    # Restating an account keeps its declaration, so content attributed to it stays attributed.
    assert (kept["id"], kept["declared_at"]) == (first["accounts"][0]["id"], first["accounts"][0]["declared_at"])
    assert kept["declared_name"] == "Brand X Official" and second["withdrawn"] == 0
    assert cleared == {**cleared, "accounts": [], "withdrawn": 2}
    assert "not re-attributed" in cleared["applies_from"]


async def test_duplicates_blank_names_and_unknown_missions_are_refused(repository_case):
    repository = repository_case.repository
    mission = await _mission(repository)

    duplicate = await _declare(
        repository, mission,
        [{"platform": "tiktok", "account": "@a", "declared_name": "A"}, {"platform": "tiktok", "account": "A", "declared_name": "A2"}],
    )
    blank = await _declare(repository, mission, [{"platform": "tiktok", "account": "a", "declared_name": "  "}])
    unknown = await SetMissionDeclaredAccountsUseCase(repository).execute(
        "00000000-0000-0000-0000-000000000000", []
    )

    assert (duplicate["status"], duplicate["reason_code"]) == ("INVALID", "INVALID_REQUEST")
    assert (blank["status"], blank["reason_code"]) == ("INVALID", "INVALID_REQUEST")
    assert unknown["status"] == "NOT_FOUND"
    assert await repository.list_mission_declared_accounts(mission.id) == []


async def test_only_declared_accounts_keep_identity_and_only_in_their_mission(repository_case, persistent_key):
    repository = repository_case.repository
    declared_mission = await _mission(repository, "With a declaration")
    plain_mission = await _mission(repository, "Without declarations")
    await _declare(repository, declared_mission, [{"platform": "tiktok", "account": f"@{DECLARED_BRAND_HANDLE}", "declared_name": DECLARED_BRAND_NAME}])

    await _collect(repository, declared_mission)
    await _collect(repository, plain_mission)

    declared_rows = _evidence(repository_case, declared_mission)
    plain_rows = _evidence(repository_case, plain_mission)
    assert [(title, state) for title, state, _ in declared_rows] == [
        ("Áo khoác 7400000000000000001", "DECLARED"),
        ("Áo khoác 7400000000000000002", "KNOWN"),
        ("Áo khoác 7400000000000000003", "KNOWN"),
    ], repository_case.name
    assert declared_rows[0][2] is not None, repository_case.name
    assert {state for _, state, _ in plain_rows} == {"KNOWN"}, repository_case.name

    tables = _all_text(repository_case)
    leaked = sorted(f"{name}: {value}" for name, text in tables.items()
                    for value in [*undeclared_sentinels(), UNDECLARED_BUSINESS] if value in text)
    assert leaked == [], repository_case.name
    # The declared handle is kept in the declaration, and nowhere else.
    assert [name for name, text in tables.items() if DECLARED_BRAND_HANDLE in text] == ["mission_declared_accounts"]

    held = await repository.get_mission_signals(declared_mission.id)
    names = {StrategicMarketReasoner()._build_citation(signal, 1).author_or_channel for signal in held}
    assert names == {DECLARED_BRAND_NAME, None}, repository_case.name


async def test_a_declaration_does_not_reach_back_and_withdrawal_removes_the_name(repository_case, persistent_key):
    repository = repository_case.repository
    earlier = await _mission(repository, "Collected before declaring")
    await _collect(repository, earlier)
    await _declare(repository, earlier, [{"platform": "tiktok", "account": DECLARED_BRAND_HANDLE, "declared_name": DECLARED_BRAND_NAME}])
    assert "DECLARED" not in {state for _, state, _ in _evidence(repository_case, earlier)}, repository_case.name

    later = await _mission(repository, "Collected after declaring")
    await _declare(repository, later, [{"platform": "tiktok", "account": DECLARED_BRAND_HANDLE, "declared_name": DECLARED_BRAND_NAME}])
    await _collect(repository, later)
    await _declare(repository, later, [])
    await _declare(repository, earlier, [])

    rows = _evidence(repository_case, later)
    assert [state for _, state, _ in rows].count("DECLARED") == 1, repository_case.name
    assert all(declared is None for _, _, declared in rows), repository_case.name
    held = await repository.get_mission_signals(later.id)
    assert {StrategicMarketReasoner()._build_citation(s, 1).author_or_channel for s in held} == {None}
    assert DECLARED_BRAND_HANDLE not in json.dumps(_all_text(repository_case), ensure_ascii=False)


async def test_the_tool_answers_in_the_contract_shape(repository_case, monkeypatch):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    mission = await _mission(repository)
    monkeypatch.setattr(mcp_server, "get_components", lambda: {"repository": repository})

    answer = json.loads(
        await mcp_server.handle_set_mission_declared_accounts(
            str(mission.id), [{"platform": "tiktok", "account": "@brandx", "declared_name": "Brand X"}]
        )
    )

    assert set(answer) >= {"mission_id", "accounts", "withdrawn", "applies_from"}
    assert set(answer["accounts"][0]) == {"id", "platform", "account", "declared_name", "declared_at"}
    declared_at = datetime.fromisoformat(answer["accounts"][0]["declared_at"])
    assert abs(datetime.now(timezone.utc) - declared_at) < timedelta(minutes=5)
