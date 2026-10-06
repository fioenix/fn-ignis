"""Production defaults refuse missing secrets without exposing the database remotely."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def render_compose(**values):
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI is unavailable")
    return subprocess.run(
        [docker, "compose", "--env-file", os.devnull, "-f",
         str(ROOT / "docker-compose.prod.yml"), "config", "--format", "json"],
        env={"PATH": os.defpath, **values}, capture_output=True, text=True, timeout=15,
    )


@pytest.mark.parametrize("values", [{}, {"POSTGRES_PASSWORD": ""}])
def test_missing_or_empty_database_password_refuses_rendering(values):
    result = render_compose(**values)
    assert result.returncode != 0
    assert "POSTGRES_PASSWORD" in result.stderr


def test_explicit_secret_and_custom_port_preserve_local_access():
    result = render_compose(POSTGRES_PASSWORD="synthetic-compose-test-secret", POSTGRES_PORT="15432")
    assert result.returncode == 0, "Compose rejected the explicit test configuration"
    db = json.loads(result.stdout)["services"]["db"]
    assert db["environment"]["POSTGRES_PASSWORD"] == "synthetic-compose-test-secret"
    assert db["ports"][0]["host_ip"] == "127.0.0.1"
    assert str(db["ports"][0]["published"]) == "15432"


def test_copied_environment_example_has_no_working_default_password():
    values = {}
    for line in (ROOT / "env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    assert values["POSTGRES_PASSWORD"] == ""
    assert "postgres:postgres@" not in values["DATABASE_URL"]
    assert render_compose(**values).returncode != 0
