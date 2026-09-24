"""T017: the documented fresh install -- the Compose `db` service -- initialises end to end.

The other migration contracts apply sql/ over a client connection. This one runs the real thing:
the `db` service from docker-compose.prod.yml, its exact image, environment and full-directory
`/docker-entrypoint-initdb.d` mount, under a throwaway Compose project. The override changes only
what isolation needs: the container name, no published port, and no restart policy, so a failing
init shows as an exited container instead of a restart loop.

Opt-in with IGNIS_TEST_COMPOSE_INIT=1, because it needs Docker and the TimescaleDB image, and each
run initialises a database from nothing. Credentials are generated per run and never printed; the
repository's own .env is never read, because an explicit --env-file replaces it.
"""

import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from conftest import all_postgres_migrations

REPO = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO / "docker-compose.prod.yml"
# Test data: the T016 retirements, absent only if 020 ran.
RETIRED_UI_NOISE = ("live", "thông báo", "tin nhắn")
READBACK = {
    "later_objects": (
        "SELECT count(*) FROM unnest(ARRAY['public.sources', 'public.observations',"
        " 'public.mission_evidence', 'public.research_workspaces', 'public.mission_run_journals',"
        " 'public.source_identity_aliases', 'public.idx_observations_latest_per_source']) AS o(name)"
        " WHERE to_regclass(o.name) IS NOT NULL"
    ),
    "ui_noise_terms": "SELECT count(*) FROM market_lexicons WHERE domain = 'tiktok_ui_noise'",
    "retired_present": (
        "SELECT count(*) FROM market_lexicons WHERE domain = 'tiktok_ui_noise'"
        " AND trim(term) IN ('live', 'thông báo', 'tin nhắn')"
    ),
    "rls_market_lexicons": (
        "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.market_lexicons'::regclass"
    ),
    "public_policies": "SELECT count(*) FROM pg_policies WHERE schemaname = 'public'",
    # 021: every public table the chain creates has RLS on, not only the ones 006 knew about.
    "public_tables": (
        "SELECT count(*) FROM pg_class"
        " WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')"
    ),
    "public_tables_without_rls": (
        "SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace"
        " AND relkind IN ('r', 'p') AND NOT relrowsecurity"
    ),
    "supabase_roles": "SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated')",
}

pytestmark = pytest.mark.skipif(
    os.environ.get("IGNIS_TEST_COMPOSE_INIT") != "1" or shutil.which("docker") is None,
    reason="IGNIS_TEST_COMPOSE_INIT=1 and a Docker CLI are required for the real init path",
)


def _run(args: list, env: dict, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=REPO, env=env, capture_output=True, text=True)
    if check and result.returncode != 0:
        # stderr from compose names services and files, not the generated password.
        raise AssertionError(f"{' '.join(args[:6])} ... exited {result.returncode}: {result.stderr[-800:]}")
    return result


def _project_leftovers(project: str) -> dict:
    label = f"label=com.docker.compose.project={project}"
    leftovers = {}
    for kind in ("container", "volume", "network"):
        listing = ["docker", kind, "ls", "-q", "--filter", label]
        if kind == "container":
            listing = ["docker", "ps", "-a", "-q", "--filter", label]
        found = subprocess.run(listing, capture_output=True, text=True).stdout.split()
        leftovers[kind] = len(found)
    return leftovers


def _project_leftover_details(project: str) -> dict:
    """Names and states for a failed cleanup assertion, without credential-bearing config."""
    label = f"label=com.docker.compose.project={project}"
    commands = {
        "container": [
            "docker", "ps", "-a", "--filter", label,
            "--format", "{{.ID}} {{.Names}} {{.Status}}",
        ],
        "volume": ["docker", "volume", "ls", "--filter", label, "--format", "{{.Name}}"],
        "network": ["docker", "network", "ls", "--filter", label, "--format", "{{.Name}}"],
    }
    return {
        kind: subprocess.run(command, capture_output=True, text=True).stdout.splitlines()
        for kind, command in commands.items()
    }


