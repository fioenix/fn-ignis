"""Derive Hermes tool catalogs from the public FastMCP schema."""

import argparse
import asyncio
import json
from pathlib import Path

from ignis.interfaces.mcp.server import mcp


ROOT = Path(__file__).resolve().parents[1]
CATALOGS = (ROOT / "hermes_manifest.json", ROOT / ".hermes/tools.json")


async def expected_catalog(path: Path) -> str:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    previous = json.loads(path.read_text(encoding="utf-8"))
    names = [
        item["function"]["name"]
        for item in previous
        if item["function"]["name"] in tools
    ]
    names.extend(sorted(set(tools) - set(names)))
    entries = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": tools[name].description,
                "parameters": tools[name].parameters,
            },
        }
        for name in names
    ]
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"


async def run(write: bool) -> int:
    drifted = []
    for path in CATALOGS:
        expected = await expected_catalog(path)
        if path.read_text(encoding="utf-8") != expected:
            drifted.append(path.relative_to(ROOT).as_posix())
            if write:
                path.write_text(expected, encoding="utf-8")
    if drifted:
        print("Updated: " + ", ".join(drifted) if write else "Drift: " + ", ".join(drifted))
    return 0 if write or not drifted else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.write))


if __name__ == "__main__":
    raise SystemExit(main())
