"""Spec 020: no Chromium automation concealment in retained launch sites."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHES = {
    "infrastructure/auth/meta_browser_auth.py": {"authenticate_interactive"},
    "infrastructure/auth/tiktok_auth.py": {"authenticate_interactive"},
    "infrastructure/connectors/meta_browser_ingress.py": {"collect_json_payloads"},
    "infrastructure/connectors/tiktok/tiktok_plugin.py": {"fetch_suggestions", "fetch_video_comments", "_fetch_via_playwright"},
    "infrastructure/connectors/tiktok/creative_center_plugin.py": {"fetch_macro_trends"},
}


def test_no_automation_hiding_flags_or_webdriver_override_under_src():
    forbidden = ("AutomationControlled", "--disable-infobars", "navigator.webdriver")
    violations = []
    for path in (ROOT / "src").rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            source = path.read_text()
        except UnicodeDecodeError:
            continue  # Compiled/binary output is not a source launch configuration.
        violations.extend((str(path.relative_to(ROOT)), token) for token in forbidden if token in source)
        if path.suffix == ".py" and "ignore_default_args" in source:
            for call in ast.walk(ast.parse(source)):
                if not isinstance(call, ast.Call):
                    continue
                for keyword in call.keywords:
                    if keyword.arg == "ignore_default_args" and (
                        isinstance(keyword.value, ast.Constant) and keyword.value.value is True
                        or "--enable-automation" in ast.unparse(keyword.value)
                    ):
                        violations.append((str(path.relative_to(ROOT)), "suppressed Chromium automation defaults"))
    assert violations == [], f"Automation concealment found: {violations}"


@pytest.mark.parametrize("path,expected", LAUNCHES.items())
def test_original_eight_sites_leave_seven_retained_flag_free_launches(path, expected):
    tree = ast.parse((ROOT / "src/ignis" / path).read_text())
    found = set()
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = [call for call in ast.walk(function) if isinstance(call, ast.Call)
                     and isinstance(call.func, ast.Attribute) and call.func.attr == "launch"]
            if calls:
                found.add(function.name)
            for call in calls:
                assert all(k.arg != "ignore_default_args" for k in call.keywords)
                assert "AutomationControlled" not in ast.unparse(call)
    assert found == expected


def test_threads_suggestions_browser_launch_and_relay_projection_are_removed():
    from ignis.infrastructure.connectors import meta_browser_ingress as module
    assert not hasattr(module, "collect_threads_search_suggestions_via_browser")
    assert not hasattr(module, "THREADS_SEARCH_RELAY_EXTRACTOR")


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["meta_auth", "tiktok_auth", "meta_capture", "suggestions", "comments", "search", "creative"])
async def test_retained_sites_pass_only_original_non_hiding_launch_arguments(monkeypatch, site):
    from unittest.mock import AsyncMock, MagicMock
    from ignis.domain.value_objects import GeoCode
    from ignis.infrastructure.auth.meta_browser_auth import InstagramBrowserAuthManager
    from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager
    from ignis.infrastructure.connectors.meta_browser_ingress import collect_json_payloads
    from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
    from ignis.infrastructure.connectors.tiktok.creative_center_plugin import TikTokCreativeCenterPlugin
    import playwright.async_api
    launches = []
    async def launch(**kwargs):
        launches.append(kwargs)
        raise RuntimeError("SYNTHETIC_STOP_AT_LAUNCH")
    engine = MagicMock()
    engine.chromium.launch = AsyncMock(side_effect=launch)
    manager = MagicMock(__aenter__=AsyncMock(return_value=engine), __aexit__=AsyncMock(return_value=None))
    monkeypatch.setattr(playwright.async_api, "async_playwright", lambda: manager)
    auth = AsyncMock()
    auth.get_storage_state.return_value = {"cookies": []}
    plugin = TikTokPlugin(auth_manager=auth)
    plugin.register_ui_noise(["Synthetic UI label"])
    async def invoke():
        if site == "meta_auth":
            await InstagramBrowserAuthManager().authenticate_interactive()
        elif site == "tiktok_auth":
            await TikTokAuthManager().authenticate_interactive()
        elif site == "meta_capture":
            await collect_json_payloads("https://www.instagram.com/explore/tags/synthetic/", {}, ["/api/"])
        elif site == "suggestions":
            await plugin.fetch_suggestions(["synthetic"])
        elif site == "comments":
            await plugin.fetch_video_comments("https://www.tiktok.com/share/video/7417820067028536584")
        elif site == "search":
            await plugin._fetch_via_playwright("https://www.tiktok.com/search?q=synthetic", {}, GeoCode.VN, keyword="synthetic")
        else:
            await TikTokCreativeCenterPlugin(auth_manager=auth).fetch_macro_trends()
    try:
        await invoke()
    except Exception as exc:
        assert "SYNTHETIC_STOP_AT_LAUNCH" in str(exc)
    assert launches, "The retained production launch site was not exercised"
    assert all(call["args"] == ["--no-sandbox", "--disable-setuid-sandbox"] for call in launches)
    assert all(set(call) == {"headless", "args"} for call in launches)