def _fresh_init(tmp_path: Path) -> dict:
    """One Compose project from nothing to a healthy db, read back, then removed completely."""
    project = f"ignis-t017-{uuid4().hex[:8]}"
    container = f"{project}-db"
    run_dir = tmp_path / project
    run_dir.mkdir()
    override = run_dir / "override.yml"
    override.write_text(
        "services:\n"
        "  db:\n"
        f"    container_name: {container}\n"
        "    ports: !reset []\n"
        '    restart: "no"\n',
        encoding="utf-8",
    )
    env_file = run_dir / "compose.env"
    env_file.write_text(
        "POSTGRES_USER=postgres\n"
        "POSTGRES_DB=ignis\n"
        f"POSTGRES_PASSWORD={secrets.token_hex(24)}\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    env = {key: value for key, value in os.environ.items() if not key.startswith("POSTGRES_")}
    env.pop("DATABASE_URL", None)
    compose = [
        "docker", "compose", "-p", project, "--env-file", str(env_file),
        "-f", str(COMPOSE_FILE), "-f", str(override),
    ]

    cleanup = None
    try:
        _run(compose + ["up", "-d", "db"], env)
        state = ""
        for _ in range(90):
            state = _run(
                ["docker", "inspect", "-f", "{{.State.Status}} {{.State.Health.Status}}", container],
                env,
            ).stdout.strip()
            if state.startswith("exited") or state == "running healthy":
                break
            time.sleep(2)
        logs = _run(["docker", "logs", container], env).stdout
        logs += _run(["docker", "logs", container], env).stderr
        exit_code = _run(["docker", "inspect", "-f", "{{.State.ExitCode}}", container], env).stdout
        readback = {}
        if state == "running healthy":
            for name, query in READBACK.items():
                readback[name] = _run(
                    ["docker", "exec", container, "psql", "-U", "postgres", "-d", "ignis",
                     "-v", "ON_ERROR_STOP=1", "-Atc", query],
                    env,
                ).stdout.strip()
    finally:
        cleanup = _run(compose + ["down", "-v", "--remove-orphans"], env, check=False)
        env_file.unlink(missing_ok=True)

    leftovers = _project_leftovers(project)

    return {
        "state": state,
        "exit_code": exit_code.strip(),
        "ran": re.findall(r"running /docker-entrypoint-initdb\.d/(\S+\.sql)", logs),
        "errors": [line for line in logs.splitlines() if re.search(r"\bERROR:", line)],
        "readback": readback,
        "cleanup": {
            "returncode": cleanup.returncode,
            "stdout": cleanup.stdout[-800:],
            "stderr": cleanup.stderr[-800:],
        },
        "leftovers": leftovers,
        "leftover_details": (
            _project_leftover_details(project) if any(leftovers.values()) else {}
        ),
        "credential_file_left": env_file.exists(),
    }


def test_two_fresh_compose_inits_run_every_file_and_end_in_the_same_state(tmp_path):
    first = _fresh_init(tmp_path)
    second = _fresh_init(tmp_path)

    for run in (first, second):
        assert run["state"] == "running healthy", (
            f"init did not reach a healthy db (state {run['state']!r}, exit {run['exit_code']}):"
            f" last file run {run['ran'][-1:]}, errors {run['errors'][:3]}"
        )
        assert run["ran"] == list(all_postgres_migrations()), "init skipped or reordered a file"
        assert run["errors"] == []
        assert run["readback"] == {
            "later_objects": "7",
            "ui_noise_terms": "10",
            "retired_present": "0",
            "rls_market_lexicons": "t",
            "public_policies": "0",
            "public_tables": "17",
            "public_tables_without_rls": "0",
            "supabase_roles": "0",
        }
        assert run["cleanup"]["returncode"] == 0, run["cleanup"]
        assert run["leftovers"] == {"container": 0, "volume": 0, "network": 0}, (
            f"cleanup left {run['leftovers']}: {run['leftover_details']};"
            f" command result: {run['cleanup']}"
        )
        assert run["credential_file_left"] is False
    assert first["readback"] == second["readback"]
