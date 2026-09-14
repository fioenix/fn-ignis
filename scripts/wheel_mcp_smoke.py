#!/usr/bin/env python3
"""Complete one MCP session against an Ignis installed from its built wheel.

An editable install reads the source tree, so it cannot tell whether the wheel actually ships the
HTML templates and SQL seeds the server needs. Importing the module cannot tell whether a client
can use it. This does both: it starts the installed console script, completes the JSON-RPC
handshake, discovers the tool catalog, and calls a local read-only tool.

Run it with the interpreter of the environment the wheel was installed into. It contacts no
external service and consumes no API quota.
"""

import json
import os
import select
import subprocess
import sys

EXPECTED_TOOL_COUNT = 39
PROTOCOL_VERSION = "2024-11-05"
RESPONSE_TIMEOUT_SECONDS = 120.0


def _read(process) -> dict:
    readable, _, _ = select.select([process.stdout], [], [], RESPONSE_TIMEOUT_SECONDS)
    if not readable:
        raise SystemExit("the server did not answer within the timeout")
    line = process.stdout.readline()
    if not line:
        raise SystemExit(
            f"the server closed stdout; exit {process.poll()}\n{process.stderr.read()[:4000]}"
        )
    return json.loads(line)


def _send(process, payload: dict) -> None:
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()


def main() -> int:
    if not os.environ.get("IGNIS_ENV_FILE"):
        raise SystemExit("set IGNIS_ENV_FILE to an environment file naming a SQLite database")

    process = subprocess.Popen(
        [sys.executable, "-m", "ignis.interfaces.mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "wheel-smoke", "version": "1"},
                },
            },
        )
        initialized = _read(process)
        if "result" not in initialized:
            raise SystemExit(f"initialize was refused: {initialized}")
        print(f"initialize ok, protocol {initialized['result']['protocolVersion']}")

        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        _send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = _read(process)["result"]["tools"]
        if len(tools) != EXPECTED_TOOL_COUNT:
            raise SystemExit(f"expected {EXPECTED_TOOL_COUNT} tools, discovered {len(tools)}")
        print(f"tool discovery ok, {len(tools)} tools")

        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_runtime_config", "arguments": {}},
            },
        )
        called = _read(process)
        if called.get("result", {}).get("isError") is not False:
            raise SystemExit(f"get_runtime_config failed: {called}")
        payload = json.loads(called["result"]["content"][0]["text"])
        if payload.get("status") != "SUCCESS":
            raise SystemExit(f"get_runtime_config returned {payload}")
        print(f"tool call ok, {payload.get('total_configs')} runtime configs read")

        print("wheel serves a real MCP session")
        return 0
    finally:
        process.kill()
        process.wait(timeout=30)


if __name__ == "__main__":
    raise SystemExit(main())
