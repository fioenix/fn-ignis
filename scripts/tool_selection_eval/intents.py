"""Load and validate the tool-selection intent set."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPLY = "reply"
JOURNEYS = ("tactical", "watchlist", "mission")
MIN_INTENTS, MAX_INTENTS, MIN_TRAPS = 40, 50, 16
INTENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


@dataclass(frozen=True)
class IntentSet:
    version: str
    intents: list[dict[str, Any]]
    neutral_tools: frozenset[str] = frozenset()
    neutral_responses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def by_id(self, intent_id: str) -> dict[str, Any]:
        for intent in self.intents:
            if intent["id"] == intent_id:
                return intent
        raise KeyError(intent_id)


def load_intents(path: Path) -> IntentSet:
    data = json.loads(path.read_text(encoding="utf-8"))
    return IntentSet(
        version=data["version"],
        intents=data["intents"],
        neutral_tools=frozenset(data.get("neutral_tools", [])),
        neutral_responses=data.get("neutral_responses", {}),
    )


def validate(intent_set: IntentSet, tool_names: set[str]) -> list[str]:
    """Return every problem that makes the set unfit to run; empty when it is fit."""
    problems: list[str] = []
    intents = intent_set.intents
    if not MIN_INTENTS <= len(intents) <= MAX_INTENTS:
        problems.append(f"expected {MIN_INTENTS}-{MAX_INTENTS} intents, found {len(intents)}")
    traps = sum(1 for intent in intents if intent.get("trap"))
    if traps < MIN_TRAPS:
        problems.append(f"expected at least {MIN_TRAPS} trap intents, found {traps}")
    journeys = {intent.get("journey") for intent in intents}
    if journeys != set(JOURNEYS):
        problems.append(f"journeys must be exactly {JOURNEYS}, found {sorted(map(str, journeys))}")

    neutral = set(intent_set.neutral_tools)
    for name in sorted(neutral - tool_names):
        problems.append(f"neutral tool {name} is not in the live catalog")
    for name in sorted(neutral - set(intent_set.neutral_responses)):
        problems.append(f"neutral tool {name} has no default response")

    seen: set[str] = set()
    for intent in intents:
        intent_id = intent.get("id", "?")
        if intent_id in seen:
            problems.append(f"{intent_id}: duplicate id")
        seen.add(intent_id)
        if not INTENT_ID.match(str(intent_id)):
            problems.append(f"{intent_id}: id must be letters, digits and hyphens (it names files)")
        text = str(intent.get("text", "")).strip()
        if not text:
            problems.append(f"{intent_id}: empty text")
        elif text.startswith("-"):
            problems.append(f"{intent_id}: text must not start with '-' (the host CLI would read an option)")
        first = intent.get("acceptable_first") or []
        path = set(intent.get("acceptable_path") or [])
        trap_tools = set(intent.get("trap_tools") or [])
        terminal = intent.get("terminal")
        responses = intent.get("responses") or {}
        if not first:
            problems.append(f"{intent_id}: acceptable_first is empty")
        if intent.get("trap") and not trap_tools and REPLY not in first:
            problems.append(f"{intent_id}: a trap needs trap_tools or a reply as acceptable first")
        named = {name for name in first if name != REPLY} | path | trap_tools | set(responses)
        if terminal != REPLY:
            named.add(terminal)
        for name in sorted(named - tool_names):
            problems.append(f"{intent_id}: names {name}, which the live catalog does not publish")
        for name in sorted({name for name in first if name != REPLY} - path):
            problems.append(f"{intent_id}: first tool {name} is missing from acceptable_path")
        if terminal != REPLY and terminal not in path:
            problems.append(f"{intent_id}: terminal {terminal} is missing from acceptable_path")
        for name in sorted(path & trap_tools):
            problems.append(f"{intent_id}: {name} is both acceptable and a trap")
        for name in sorted(trap_tools & neutral):
            problems.append(f"{intent_id}: {name} is neutral and cannot be a trap")
        for name in sorted(path - set(responses) - set(intent_set.neutral_responses)):
            problems.append(f"{intent_id}: acceptable tool {name} has no scripted response")
    return problems
