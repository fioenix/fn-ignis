#!/usr/bin/env python3
"""Complete one MCP session against an installed Ignis server.

An editable install reads the source tree, so it cannot tell whether the wheel actually ships the
HTML templates and SQL seeds the server needs. Importing the module cannot tell whether a client
can use it. This does both: it starts the server, completes the JSON-RPC handshake, discovers the
tool catalog, calls a local read-only tool, and then closes stdin and requires the server to exit.

With no command it starts this interpreter's installed server, which is the built-wheel gate:
run it with the interpreter of the environment the wheel was installed into. After `--` it starts
whatever command the caller names instead -- a bootstrapped source checkout's interpreter, or
`docker run --rm -i <image>@<digest>` -- so every distribution path is held to one conversation
rather than to copies of it.

Stdout must carry newline-delimited JSON-RPC and nothing else. A process that prints a banner or a
log line there is not an MCP stdio server, however healthy it looks; the image defaulting to the
scheduler worker is exactly that failure.

It contacts no external service and consumes no API quota.

    IGNIS_ENV_FILE=wheel.env .venv/bin/python scripts/wheel_mcp_smoke.py
    python scripts/wheel_mcp_smoke.py -- docker run --rm -i ghcr.io/fioenix/fn-ignis@sha256:...
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass

EXPECTED_TOOL_COUNT = 47
PROTOCOL_VERSION = "2024-11-05"
RESPONSE_TIMEOUT_SECONDS = 120.0
# A stdio server has nothing left to do once its client hangs up. One that keeps running holds a
# client's process table and, in a container, the container itself.
EXIT_TIMEOUT_SECONDS = 30.0


class SmokeFailure(Exception):
    """The server did not hold up its side of the MCP conversation."""


@dataclass(frozen=True)
class SmokeResult:
    protocol_version: str
    tool_count: int
    runtime_configs: int | None


def default_server_command() -> list[str]:
    return [sys.executable, "-m", "ignis.interfaces.mcp.server"]


class _Session:
    """One server process, read on background threads.

    Reading a buffered text pipe after `select()` misses a second line already sitting in Python's
    buffer, and an undrained stderr can fill its pipe and stall the server. Threads avoid both.
    """

    def __init__(self, command: list[str], env: dict | None, cwd: str | None, response_timeout: float):
        self.response_timeout = response_timeout
        self.lines: queue.Queue = queue.Queue()
        self.stderr_tail: list[str] = []
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
                cwd=cwd,
            )
        except FileNotFoundError as error:
            raise SmokeFailure(f"the server command could not start: {error}") from error
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stdout(self) -> None:
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _pump_stderr(self) -> None:
        for line in self.process.stderr:
            self.stderr_tail = (self.stderr_tail + [line])[-40:]

    def stderr(self) -> str:
        return "".join(self.stderr_tail)[-4000:]

    @staticmethod
    def parse(line: str) -> dict:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            message = None
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise SmokeFailure(f"the server wrote non-MCP output to stdout: {line.strip()[:200]!r}")
        return message

    def send(self, payload: dict) -> None:
        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise SmokeFailure(
                f"the server stopped reading stdin; exit {self.process.poll()}\n{self.stderr()}"
            ) from error

    def response(self, request_id: int) -> dict:
        while True:
            try:
                line = self.lines.get(timeout=self.response_timeout)
            except queue.Empty as error:
                raise SmokeFailure(
                    f"the server did not answer request {request_id} within {self.response_timeout}s"
                ) from error
            if line is None:
                raise SmokeFailure(f"the server closed stdout; exit {self.process.poll()}\n{self.stderr()}")
            message = self.parse(line)
            # A server-initiated notification is valid MCP traffic; only the matching reply answers.
            if message.get("id") == request_id:
                return message

    def close_and_wait(self, exit_timeout: float) -> None:
        self.process.stdin.close()
        try:
            self.process.wait(timeout=exit_timeout)
        except subprocess.TimeoutExpired as error:
            raise SmokeFailure(f"the server did not exit within {exit_timeout}s after stdin closed") from error
        # Whatever it printed on the way out must still be protocol, not a shutdown banner.
        while True:
            try:
                line = self.lines.get(timeout=5)
            except queue.Empty:
                return
            if line is None:
                return
            self.parse(line)

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass


def run_smoke(
    command: list[str] | None = None,
    *,
    env: dict | None = None,
    cwd: str | None = None,
    response_timeout: float = RESPONSE_TIMEOUT_SECONDS,
    exit_timeout: float = EXIT_TIMEOUT_SECONDS,
    expected_tools: int = EXPECTED_TOOL_COUNT,
    log=lambda message: None,
) -> SmokeResult:
    """Hold one MCP conversation with `command` (default: this interpreter's server)."""
    session = _Session(command or default_server_command(), env, cwd, response_timeout)
    try:
        session.send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "wheel-smoke", "version": "1"},
                },
            }
        )
        initialized = session.response(1)
        if "result" not in initialized:
            raise SmokeFailure(f"initialize was refused: {initialized}")
        protocol = initialized["result"].get("protocolVersion", "")
        log(f"initialize ok, protocol {protocol}")

        session.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        session.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = session.response(2).get("result", {}).get("tools", [])
        if len(tools) != expected_tools:
            raise SmokeFailure(f"expected {expected_tools} tools, discovered {len(tools)}")
        log(f"tool discovery ok, {len(tools)} tools")

        session.send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_runtime_config", "arguments": {}},
            }
        )
        called = session.response(3)
        if called.get("result", {}).get("isError") is not False:
            raise SmokeFailure(f"get_runtime_config failed: {called}")
        try:
            payload = json.loads(called["result"]["content"][0]["text"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise SmokeFailure(f"get_runtime_config returned an unreadable result: {called}") from error
        if payload.get("status") != "SUCCESS":
            raise SmokeFailure(f"get_runtime_config returned {payload}")
        log(f"tool call ok, {payload.get('total_configs')} runtime configs read")

        session.close_and_wait(exit_timeout)
        log("server exited when stdin closed")
        return SmokeResult(protocol, len(tools), payload.get("total_configs"))
    finally:
        session.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="server command after `--`; defaults to this interpreter's installed Ignis server",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command

    if not command and not os.environ.get("IGNIS_ENV_FILE"):
        raise SystemExit("set IGNIS_ENV_FILE to an environment file naming a SQLite database")

    try:
        run_smoke(command or None, log=print)
    except SmokeFailure as failure:
        raise SystemExit(str(failure)) from failure
    print("the server holds a real MCP session")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
