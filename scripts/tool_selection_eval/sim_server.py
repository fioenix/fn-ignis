"""MCP stdio server that republishes the live Ignis catalog with scripted handlers.

Every handler is simulated: no call reaches a source, store, browser, session,
token or network endpoint. Each call is appended to a JSONL log for scoring.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import jsonschema
import mcp_types

from scripts.tool_selection_eval.catalog import Catalog, load_catalog, wraps_result
from scripts.tool_selection_eval.intents import load_intents

UNSCRIPTED = {"status": "SUCCESS", "items": []}
CAP_REACHED = {"status": "ERROR", "message": "Rate limit reached for this session; try again later."}


class Simulator:
    """Answer tool calls for one intent from its scripted responses."""

    def __init__(self, intent: dict[str, Any], catalog: Catalog, cap: int, log_path: Path) -> None:
        self.intent = intent
        self.catalog = catalog
        self.cap = cap
        self.log_path = log_path
        self.calls = 0
        self._consumed: dict[str, int] = {}

    def _scripted(self, name: str) -> dict[str, Any]:
        scripted = self.intent.get("responses", {}).get(name)
        if not scripted:
            return UNSCRIPTED
        index = self._consumed.get(name, 0)
        self._consumed[name] = index + 1
        return scripted[min(index, len(scripted) - 1)]

    def _log(self, entry: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def call(self, name: str, arguments: dict[str, Any] | None) -> mcp_types.CallToolResult:
        self.calls += 1
        arguments = arguments or {}
        tool = self.catalog.tool(name)
        entry: dict[str, Any] = {"n": self.calls, "tool": name, "arguments": arguments}
        if tool is None:
            entry["outcome"] = "unknown_tool"
            self._log(entry)
            return _error(f"Unknown tool: {name}")
        if self.calls > self.cap:
            entry["outcome"] = "cap"
            self._log(entry)
            return _result(tool, CAP_REACHED)
        errors = sorted(
            jsonschema.Draft202012Validator(tool.input_schema).iter_errors(arguments),
            key=lambda error: list(error.path),
        )
        if errors:
            entry["outcome"] = "invalid_arguments"
            self._log(entry)
            return _error(f"Input validation error: {errors[0].message}")
        response = self._scripted(name)
        entry["outcome"] = "unscripted" if response is UNSCRIPTED else "scripted"
        self._log(entry)
        return _result(tool, response)


def _error(message: str) -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=message)], is_error=True
    )


def _result(tool: mcp_types.Tool, response: dict[str, Any]) -> mcp_types.CallToolResult:
    text = json.dumps(response, ensure_ascii=False)
    structured = {"result": text} if wraps_result(tool) else response
    return mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=text)],
        structured_content=structured,
    )


def build_server(simulator: Simulator):
    from mcp.server.lowlevel import Server

    catalog = simulator.catalog

    async def on_list_tools(_context, _params) -> mcp_types.ListToolsResult:
        return mcp_types.ListToolsResult(tools=catalog.tools)

    async def on_list_prompts(_context, _params) -> mcp_types.ListPromptsResult:
        return mcp_types.ListPromptsResult(prompts=catalog.prompts)

    async def on_call_tool(_context, params: mcp_types.CallToolRequestParams):
        return simulator.call(params.name, params.arguments)

    return Server(
        "fn-ignis-social-market-research",
        instructions=catalog.instructions,
        on_list_tools=on_list_tools,
        on_list_prompts=on_list_prompts,
        on_call_tool=on_call_tool,
    )


async def _serve(args: argparse.Namespace) -> None:
    from mcp.server.stdio import stdio_server

    intent = load_intents(Path(args.intents)).by_id(args.intent_id)
    simulator = Simulator(intent, await load_catalog(), args.cap, Path(args.log))
    server = build_server(simulator)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intents", required=True)
    parser.add_argument("--intent-id", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--cap", type=int, default=8)
    asyncio.run(_serve(parser.parse_args()))


if __name__ == "__main__":
    main()
