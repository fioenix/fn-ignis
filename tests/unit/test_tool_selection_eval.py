"""Model-free tests for the Spec 028 tool-selection eval."""

from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
from pathlib import Path

import pytest
from mcp.client.client import Client

from scripts.tool_selection_eval.catalog import load_catalog
from scripts.tool_selection_eval.intents import IntentSet, load_intents, validate
from scripts.tool_selection_eval.scoring import aggregate, score_intent, stability
from scripts.tool_selection_eval.sim_server import Simulator, build_server

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tool_selection_intents.json"


@pytest.fixture(scope="module")
def catalog():
    return asyncio.run(load_catalog())


@pytest.fixture(scope="module")
def intent_set() -> IntentSet:
    return load_intents(FIXTURE)


def _intent(**overrides):
    intent = {
        "id": "X01",
        "journey": "tactical",
        "trap": False,
        "text": "check health",
        "acceptable_first": ["diagnose_system_health"],
        "acceptable_path": ["diagnose_system_health", "get_system_logs"],
        "trap_tools": ["verify_connectors_health"],
        "terminal": "diagnose_system_health",
        "responses": {
            "diagnose_system_health": [{"status": "HEALTHY"}, {"status": "DEGRADED"}],
            "get_system_logs": [{"status": "SUCCESS"}],
        },
    }
    intent.update(overrides)
    return intent


def test_fixture_fits_the_live_catalog(intent_set, catalog):
    assert validate(intent_set, catalog.tool_names) == []
    ids = {intent["id"] for intent in intent_set.intents}
    assert {"T05-show-my-threads", "M01-find-opportunities-vi"} <= ids


def test_validate_refuses_unknown_tools_overlap_and_missing_responses(catalog):
    broken = _intent(
        acceptable_path=["diagnose_system_health", "get_system_logs", "verify_connectors_health"],
        trap_tools=["verify_connectors_health", "no_such_tool"],
        responses={"diagnose_system_health": [{"status": "HEALTHY"}]},
    )
    problems = validate(IntentSet("t", [broken]), catalog.tool_names)
    joined = "\n".join(problems)
    assert "no_such_tool, which the live catalog does not publish" in joined
    assert "verify_connectors_health is both acceptable and a trap" in joined
    assert "get_system_logs has no scripted response" in joined
    assert "expected 40-50 intents" in joined


def test_score_counts_first_call_trap_wrong_calls_and_terminal():
    row = score_intent(_intent(), ["verify_connectors_health", "diagnose_system_health"], capped=False)
    assert row["first_call_ok"] is False
    assert row["first_call_trap"] is True
    assert row["wrong_calls"] == 1
    assert row["reached_terminal"] is True
    assert row["calls_to_terminal"] == 2


def test_reply_terminal_counts_no_call_as_acceptable_and_any_wrong_call_as_failure():
    reply = _intent(acceptable_first=["reply"], acceptable_path=[], terminal="reply", responses={})
    clean = score_intent(reply, [], capped=False)
    assert clean["first_call_ok"] and clean["reached_terminal"] and clean["calls_to_terminal"] == 0
    wrong = score_intent(reply, ["verify_connectors_health"], capped=False)
    assert not wrong["first_call_ok"] and not wrong["reached_terminal"]


def test_neutral_reads_are_skipped_for_the_first_call_and_never_wrong():
    neutral = frozenset({"list_research_missions"})
    row = score_intent(
        _intent(), ["list_research_missions", "diagnose_system_health"], capped=False, neutral=neutral
    )
    assert row["first_call"] == "diagnose_system_health" and row["first_call_ok"]
    assert row["raw_first_call"] == "list_research_missions"
    assert row["wrong_calls"] == 0 and row["neutral_calls"] == 1
    reply = _intent(acceptable_first=["reply"], acceptable_path=[], terminal="reply")
    only_reads = score_intent(reply, ["list_research_missions"], capped=False, neutral=neutral)
    assert only_reads["first_call_ok"] and only_reads["reached_terminal"]
    trapped = score_intent(reply, ["list_research_missions", "verify_connectors_health"], False, neutral)
    assert not trapped["first_call_ok"] and trapped["any_trap_call"]


def test_validate_refuses_a_neutral_tool_used_as_a_trap(catalog):
    intent_set = IntentSet(
        "t",
        [_intent(trap_tools=["list_research_missions"])],
        neutral_tools=frozenset({"list_research_missions"}),
        neutral_responses={"list_research_missions": [{"status": "SUCCESS"}]},
    )
    assert "X01: list_research_missions is neutral and cannot be a trap" in validate(intent_set, catalog.tool_names)


