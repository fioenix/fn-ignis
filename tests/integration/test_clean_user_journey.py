"""What a new user gets: clone, bootstrap, connect a client, call a tool.

This is the release acceptance path. A package-import smoke test proves the wheel is importable;
it does not prove that bootstrap builds the locked environment, that the database it creates has
its seeds, that the MCP registration it writes carries a path instead of secrets, or that a client
can actually complete a handshake against it. Each of those has broken separately.

The journey runs against a clean copy of the tracked tree with its own HOME, so no .venv, .env,
SQLite database or MCP client configuration from the developer's machine is visible to it. The
copy is made from `git ls-files`, which is the working-tree content of tracked files only --
ignored artifacts are exactly what must not be inherited.

Live connectors are not contacted for evidence here and no YouTube quota is consumed. Bootstrap's
own diagnostics do make one unauthenticated Google Trends RSS reachability probe, which needs no
credentials and no quota; nothing in this module asserts on its result, so the journey passes
offline as well.
"""

import json
import os
import select
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TOOL_COUNT = 39
PROTOCOL_VERSION = "2024-11-05"

# Bootstrap builds a virtual environment and installs 155 locked packages. Warm uv cache makes
# that seconds; a cold one has to download, which is why this is generous.
BOOTSTRAP_TIMEOUT_SECONDS = 900
RESPONSE_TIMEOUT_SECONDS = 120.0

# Secrets that used to be copied into every generated MCP config. The entry must carry a path to
# the environment file instead, so none of these may appear in a generated registration.
FORBIDDEN_ENTRY_KEYS = ("DATABASE_URL", "IGNIS_ENCRYPTION_KEY", "YOUTUBE_API_KEY", "DEFAULT_GEO")

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None,
    reason="the release path is the frozen uv install; without uv there is no path to accept",
)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [name for name in out.split("\0") if name]


