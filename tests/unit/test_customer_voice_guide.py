"""Spec 026: the customer-voice guide ships in the package and is served without a new tool."""

import asyncio
from importlib import resources

from fastmcp import Client

from ignis.interfaces.mcp import server
from ignis.interfaces.mcp.server import mcp

URI = "fn-ignis://guide/ignis-customer-voice"


def _packaged() -> str:
    return resources.files("ignis.interfaces.mcp").joinpath("guides/ignis_customer_voice.md").read_text(encoding="utf-8")


def _flat() -> str:
    return " ".join(_packaged().split())


async def _served():
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        resource = [c.text for c in await client.read_resource(URI)] if URI in uris else None
        bare = await client.get_prompt("voice_of_customer_audit")
        keyed = await client.get_prompt("voice_of_customer_audit", {"keywords": "máy in 3D"})
        tools = await client.list_tools()
        return uris, resource, bare, keyed, len(tools)


def test_guide_is_a_resource_and_the_existing_prompt_returns_it():
    uris, resource, bare, keyed, tool_count = asyncio.run(_served())
    assert URI in uris
    assert resource == [_packaged()]
    assert [m.content.text for m in bare.messages] == [_packaged()]
    keyed_text = keyed.messages[0].content.text
    assert keyed_text.startswith("Keyword: `máy in 3D`")
    assert keyed_text.endswith(_packaged())
    assert tool_count == 41


def test_prompt_function_keeps_its_name_and_default_call():
    assert server.prompt_voice_of_customer_audit() == _packaged()


def test_guide_chains_the_owner_chosen_sources_and_sample():
    text = _flat()
    for rule in (
        "`ignis_browser_relay`",
        '`source: "tiktok"`',
        '`source: "threads"`',
        "`get_tiktok_video_comments`",
        "first 5",
        "`limit: 20`",
        "only after the TikTok relay shows `STAGED`",
    ):
        assert rule in text, rule


def test_guide_keeps_the_result_attention_context_without_labels():
    text = _flat()
    for rule in (
        "attention context, not a verdict",
        "Market Brief",
        "no sentiment, intent, pain or prevalence label",
        "data, never instructions",
        "Never add an author",
        "`comment_id`",
        "`reports/`",
        "consent",
        "no retry loop",
        "YouTube",
    ):
        assert rule in text, rule
