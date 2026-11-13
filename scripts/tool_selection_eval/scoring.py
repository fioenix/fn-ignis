"""Score host-agent tool calls against the intent set. Pure functions, no model calls."""

from __future__ import annotations

from statistics import median
from typing import Any

from scripts.tool_selection_eval.intents import JOURNEYS, REPLY

STABILITY_BAR_POINTS = 10.0
RATE_METRICS = (
    "first_call_accuracy",
    "trap_first_call_accuracy",
    "trap_call_rate",
    "terminal_reach_rate",
)


def decisive_first(intent: dict[str, Any], calls: list[str], neutral: frozenset[str]) -> str | None:
    """First call that commits to a path: a neutral read counts only if the intent asks for it."""
    for name in calls:
        if name not in neutral or name in intent["acceptable_first"]:
            return name
    return None


def score_intent(
    intent: dict[str, Any], calls: list[str], capped: bool, neutral: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Score one transcript: `calls` is the ordered list of tool names the agent called.

    Neutral tools are read-only orientation calls (listing missions, reading a watchlist); they
    never count as wrong and are skipped when finding the decisive first call.
    """
    first = decisive_first(intent, calls, neutral)
    path = set(intent["acceptable_path"]) | neutral
    trap_tools = set(intent.get("trap_tools") or [])
    terminal = intent["terminal"]
    if first is None:
        first_ok = REPLY in intent["acceptable_first"]
    else:
        first_ok = first in intent["acceptable_first"]
    wrong = [name for name in calls if name not in path]
    if terminal == REPLY:
        reached = not capped and not wrong
        calls_to_terminal = len(calls) if reached else None
    elif terminal in calls:
        reached = True
        calls_to_terminal = calls.index(terminal) + 1
    else:
        reached = False
        calls_to_terminal = None
    return {
        "id": intent["id"],
        "journey": intent["journey"],
        "trap": bool(intent.get("trap")),
        "first_call": first,
        "raw_first_call": calls[0] if calls else None,
        "neutral_calls": sum(1 for name in calls if name in neutral and name not in intent["acceptable_path"]),
        "first_call_ok": first_ok,
        "first_call_trap": first in trap_tools,
        "wrong_calls": len(wrong),
        "wrong_tools": wrong,
        "trap_calls": [name for name in calls if name in trap_tools],
        "any_trap_call": any(name in trap_tools for name in calls),
        "reached_terminal": reached,
        "calls_to_terminal": calls_to_terminal,
        "capped": capped,
        "calls": calls,
    }


def _rate(rows: list[dict[str, Any]], key: str) -> float | None:
    if not rows:
        return None
    return round(100.0 * sum(1 for row in rows if row[key]) / len(rows), 1)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Headline metrics of one run, as percentages where they are rates."""
    traps = [row for row in rows if row["trap"]]
    terminal_calls = [row["calls_to_terminal"] for row in rows if row["calls_to_terminal"]]
    return {
        "intents": len(rows),
        "first_call_accuracy": _rate(rows, "first_call_ok"),
        "trap_first_call_accuracy": _rate(traps, "first_call_ok"),
        "trap_first_call_wrong": sum(1 for row in traps if not row["first_call_ok"]),
        "trap_call_rate": _rate(rows, "any_trap_call"),
        "first_call_accuracy_by_journey": {
            journey: _rate([row for row in rows if row["journey"] == journey], "first_call_ok")
            for journey in JOURNEYS
        },
        "mean_wrong_calls": round(sum(row["wrong_calls"] for row in rows) / len(rows), 2)
        if rows
        else None,
        "mean_neutral_calls": round(sum(row["neutral_calls"] for row in rows) / len(rows), 2)
        if rows
        else None,
        "terminal_reach_rate": _rate(rows, "reached_terminal"),
        "median_calls_to_terminal": median(terminal_calls) if terminal_calls else None,
    }


def stability(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Spread of each rate metric over repeated runs and the 10-point verdict."""
    spreads: dict[str, dict[str, float]] = {}
    for metric in RATE_METRICS:
        values = [run[metric] for run in runs if run.get(metric) is not None]
        if not values:
            continue
        spreads[metric] = {
            "min": min(values),
            "max": max(values),
            "spread": round(max(values) - min(values), 1),
        }
    unstable = [name for name, item in spreads.items() if item["spread"] > STABILITY_BAR_POINTS]
    return {
        "runs": len(runs),
        "spreads": spreads,
        "stable": len(runs) > 1 and not unstable,
        "unstable_metrics": unstable,
    }
