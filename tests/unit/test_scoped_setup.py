"""Scoped setup must not write unrelated client configurations or research storage."""

import tomllib
import subprocess
import sys
import os
import pytest
from pathlib import Path

from ignis.interfaces.cli.setup_bundle import ensure_environment_file, setup_all_mcp_clients


def test_codex_only_setup_preserves_other_clients(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    codex = tmp_path / ".codex" / "config.toml"
    codex.parent.mkdir()
    codex.write_text('model = "test"\n[mcp_servers.other]\ncommand = "keep"\n')
    workspace = root / ".mcp.json"
    workspace.write_text('{"untouched": true}\n')
    env_file = tmp_path / "uat.env"

    results = setup_all_mcp_clients(root, "/test/python", client="codex", env_file=env_file)

    assert workspace.read_text() == '{"untouched": true}\n'
    assert not (tmp_path / ".gemini").exists()
    assert len(results) == 1
    parsed = tomllib.loads(codex.read_text())
    assert parsed["mcp_servers"]["other"]["command"] == "keep"
    assert parsed["mcp_servers"]["fn-ignis"]["env"] == {
        "IGNIS_ENV_FILE": str(env_file), "IGNIS_ENV_ISOLATED": "1"}


def test_explicit_environment_uses_isolated_absolute_database(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    original = root / ".env"
    original.write_text("DATABASE_URL=sqlite:///keep.db\n")
    target = tmp_path / "uat" / ".env"

    ensure_environment_file(root, env_file=target)

    assert original.read_text() == "DATABASE_URL=sqlite:///keep.db\n"
    assert f"DATABASE_URL=sqlite:///{target.parent / 'ignis.db'}\n" in target.read_text()


def test_codex_only_setup_creates_missing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    results = setup_all_mcp_clients(tmp_path, "/test/python", client="codex")
    assert results[0]["status"] == "configured"
    parsed = tomllib.loads((tmp_path / ".codex/config.toml").read_text())
    assert parsed["mcp_servers"]["fn-ignis"]["command"] == "/test/python"


def test_isolated_settings_ignore_inherited_database_and_credentials(tmp_path):
    root = Path(__file__).resolve().parents[2]
    target = tmp_path / "uat.env"
    target.write_text("DATABASE_URL=sqlite:///isolated.db\n")
    (tmp_path / ".env").write_text("THREADS_APP_SECRET=synthetic-cwd-secret\n")
    env = {**os.environ, "IGNIS_ENV_FILE": str(target), "IGNIS_ENV_ISOLATED": "1",
           "PYTHONPATH": str(root / "src"), "DATABASE_URL": "sqlite:///inherited.db",
           "YOUTUBE_API_KEY": "synthetic-inherited-key"}
    result = subprocess.run([sys.executable, "-c", "from ignis.config import settings, reveal_secret; "
        "assert reveal_secret(settings.DATABASE_URL) == 'sqlite:///isolated.db'; "
        "assert not reveal_secret(settings.THREADS_APP_SECRET); "
        "assert not reveal_secret(settings.YOUTUBE_API_KEY)"], cwd=tmp_path, env=env,
        capture_output=True, text=True)
    assert result.returncode == 0, "Isolated settings inherited unrelated configuration"


def test_failed_client_registration_cannot_report_setup_success(monkeypatch):
    from ignis.interfaces.cli import setup_bundle
    monkeypatch.setattr(setup_bundle, "ensure_environment_file", lambda root: (False, "exists"))
    async def database():
        return True, "ready"
    async def diagnostics():
        return {"database": "ready"}
    monkeypatch.setattr(setup_bundle, "bootstrap_database", database)
    monkeypatch.setattr(setup_bundle, "run_synthetic_diagnostics", diagnostics)
    monkeypatch.setattr(setup_bundle, "setup_all_mcp_clients",
        lambda root, python: [{"client": "Codex", "status": "failed"}])
    assert setup_bundle.auto_provision(json_output=True)["status"] != "success"


@pytest.mark.parametrize("exists", [False, True])
def test_isolated_startup_refuses_missing_or_incomplete_environment(tmp_path, exists):
    root = Path(__file__).resolve().parents[2]
    target = tmp_path / "missing.env"
    if exists:
        target.write_text("DEFAULT_GEO=VN\n")
    env = {**os.environ, "IGNIS_ENV_FILE": str(target), "IGNIS_ENV_ISOLATED": "1",
           "PYTHONPATH": str(root / "src")}
    result = subprocess.run([sys.executable, "-c", "import ignis.config"], cwd=tmp_path,
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0, "Isolated startup fell back to the working-directory database"


def test_provisioning_refuses_switching_an_already_loaded_settings_context(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(root / "src"), "IGNIS_ENV_FILE": "/dev/null",
           "IGNIS_ENV_ISOLATED": "0", "DATABASE_URL": "sqlite:///inherited.db"}
    code = "from ignis.config import settings; " \
        "from ignis.interfaces.cli.setup_bundle import auto_provision; " \
        "from pathlib import Path; auto_provision(client='codex', env_file=Path('new/uat.env'))"
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0, "Provisioning reused the previous settings context"
    assert not (tmp_path / "new").exists(), "Refusal must happen before environment or database writes"
