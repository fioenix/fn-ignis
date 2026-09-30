"""Regression tests for ambient credential isolation in the pytest process."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

import conftest as test_harness


REPO_ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "ambient-live-credential-must-never-reach-a-test-report"
PROBE_FLAG = "IGNIS_PYTEST_CREDENTIAL_PROBE"


def test_quarantine_replaces_live_credentials_without_retaining_their_values():
    environment = {
        "DATABASE_URL": "postgresql://owner:password@example.invalid/production",
        "YOUTUBE_API_KEY": SENTINEL,
        "THREADS_APP_SECRET": "threads-live-secret",
        "GITHUB_TOKEN": "github-live-token",
        "IGNIS_TEST_POSTGRES_DSN": "postgresql://test:test@localhost/isolated_test",
        "PATH": "/usr/bin",
    }

    test_harness.quarantine_ambient_credentials(environment)

    assert environment["DATABASE_URL"] == "sqlite:///ignis.db"
    assert environment["YOUTUBE_API_KEY"] == ""
    assert environment["THREADS_APP_SECRET"] == ""
    assert "GITHUB_TOKEN" not in environment
    assert environment["IGNIS_TEST_POSTGRES_DSN"].endswith("/isolated_test")
    assert environment["PATH"] == "/usr/bin"
    assert SENTINEL not in repr(environment)


def test_quarantine_runs_before_any_ignis_module_is_imported():
    source = (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert source.index("quarantine_ambient_credentials(os.environ)") < source.index("from ignis")


def test_failure_probe_reports_only_the_quarantined_value():
    if os.environ.get(PROBE_FLAG) != "1":
        pytest.skip("subprocess-only negative control")

    pytest.fail(f"probe observed YOUTUBE_API_KEY={os.environ.get('YOUTUBE_API_KEY')!r}")


def test_a_failing_pytest_cannot_echo_an_ambient_youtube_key():
    environment = dict(os.environ)
    environment["YOUTUBE_API_KEY"] = SENTINEL
    environment[PROBE_FLAG] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_pytest_credential_quarantine.py::test_failure_probe_reports_only_the_quarantined_value",
            "-q",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    report = completed.stdout + completed.stderr

    assert completed.returncode == 1, report
    assert "probe observed YOUTUBE_API_KEY=''" in report
    assert SENTINEL not in report