def _clean_checkout(destination: Path) -> Path:
    """A source tree holding tracked files only -- no .venv, .env, database or client config."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in _tracked_files():
        source = REPO_ROOT / name
        if not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for inherited in (".venv", ".env", ".mcp.json", "ignis.db"):
        assert not (destination / inherited).exists(), (
            f"{inherited} leaked into the clean checkout; the journey would not be measuring a"
            " first run"
        )
    return destination


def _claude_desktop_config_path(home: Path) -> Path:
    """Where the product will put Claude Desktop's config, for this platform and this HOME.

    Asked rather than assumed. The path is ~/Library/Application Support/Claude on macOS and
    ~/.config/Claude on Linux, so a test that hard-codes either one seeds a file the code never
    writes to and then reports that registration failed. On Linux that is doubly wrong: the
    registration is skipped entirely unless the parent directory already exists, which is exactly
    what seeding is meant to arrange.
    """
    from ignis.interfaces.cli.setup_bundle import get_claude_desktop_config_path

    previous = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        return get_claude_desktop_config_path()
    finally:
        if previous is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous


def _seed_client_configs(home: Path) -> dict[str, Path]:
    """Pre-existing client configuration holding entries that belong to other servers.

    Registration has to add fn-ignis beside them. Rewriting one of these files wholesale would
    silently delete a user's other MCP servers, and on the Codex TOML an earlier implementation
    appended a second env table each run instead of replacing the old one.
    """
    antigravity = home / ".gemini" / "config" / "mcp_config.json"
    antigravity.parent.mkdir(parents=True, exist_ok=True)
    antigravity.write_text(
        json.dumps({"mcpServers": {"unrelated-neighbour": {"command": "echo", "args": ["keep-me"]}}}),
        encoding="utf-8",
    )

    claude = _claude_desktop_config_path(home)
    claude.parent.mkdir(parents=True, exist_ok=True)
    claude.write_text(
        json.dumps({"mcpServers": {"unrelated-neighbour": {"command": "echo", "args": ["keep-me"]}}}),
        encoding="utf-8",
    )

    codex = home / ".codex" / "config.toml"
    codex.parent.mkdir(parents=True, exist_ok=True)
    codex.write_text(
        'model = "gpt-5"\n\n[mcp_servers.unrelated-neighbour]\ncommand = "echo"\nargs = ["keep-me"]\n',
        encoding="utf-8",
    )
    return {"antigravity": antigravity, "claude": claude, "codex": codex}


def _bootstrap_env(home: Path) -> dict:
    env = dict(os.environ)
    env["HOME"] = str(home)
    # An ambient DSN or environment-file override would point the fresh install at the developer's
    # own database, which is the opposite of what a first run does.
    for leaked in ("DATABASE_URL", "IGNIS_ENV_FILE", "IGNIS_ENCRYPTION_KEY", "VIRTUAL_ENV"):
        env.pop(leaked, None)
    return env


class StdioSession:
    """A client speaking MCP over the clean checkout's own interpreter."""

    def __init__(self, checkout: Path, home: Path, name: str):
        env = _bootstrap_env(home)
        env["IGNIS_ENV_FILE"] = str((checkout / ".env").resolve())
        self.name = name
        self.process = subprocess.Popen(
            [str(checkout / ".venv" / "bin" / "python"), "-m", "ignis.interfaces.mcp.server"],
            cwd=str(checkout),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )

    def request(self, payload: dict) -> dict:
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        readable, _, _ = select.select([self.process.stdout], [], [], RESPONSE_TIMEOUT_SECONDS)
        if not readable:
            raise AssertionError(f"{self.name} did not answer {payload['method']} in time")
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError(
                f"{self.name} closed stdout; exit {self.process.poll()};"
                f" stderr: {self.process.stderr.read()[:2000]}"
            )
        return json.loads(line)

    def initialize(self) -> dict:
        response = self.request(
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
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.process.stdin.flush()
        return response

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


@pytest.fixture(scope="module")
def bootstrapped(tmp_path_factory):
    """Run the documented first-run command once, and hand the result to every assertion."""
    base = tmp_path_factory.mktemp("clean-user")
    checkout = _clean_checkout(base / "checkout")
    home = base / "home"
    home.mkdir()
    seeded = _seed_client_configs(home)

    completed = subprocess.run(
        ["./scripts/bootstrap.sh"],
        cwd=str(checkout),
        capture_output=True,
        text=True,
        timeout=BOOTSTRAP_TIMEOUT_SECONDS,
        env=_bootstrap_env(home),
    )
    if completed.returncode != 0:
        pytest.fail(
            "bootstrap.sh failed on a clean checkout\n"
            f"stdout:\n{completed.stdout[-4000:]}\n\nstderr:\n{completed.stderr[-4000:]}"
        )
    return {
        "checkout": checkout,
        "home": home,
        "seeded": seeded,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def test_bootstrap_uses_the_locked_uv_path(bootstrapped):
    """The reproducible branch ran, and the best-effort pip fallback did not."""
    output = bootstrapped["stdout"] + bootstrapped["stderr"]
    assert "Installed the exact solution recorded in uv.lock." in output, output[-3000:]
    assert "Best-effort install complete" not in output


def test_bootstrap_creates_the_environment_file_and_database(bootstrapped):
    checkout = bootstrapped["checkout"]

    env_file = checkout / ".env"
    assert env_file.exists(), "a first run must write its own .env"
    env_text = env_file.read_text(encoding="utf-8")
    assert "DATABASE_URL=sqlite:///ignis.db" in env_text, "a fresh install must default to SQLite"
    key_line = next(
        line for line in env_text.splitlines() if line.startswith("IGNIS_ENCRYPTION_KEY=")
    )
    assert key_line.split("=", 1)[1].strip(), "the generated Fernet key must not be empty"

    database = checkout / "ignis.db"
    assert database.exists() and database.stat().st_size > 0, "no SQLite database was created"


def test_bootstrap_loads_schema_and_seed_lexicons(bootstrapped):
    """Tables alone are not readiness; the vocabulary rows the engines read must be there."""
    import sqlite3

    with sqlite3.connect(bootstrapped["checkout"] / "ignis.db") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"sources", "observations", "mission_evidence", "market_lexicons"} <= tables, (
            f"schema incomplete; found {sorted(tables)}"
        )
        seeded_terms = connection.execute("SELECT COUNT(*) FROM market_lexicons").fetchone()[0]

    assert seeded_terms > 0, "the database has its schema but none of its seed vocabulary"


def test_workspace_registration_carries_a_path_not_secrets(bootstrapped):
    checkout = bootstrapped["checkout"]
    entry = json.loads((checkout / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["fn-ignis"]

    assert entry["command"] == str(checkout / ".venv" / "bin" / "python"), (
        "the registration must point at this checkout's interpreter, not the developer's"
    )
    assert entry["args"] == ["-m", "ignis.interfaces.mcp.server"]
    assert set(entry["env"]) == {"IGNIS_ENV_FILE"}, (
        f"the entry must carry only IGNIS_ENV_FILE, found {sorted(entry['env'])}"
    )
    assert entry["env"]["IGNIS_ENV_FILE"] == str((checkout / ".env").resolve())

    serialized = json.dumps(entry)
    for forbidden in FORBIDDEN_ENTRY_KEYS:
        assert forbidden not in serialized, (
            f"{forbidden} was copied into the MCP registration; secrets belong in .env only"
        )


def test_registration_keeps_the_user_other_mcp_servers(bootstrapped):
    """Adding fn-ignis must not rewrite a config file out from under its other entries."""
    seeded = bootstrapped["seeded"]

    for label in ("antigravity", "claude"):
        servers = json.loads(seeded[label].read_text(encoding="utf-8"))["mcpServers"]
        assert "unrelated-neighbour" in servers, f"{label} lost an unrelated MCP server"
        assert servers["unrelated-neighbour"]["args"] == ["keep-me"]
        assert "fn-ignis" in servers, f"{label} did not receive the fn-ignis entry"

    codex_text = seeded["codex"].read_text(encoding="utf-8")
    assert "[mcp_servers.unrelated-neighbour]" in codex_text, "Codex lost an unrelated MCP server"
    assert 'model = "gpt-5"' in codex_text, "Codex lost configuration outside the server tables"
    assert codex_text.count("[mcp_servers.fn-ignis]") == 1, "Codex gained a duplicate fn-ignis table"


def test_a_client_can_handshake_discover_and_call(bootstrapped):
    """The whole point: a client connects to the fresh install and a tool answers."""
    session = StdioSession(bootstrapped["checkout"], bootstrapped["home"], "clean-user")
    try:
        initialized = session.initialize()
        assert "result" in initialized, initialized
        assert initialized["result"]["protocolVersion"] == PROTOCOL_VERSION

        tools = session.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        assert len(tools) == EXPECTED_TOOL_COUNT, (
            f"expected {EXPECTED_TOOL_COUNT} tools, discovered {len(tools)}"
        )

        called = session.request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_runtime_config", "arguments": {}},
            }
        )
        assert called["result"]["isError"] is False, called
        payload = json.loads(called["result"]["content"][0]["text"])
        assert payload["status"] == "SUCCESS", payload
    finally:
        session.close()


def test_two_clients_share_the_fresh_install(bootstrapped):
    """The concurrent-client contract, re-measured in the environment a new user actually gets."""
    first = StdioSession(bootstrapped["checkout"], bootstrapped["home"], "first")
    try:
        first.initialize()
        assert len(first.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]) == (
            EXPECTED_TOOL_COUNT
        )

        second = StdioSession(bootstrapped["checkout"], bootstrapped["home"], "second")
        try:
            second.initialize()
            assert len(
                second.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
            ) == EXPECTED_TOOL_COUNT

            assert first.is_running(), (
                "the first client's server died when a second client connected; exit code"
                f" {first.process.poll()}"
            )
            still_answering = first.request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "get_runtime_config", "arguments": {}},
                }
            )
            assert still_answering["result"]["isError"] is False, still_answering
        finally:
            second.close()
    finally:
        first.close()
