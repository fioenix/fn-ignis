"""Two local MCP clients may run Ignis at the same time.

Claude Code, Claude Desktop and Codex each start their own stdio server, and a developer
routinely has more than one of them open. Server startup therefore has to be indifferent to
the other servers already running.

These are real subprocesses speaking JSON-RPC over stdio, not mocks. A test that asserts
os.kill was never called proves only that one implementation of the sweep is gone; it stays
green if the sweep comes back through pkill, psutil or a shell pipeline. What the clients
actually care about is that the first server is still answering after the second one starts,
so that is what is measured here.

Each server gets its own environment file, its own SQLite database and its own HOME, so a
failure here is about process lifecycle rather than two servers contending for one file.
"""

import json
import os
import select
import subprocess
import sys
import time

# Long enough for an import-heavy interpreter start on a loaded machine, short enough that a
# hung server fails the run instead of stalling it. Enforced by selecting on the child's stdout
# rather than by pytest-timeout, which this project does not depend on.
RESPONSE_TIMEOUT_SECONDS = 120.0
# A peer is signalled during the other server's startup, so the corpse appears almost at once.
# This is the grace period before concluding the peer survived.
SETTLE_SECONDS = 2.0

PROTOCOL_VERSION = "2024-11-05"
EXPECTED_TOOL_COUNT = 44


class StdioClient:
    """One MCP client driving one Ignis server over its own stdin/stdout pipe."""

    def __init__(self, name: str, env_file: str, home: str):
        self.name = name
        env = dict(os.environ)
        env["IGNIS_ENV_FILE"] = env_file
        env["HOME"] = home
        # Never let an ambient DSN reach the child; these servers must stay on their own file.
        env.pop("DATABASE_URL", None)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "ignis.interfaces.mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )

    def _request(self, payload: dict) -> dict:
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        readable, _, _ = select.select(
            [self.process.stdout], [], [], RESPONSE_TIMEOUT_SECONDS
        )
        if not readable:
            raise AssertionError(
                f"server {self.name} did not answer {payload['method']} within"
                f" {RESPONSE_TIMEOUT_SECONDS:.0f}s"
            )
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError(
                f"server {self.name} closed its stdout; exit code {self.process.poll()}"
            )
        return json.loads(line)

    def _notify(self, payload: dict) -> None:
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def initialize(self) -> None:
        response = self._request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": self.name, "version": "1"},
                },
            }
        )
        assert "result" in response, f"server {self.name} refused initialize: {response}"
        self._notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self) -> list:
        response = self._request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        return response["result"]["tools"]

    def call_runtime_config(self, request_id: int) -> dict:
        return self._request(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": "get_runtime_config", "arguments": {}},
            }
        )

    def is_running(self) -> bool:
        return self.process.poll() is None

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=30)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (BrokenPipeError, OSError):
                    pass


def _isolated_client(tmp_path, name: str) -> StdioClient:
    """A server whose database, environment file and HOME belong to it alone."""
    workspace = tmp_path / name
    home = workspace / "home"
    home.mkdir(parents=True)
    env_file = workspace / "env"
    env_file.write_text(
        f"DATABASE_URL=sqlite:///{workspace / 'ignis.db'}\nDEFAULT_GEO=VN\n"
    )
    client = StdioClient(name, str(env_file), str(home))
    client.initialize()
    return client


def test_second_client_does_not_terminate_the_first(tmp_path):
    """Starting a second server leaves the first one running and answering."""
    first = _isolated_client(tmp_path, "first")
    try:
        assert len(first.list_tools()) == EXPECTED_TOOL_COUNT

        second = _isolated_client(tmp_path, "second")
        try:
            assert len(second.list_tools()) == EXPECTED_TOOL_COUNT

            # The sweep signalled its peers during startup, so any corpse is already made.
            time.sleep(SETTLE_SECONDS)

            assert first.is_running(), (
                "the first server exited when the second one started; exit code "
                f"{first.process.poll()} (-15 is SIGTERM from a cross-process kill sweep)"
            )

            # Liveness is not enough: the pipe has to still carry a real call.
            response = first.call_runtime_config(request_id=3)
            assert response["result"]["isError"] is False, response
            assert second.is_running(), "the second server did not survive its own startup"
        finally:
            second.close()
    finally:
        first.close()
