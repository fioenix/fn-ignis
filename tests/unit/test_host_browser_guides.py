"""Spec 025 Story 1: the host-browser guides ship in the package and reach every MCP host."""

import asyncio
from importlib import resources
from pathlib import Path

import pytest
from fastmcp import Client

from ignis.interfaces.mcp.server import mcp

GUIDES = {
    "ignis_browser_relay": "fn-ignis://guide/ignis-browser-relay",
    "ignis_tiktok_browser": "fn-ignis://guide/ignis-tiktok-browser",
    "ignis_threads_browser": "fn-ignis://guide/ignis-threads-browser",
    "ignis_instagram_browser": "fn-ignis://guide/ignis-instagram-browser",
}
REPO = Path(__file__).resolve().parents[2]


def _packaged(name: str) -> str:
    return resources.files("ignis.interfaces.mcp").joinpath(f"guides/{name}.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(GUIDES))
def test_each_guide_is_packaged_in_the_library(name):
    assert _packaged(name).startswith("# ")


async def _served():
    async with Client(mcp) as client:
        prompts = {p.name for p in await client.list_prompts()}
        uris = {str(r.uri) for r in await client.list_resources()}
        texts = {}
        for name, uri in GUIDES.items():
            if name in prompts and uri in uris:
                prompt = await client.get_prompt(name)
                resource = await client.read_resource(uri)
                texts[name] = ([m.content.text for m in prompt.messages], [c.text for c in resource])
        return prompts, uris, texts


def test_each_guide_is_a_prompt_and_a_resource_returning_the_packaged_text():
    prompts, uris, texts = asyncio.run(_served())
    for name, uri in GUIDES.items():
        assert name in prompts, f"{name} is not offered as a prompt"
        assert uri in uris, f"{uri} is not offered as a resource"
        assert texts[name] == ([_packaged(name)], [_packaged(name)])


def test_source_guides_point_at_the_shared_relay_guide():
    for name in ("ignis_tiktok_browser", "ignis_threads_browser", "ignis_instagram_browser"):
        assert "`ignis_browser_relay`" in _packaged(name)


def test_the_relay_guide_keeps_the_rules_the_collect_skill_states():
    """The repository skill and the packaged guide must not drift on the safety rules."""
    relay = " ".join(_packaged("ignis_browser_relay").split())
    collect = " ".join((REPO / ".agents/skills/ignis-collect/SKILL.md").read_text(encoding="utf-8").split())
    for rule in ("evaluate `tab_script` once", "never immediately after `posted: true`", "`DEGRADED`",
                 "click, type, scroll, sign in"):
        assert rule.lower() in relay.lower(), rule
    assert "stage every one of them" in relay.lower() and "stage every sibling before submitting any" in collect.lower()
    assert "Never close a tab immediately after `posted: true`" in collect
    assert "no typing, clicking, scrolling, signing in" in collect


def test_the_relay_guide_names_every_live_run_failure():
    relay = _packaged("ignis_browser_relay")
    for symptom in ("No such file or directory", "not in the same group", "Evaluator returns `{}`",
                    "This tab was not opened by the relay", "expires_at", "Wrong account or profile",
                    "page locale is unsupported"):
        assert symptom in relay, symptom


def test_relay_guide_ships_the_pre_check_and_the_relay_tab_rule():
    relay = _packaged("ignis_browser_relay")
    assert "One relay tab may serve every source and run" in relay
    assert "only after the current relay shows `STAGED`" in relay
    assert "querySelectorAll('CARDS')" in relay and "never wait in a loop" in relay


@pytest.mark.parametrize("name", ["ignis_tiktok_browser", "ignis_threads_browser", "ignis_instagram_browser"])
def test_each_source_guide_names_its_pre_check_card_selector(name):
    assert "Pre-check card selector (relay step 5)" in _packaged(name)


def test_tiktok_guide_pre_check_selector_matches_the_extractor():
    script = resources.files("ignis.infrastructure.connectors.host_browser").joinpath("tiktok_search.js")
    card = script.read_text(encoding="utf-8").split("const CARD = '", 1)[1].split("'", 1)[0]
    assert f"`{card}`" in _packaged("ignis_tiktok_browser")


def test_relay_prepare_step_names_the_required_task_refs():
    """Spec 026 live run: prepare refused a call without them because step 1 did not name them."""
    step_one = " ".join(_packaged("ignis_browser_relay").split("2. Open `relay_url`")[0].split())
    assert "`host_task_ref`, `session_ref`" in step_one
