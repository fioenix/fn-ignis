import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from ignis.domain.token_rotation import (
    STATUS_EXPIRED,
    STATUS_EXPIRING_SOON,
    STATUS_OK,
    STATUS_UNKNOWN,
    build_expiry_alerts,
    plan_staggered_refresh,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _cred(platform, days=None):
    return {
        "platform": platform,
        "auth_type": "browser_session",
        "expires_at": (NOW + timedelta(days=days)).isoformat() if days is not None else None,
    }


def test_bug11_flags_tier1_tokens_expiring_within_seven_days():
    plan = plan_staggered_refresh([_cred("threads", 3), _cred("instagram", 30), _cred("tiktok", -1)], now=NOW)
    by_platform = {e["platform"]: e for e in plan}
    assert by_platform["threads"]["status"] == STATUS_EXPIRING_SOON
    assert by_platform["threads"]["days_remaining"] == 3
    assert by_platform["instagram"]["status"] == STATUS_OK
    assert by_platform["tiktok"]["status"] == STATUS_EXPIRED


def test_bug11_missing_expiry_is_reported_not_silently_ok():
    plan = plan_staggered_refresh([_cred("threads")], now=NOW)
    assert plan[0]["status"] == STATUS_UNKNOWN
    assert plan[0]["recommended_refresh_at"] is None


def test_bug11_refresh_slots_are_staggered_at_least_one_day_apart():
    """Threads va Instagram het han cung ngay khong duoc refresh cung mot luc."""
    plan = plan_staggered_refresh([_cred("threads", 20), _cred("instagram", 20)], now=NOW)
    slots = sorted(datetime.fromisoformat(e["recommended_refresh_at"]) for e in plan)
    assert (slots[1] - slots[0]) >= timedelta(hours=24)
    assert all(not e["stagger_conflict"] for e in plan)


def test_bug11_stagger_never_plans_a_refresh_after_expiry():
    plan = plan_staggered_refresh([_cred("threads", 2), _cred("instagram", 2), _cred("tiktok", 2)], now=NOW)
    for entry in plan:
        slot = datetime.fromisoformat(entry["recommended_refresh_at"])
        assert slot <= datetime.fromisoformat(entry["expires_at"])


def test_bug11_alerts_generated_for_expiring_and_expired_credentials():
    plan = plan_staggered_refresh([_cred("threads", 3), _cred("instagram", 40), _cred("tiktok", -2)], now=NOW)
    alerts = build_expiry_alerts(plan, now=NOW)
    types = {(a["type"], a["component"]) for a in alerts}
    assert ("TOKEN_EXPIRING_SOON", "threads") in types
    assert ("TOKEN_EXPIRED", "tiktok") in types
    assert not any(a["component"] == "instagram" for a in alerts)


@pytest.mark.asyncio
async def test_bug11_auth_status_tool_exposes_refresh_plan():
    from ignis.interfaces.mcp import server as srv

    repo = AsyncMock()
    repo.list_platform_credentials.return_value = [_cred("threads", 2), _cred("instagram", 2)]
    with patch.object(srv, "get_components", return_value={"repository": repo}):
        payload = json.loads(await srv.handle_get_platform_auth_status())

    assert payload["status"] == "SUCCESS"
    assert len(payload["expiry_warnings"]) == 2
    assert all(e["recommended_refresh_at"] for e in payload["refresh_plan"])
