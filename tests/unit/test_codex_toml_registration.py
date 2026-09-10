"""The Codex TOML writer must replace fn-ignis, not accumulate copies of it."""

import tomllib

import pytest

from ignis.interfaces.cli.setup_bundle import register_mcp_to_codex_toml


STALE_CONFIG = """\
model = "gpt-5"

[mcp_servers.obsidian]
command = "/usr/bin/obsidian-mcp"
args = []

[mcp_servers.fn-ignis]
command = "/old/path/python"
args = ["-m", "ignis.interfaces.mcp.server"]

[mcp_servers.fn-ignis.env]
DATABASE_URL = "postgresql://user:hunter2@db.example.com:5432/postgres"
IGNIS_ENCRYPTION_KEY = "an-old-fernet-key="
YOUTUBE_API_KEY = "a-revoked-key"

[mcp_servers.huly]
command = "/usr/bin/huly-mcp"
args = []
"""

ENTRY = {
    "command": "/new/path/python",
    "args": ["-m", "ignis.interfaces.mcp.server"],
    "env": {"IGNIS_ENV_FILE": "/projects/fn-ignis/.env"},
}


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(STALE_CONFIG, encoding="utf-8")
    return path


def test_registration_leaves_no_stale_secrets(config_path):
    assert register_mcp_to_codex_toml(config_path, ENTRY) is True

    text = config_path.read_text(encoding="utf-8")
    for secret in ("hunter2", "an-old-fernet-key=", "a-revoked-key"):
        assert secret not in text, f"stale secret {secret!r} survived registration"


def test_registration_writes_parseable_toml(config_path):
    register_mcp_to_codex_toml(config_path, ENTRY)

    # tomllib rejects a duplicate [mcp_servers.fn-ignis.env] table outright.
    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    entry = parsed["mcp_servers"]["fn-ignis"]
    assert entry["command"] == "/new/path/python"
    assert entry["env"] == {"IGNIS_ENV_FILE": "/projects/fn-ignis/.env"}


def test_registration_preserves_other_servers_and_top_level_keys(config_path):
    register_mcp_to_codex_toml(config_path, ENTRY)

    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert parsed["model"] == "gpt-5"
    assert set(parsed["mcp_servers"]) == {"obsidian", "fn-ignis", "huly"}
    assert parsed["mcp_servers"]["huly"]["command"] == "/usr/bin/huly-mcp"


def test_registration_is_idempotent(config_path):
    for _ in range(3):
        register_mcp_to_codex_toml(config_path, ENTRY)

    text = config_path.read_text(encoding="utf-8")
    assert text.count("[mcp_servers.fn-ignis]") == 1
    assert text.count("[mcp_servers.fn-ignis.env]") == 1
    tomllib.loads(text)