def test_capped_run_does_not_reach_a_reply_terminal():
    reply = _intent(acceptable_first=["reply", "get_system_logs"], acceptable_path=["get_system_logs"], terminal="reply")
    assert score_intent(reply, ["get_system_logs"] * 9, capped=True)["reached_terminal"] is False


def test_aggregate_and_stability_apply_the_ten_point_bar():
    rows = [
        score_intent(_intent(id="a", trap=True), ["diagnose_system_health"], False),
        score_intent(_intent(id="b"), ["verify_connectors_health"], False),
    ]
    metrics = aggregate(rows)
    assert metrics["first_call_accuracy"] == 50.0
    assert metrics["trap_first_call_accuracy"] == 100.0
    assert metrics["trap_first_call_wrong"] == 0
    assert metrics["trap_call_rate"] == 50.0
    assert metrics["first_call_accuracy_by_journey"]["tactical"] == 50.0
    base = {
        "first_call_accuracy": 60.0,
        "trap_first_call_accuracy": 50.0,
        "trap_call_rate": 5.0,
        "terminal_reach_rate": 70.0,
    }
    assert stability([base, {**base, "first_call_accuracy": 70.0}])["stable"] is True
    shaky = stability([base, {**base, "trap_first_call_accuracy": 62.5}])
    assert shaky["stable"] is False and shaky["unstable_metrics"] == ["trap_first_call_accuracy"]
    assert stability([base])["stable"] is False


def test_simulator_scripts_validates_caps_and_logs(catalog, tmp_path):
    log = tmp_path / "calls.jsonl"
    sim = Simulator(_intent(), catalog, cap=4, log_path=log)
    first = sim.call("diagnose_system_health", {})
    assert json.loads(first.content[0].text) == {"status": "HEALTHY"}
    assert first.structured_content == {"result": '{"status": "HEALTHY"}'}
    assert json.loads(sim.call("diagnose_system_health", {}).content[0].text) == {"status": "DEGRADED"}
    assert json.loads(sim.call("list_research_missions", {}).content[0].text) == {"status": "SUCCESS", "items": []}
    defaulted = Simulator(_intent(), catalog, cap=4, log_path=tmp_path / "d.jsonl", defaults={"get_watchlist": [{"status": "DEFAULT"}]})
    assert json.loads(defaulted.call("get_watchlist", {"watchlist_id": "wl-1"}).content[0].text) == {"status": "DEFAULT"}
    invalid = sim.call("get_tiktok_video_comments", {})
    assert invalid.is_error and "video_url" in invalid.content[0].text
    assert json.loads(sim.call("diagnose_system_health", {}).content[0].text) == {"status": "ERROR", "message": "Rate limit reached for this session; try again later."}
    outcomes = [json.loads(line)["outcome"] for line in log.read_text().splitlines()]
    assert outcomes == ["scripted", "scripted", "unscripted", "invalid_arguments", "cap"]


def test_simulator_reaches_no_network_or_store(catalog, tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("simulated handler reached a real network or store")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(sqlite3, "connect", refuse)
    sim = Simulator(_intent(), catalog, cap=100, log_path=tmp_path / "calls.jsonl")
    for tool in catalog.tools:
        sim.call(tool.name, {})


def test_simulated_server_publishes_the_live_catalog_unchanged(catalog, tmp_path):
    async def published():
        server = build_server(Simulator(_intent(), catalog, cap=8, log_path=tmp_path / "c.jsonl"))
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            prompts = (await client.list_prompts()).prompts
            result = await client.call_tool("diagnose_system_health", {})
            return tools, prompts, client.instructions, result

    tools, prompts, instructions, result = asyncio.run(published())
    dump = lambda items: [item.model_dump(mode="json", exclude_none=True) for item in items]  # noqa: E731
    assert dump(tools) == dump(catalog.tools)
    assert dump(prompts) == dump(catalog.prompts)
    assert instructions == catalog.instructions
    assert json.loads(result.content[0].text) == {"status": "HEALTHY"}


def test_runner_treats_a_missing_start_line_as_a_dead_simulator(tmp_path):
    from scripts.tool_selection_eval.run import read_calls

    assert read_calls(tmp_path / "absent.jsonl") == ([], False, False)
    log = tmp_path / "calls.jsonl"
    log.write_text(
        '{"n": 0, "tool": null, "outcome": "started"}\n'
        '{"n": 1, "tool": "get_watchlist", "outcome": "scripted"}\n'
        '{"n": 9, "tool": "get_watchlist", "outcome": "cap"}\n'
    )
    assert read_calls(log) == (["get_watchlist", "get_watchlist"], True, True)
