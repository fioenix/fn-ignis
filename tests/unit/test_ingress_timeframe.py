"""The requested timeframe has to reach the connectors, and garbage must not.

trigger_ingress_refresh took no timeframe at all: fetch_from_all has the parameter, the tool
never passed it, so every requested pass searched a 24-hour window and the caller's timeframe
only narrowed the later read of stored clusters.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ignis.domain.value_objects import Timeframe
from ignis.interfaces.mcp import server as mcp_server


@pytest.fixture
def spied_components(monkeypatch):
    """A component bundle whose registry records the timeframe it was handed."""
    seen = {}

    async def _fetch_from_all(**kwargs):
        seen["timeframe"] = kwargs.get("timeframe")
        return []

    registry = MagicMock()
    registry.fetch_from_all = _fetch_from_all
    registry.last_pass_report = {}

    ingest_use_case = MagicMock()
    ingest_use_case.load_seed_keywords = AsyncMock(return_value=["ai agent"])
    cluster_use_case = MagicMock()
    cluster_use_case.execute = AsyncMock(return_value=[])

    comp = {
        "registry": registry,
        "ingest_use_case": ingest_use_case,
        "cluster_use_case": cluster_use_case,
        "repository": AsyncMock(),
    }
    monkeypatch.setattr(mcp_server, "get_components", lambda: comp)
    monkeypatch.setattr(mcp_server, "_sync_lexicons_from_db", AsyncMock())
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("asked,expected", [
    ("24h", Timeframe.LAST_24H),
    ("7d", Timeframe.LAST_7D),
    ("30d", Timeframe.LAST_30D),
    ("12m", Timeframe.LAST_12M),
])
async def test_the_requested_window_reaches_the_connectors(spied_components, asked, expected):
    result = json.loads(await mcp_server.handle_trigger_ingress_refresh(geo="VN", timeframe=asked))

    assert spied_components["timeframe"] == expected
    assert result["timeframe"] == expected.value


@pytest.mark.asyncio
@pytest.mark.parametrize("asked", [None, ""])
async def test_no_window_means_the_previous_default(spied_components, asked):
    """Passing nothing or blank keeps the old behaviour rather than silently widening the pass.

    resolve_timeframe treats a falsy value as 24h, the same way resolve_geo treats it as VN, so
    blank is a default and not a bad value.
    """
    kwargs = {} if asked is None else {"timeframe": asked}
    await mcp_server.handle_trigger_ingress_refresh(geo="VN", **kwargs)

    assert spied_components["timeframe"] == Timeframe.LAST_24H


@pytest.mark.asyncio
@pytest.mark.parametrize("asked", ["bogus", "30 days", "last week", "1y"])
async def test_an_unknown_window_is_refused_rather_than_synthesised(spied_components, asked):
    """Timeframe._missing_ builds a member from any string, so the check has to be explicit.

    Without it an unknown value arrives at the connectors as a live enum and is then mapped to
    a default interval, so the pass silently searches a window nobody asked for.
    """
    result = json.loads(await mcp_server.handle_trigger_ingress_refresh(geo="VN", timeframe=asked))

    assert result["status"] == "INVALID_TIMEFRAME"
    assert "timeframe" not in spied_components, "no pass may run on an unknown window"
