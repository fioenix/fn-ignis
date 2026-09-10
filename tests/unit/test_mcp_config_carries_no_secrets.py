"""An MCP config is a pointer to the secrets, never a copy of them.

build_mcp_entry used to copy DATABASE_URL, IGNIS_ENCRYPTION_KEY and YOUTUBE_API_KEY into every
config it wrote: the workspace .mcp.json, Claude Desktop's, Antigravity's, and Codex's TOML.
That put a database password and a Fernet key in plaintext in four places and made each of them
a second source of truth. Rotating the YouTube key in .env left Claude Desktop's copy stale, and
since a host's `env` overrides the env file, every YouTube call through MCP failed with "API key
expired" while the same code run from a shell succeeded.
"""

import re
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from ignis.interfaces.cli.setup_bundle import build_mcp_entry

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Names that carry a credential rather than a location.
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|DSN|_URL$)", re.I)


def test_the_entry_names_no_credential():
    entry = build_mcp_entry("/usr/bin/python", PROJECT_ROOT)

    offenders = [name for name in entry["env"] if SECRET_NAME.search(name)]

    assert not offenders, (
        "an MCP config is written to several files, one of them outside the repo; it must "
        f"point at .env rather than copy it. Credential-shaped keys: {offenders}"
    )


def test_the_entry_points_at_the_project_env_file():
    entry = build_mcp_entry("/usr/bin/python", PROJECT_ROOT)
    pointer = entry["env"]["IGNIS_ENV_FILE"]

    assert Path(pointer).is_absolute(), "a host starts the server with a cwd of its own choosing"
    assert Path(pointer) == (PROJECT_ROOT / ".env").resolve()


def test_no_value_in_the_entry_looks_like_a_live_secret():
    """Belt and braces: catch a credential smuggled in under an innocent name."""
    entry = build_mcp_entry("/usr/bin/python", PROJECT_ROOT)

    for name, value in entry["env"].items():
        assert "://" not in str(value), f"{name} looks like a connection string"
        assert not re.match(r"^AIza[0-9A-Za-z_-]{30,}$", str(value)), f"{name} looks like an API key"


def _probe_env_files(order, tmp_path):
    """Read a couple of settings through a given env_file order, from tmp_path as cwd."""
    class Probe(BaseSettings):
        model_config = SettingsConfigDict(env_file=order, env_file_encoding="utf-8", extra="ignore")
        YOUTUBE_API_KEY: str = ""

    return Probe().YOUTUBE_API_KEY


def test_a_stray_env_file_in_the_working_directory_does_not_outrank_the_project(tmp_path, monkeypatch):
    """pydantic-settings gives the last file priority, so the bare ".env" has to come first.

    With the old order a project's own values were overridden by whatever .env happened to sit
    in the directory the host started the server from.
    """
    real = tmp_path / "real.env"
    real.write_text("YOUTUBE_API_KEY=the_real_one\n", encoding="utf-8")
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / ".env").write_text("YOUTUBE_API_KEY=the_decoy\n", encoding="utf-8")
    monkeypatch.chdir(decoy)

    assert _probe_env_files((".env", real), tmp_path) == "the_real_one"
    # The order the code used to have, kept here to show what it cost.
    assert _probe_env_files((real, ".env"), tmp_path) == "the_decoy"


def test_an_explicit_env_file_wins_over_both(tmp_path, monkeypatch):
    """IGNIS_ENV_FILE is what an MCP config sets, so it has to be the highest priority."""
    project = tmp_path / "project.env"
    project.write_text("YOUTUBE_API_KEY=from_project\n", encoding="utf-8")
    explicit = tmp_path / "explicit.env"
    explicit.write_text("YOUTUBE_API_KEY=from_explicit\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("YOUTUBE_API_KEY=from_cwd\n", encoding="utf-8")
    monkeypatch.chdir(elsewhere)

    assert _probe_env_files((".env", project, explicit), tmp_path) == "from_explicit"


def test_the_settings_module_orders_its_env_files_least_specific_first():
    """Guard the order itself, since the failure is silent: wrong values, no error."""
    from ignis import config

    files = [str(source) for source in config._ENV_FILES]

    assert files[0] == ".env", "the working directory must be the weakest source"
    assert files[1] == str(config._PROJECT_ENV), "the project's own file outranks the cwd"
    assert len(files) <= 3


def test_the_committed_example_config_carries_no_secret():
    """mcp.example.json ships in the repo, so it must show the pointer, not a credential.

    The developer's own .mcp.json is deliberately not asserted here. It is untracked and
    machine-local, so failing the suite over it would make the result depend on whose checkout
    is running. Bringing an existing config into line is the job of setup_bundle, which rewrites
    the fn-ignis entry, not of a test.
    """
    candidate = PROJECT_ROOT / "mcp.example.json"
    if not candidate.exists():
        pytest.skip("mcp.example.json not present")

    text = candidate.read_text(encoding="utf-8")

    assert not re.search(r"AIza[0-9A-Za-z_-]{30,}", text), "the example config holds an API key"
    assert "postgresql://postgres." not in text, "the example config holds a live database DSN"
    assert not re.search(r"IGNIS_ENCRYPTION_KEY\"\s*:\s*\"[A-Za-z0-9_=-]{20,}", text), (
        "the example config holds a Fernet key"
    )
