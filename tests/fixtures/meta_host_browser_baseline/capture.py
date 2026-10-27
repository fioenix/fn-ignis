"""Capture/check synthetic Spec 020 pre-change outputs without sockets or credentials.

Run from the checkout: PYTHONPATH=src <venv-python> <this-file> [--check].
Only transport, random IDs and the clock are replaced. Validation/comparison and
public schema enumeration use checkout production modules. No caller store opens.
"""
import asyncio
import itertools
import json
import os
import runpy
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from pydantic_settings.sources import DotEnvSettingsSource, SecretsSettingsSource

# Prevent import-time configuration from opening environment or credential files.
ENV_GUARD = patch.object(DotEnvSettingsSource, "_read_env_files", return_value={})
SECRET_GUARD = patch.object(SecretsSettingsSource, "__call__", return_value={})
ENV_GUARD.start()
SECRET_GUARD.start()
os.environ.update(DATABASE_URL="sqlite:///:memory:", IGNIS_ENV_ISOLATED="0",
                  IGNIS_ENV_FILE="", YOUTUBE_API_KEY="", IGNIS_ENCRYPTION_KEY="",
                  THREADS_APP_SECRET="", INSTAGRAM_APP_SECRET="")

from ignis.application.use_cases import host_browser_search as host
from ignis.domain import watchlist_period as periods
from ignis.domain.listening_period import LISTENING_TZ, PeriodKind, period_of
from ignis.domain.watchlist import ListeningPlan
from ignis.interfaces.mcp import server

DIRECTORY = Path(__file__).resolve().parent
CLOCK = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return CLOCK if tz else CLOCK.replace(tzinfo=None)


class MockRelay:
    """No listener, browser or transport claim; descriptor placeholders are explicit."""
    url = "http://127.0.0.1:0/SYNTHETIC-RELAY"
    tab_script = "[mock relay; transport script excluded from baseline]"

    def __init__(self, *args):
        pass

    def close(self):
        pass


async def outputs():
    unit = runpy.run_path("tests/unit/test_host_browser_search.py")
    identifiers = itertools.count(1)
    with patch.object(host, "LoopbackRelay", MockRelay), patch.object(host, "datetime", Clock), \
            patch.object(host, "uuid4", lambda: UUID(int=next(identifiers))):
        service = host.HostBrowserSearchService()
        try:
            request = unit["prepare"](service)
            payload = unit["answer"](request)
            payload["answers"][0]["captured_at"] = CLOCK.isoformat()
            service.stage(request["request_id"], payload)
            receipt = service.submit(request["request_id"], "task-1", "chrome-1")
            assert receipt == service.submit(request["request_id"], "task-1", "chrome-1")
            assert "@fixture" not in json.dumps(receipt)
        finally:
            service.close()
    result = {"tiktok-prepare.json": request, "tiktok-receipt.json": receipt}
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert len(tools) == 53
    result["submit-cancel-schemas.json"] = {
        name: tools[name].parameters for name in
        ("submit_host_browser_search", "cancel_host_browser_search")}
    created = runpy.run_path("tests/unit/test_watchlist_period.py")
    seen = runpy.run_path("tests/unit/test_watchlist_seen_axis.py")
    for kind in (PeriodKind.DAY, PeriodKind.WEEK, PeriodKind.MONTH):
        period = period_of(kind, date(2026, 10, 19))
        previous = period.previous()
        rows, snapshots = [], []
        for side, day in (("previous", previous.start), ("current", period.start)):
            for channel in ("youtube", "tiktok"):
                metadata = {"metric_kind": "views", "metric_known": True,
                            "views": 100, "likes": 5, "comments": 2, "shares": 1,
                            "collection_path": "host_browser:tiktok-public-grid-v1" if channel == "tiktok"
                            else "official_api:youtube"}
                row = created["item"](f"{channel}:{side}", channel, created["at"](day),
                                      [(created["at"](day, 21), 100, metadata)])
                rows.append(row)
                snapshots.append(periods.SeenSnapshot(channel, "HEALTHY", ("matcha latte",),
                                                       created["at"](day, 22), True, (row,)))
        coverage = [c for channel in ("youtube", "tiktok") for c in
                    created["coverage"](channel, previous.days + period.days)]
        created_output = periods.compare_periods(
            topics=[created["TOPIC"]], items=rows, coverage=coverage, period=period,
            now=datetime(2026, 11, 2, tzinfo=LISTENING_TZ), policy=created["POLICY"], versions={period.start: [1], previous.start: [1]})
        seen_output = periods.compare_seen_periods(
            topics=[seen["TOPIC"]], snapshots=snapshots,
            plans=[ListeningPlan(created["at"](previous.start, 0), "Track drinks.", kind.value, 1)],
            period=period, policy=periods.TermsPolicy())
        assert created_output["status"] == "OK"
        assert all(c["status"] == "comparable" for c in created_output["topics"][0]["channels"])
        assert all(c["status"] == "comparable" for c in seen_output[0])
        result[f"{kind.value}-created.json"] = created_output
        result[f"{kind.value}-seen.json"] = seen_output
    return result


async def main():
    check = "--check" in sys.argv
    for name, value in (await outputs()).items():
        encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path = DIRECTORY / name
        if check:
            assert path.read_text() == encoded, f"Baseline drift: {name}"
        else:
            path.write_text(encoded)
        print(f"{'MATCH' if check else 'CAPTURED'} {name}")
    print("9 synthetic JSON baselines; real validator/comparators/schemas; mock relay only")


if __name__ == "__main__":
    asyncio.run(main())
