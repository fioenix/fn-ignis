"""Read the live Ignis MCP catalog without running the server's lifespan."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import mcp_types


@dataclass(frozen=True)
class Catalog:
    tools: list[mcp_types.Tool]
    prompts: list[mcp_types.Prompt]
    instructions: str | None

    @property
    def tool_names(self) -> set[str]:
        return {tool.name for tool in self.tools}

    def tool(self, name: str) -> mcp_types.Tool | None:
        return next((tool for tool in self.tools if tool.name == name), None)

    def fingerprint(self) -> str:
        """SHA-256 over tool names, descriptions and input schemas."""
        payload = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in sorted(self.tools, key=lambda item: item.name)
        ]
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def load_catalog() -> Catalog:
    """Return the tools, prompts and instructions the real server publishes."""
    from ignis.interfaces.mcp.server import mcp

    tools = [tool.to_mcp_tool() for tool in await mcp.list_tools()]
    prompts = [prompt.to_mcp_prompt() for prompt in await mcp.list_prompts()]
    return Catalog(tools=tools, prompts=prompts, instructions=mcp.instructions)


def wraps_result(tool: mcp_types.Tool) -> bool:
    """True when the tool's output schema wraps a string under `result`."""
    schema: dict[str, Any] = tool.output_schema or {}
    return bool(schema.get("x-fastmcp-wrap-result"))
