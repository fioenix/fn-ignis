"""T019: the fresh Compose initialization contract runs on its own, under a name protection can require.

tests/integration/test_compose_init.py is the only test that drives the documented fresh install --
the `db` service from docker-compose.prod.yml, its image, and the full `sql/` mount -- from an empty
volume to a healthy database. It is opt-in, so the ordinary suite skips it, and until T019 nothing
ran it unless an operator remembered to. A migration could therefore break fresh initialization
while every build stayed green.

These contracts pin the wiring that makes the gate worth having: it runs on every pull request and
on the protected branches, it reaches the real test and nothing else, a skipped run cannot pass for
a green one, it carries no credential or database of its own, and it reports under one stable name
that a branch-protection rule can select. Making that name *required* is a GitHub settings
operation this repository cannot perform or prove; these tests only guarantee the name exists and
cannot drift silently.
"""

import re
import shlex
from pathlib import Path

# PyYAML arrives with fastmcp, a required runtime dependency. Parsing matters: `on:` changes meaning
# with one stray indent, and a regex cannot tell a configured trigger from a commented-out one.
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
COMPOSE_INIT_WORKFLOW = WORKFLOWS / "compose-init.yml"
PERFORMANCE_WORKFLOW = WORKFLOWS / "performance.yml"
CI_WORKFLOW = WORKFLOWS / "ci.yml"
COMPOSE_FILE = REPO / "docker-compose.prod.yml"
COMPOSE_INIT_TEST = "tests/integration/test_compose_init.py"
OPT_IN = "IGNIS_TEST_COMPOSE_INIT"

# The status string a branch-protection rule selects. Renaming either the job id or its display name
# retires the gate silently -- protection keeps waiting on a check that never reports again.
WORKFLOW_NAME = "Compose Init"
JOB_ID = "compose-fresh-init"
JOB_NAME = "Fresh Compose database init"
CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_UV_ACTION = "astral-sh/setup-uv@caf0cab7a618c569241d31dcd442f54681755d39"
UV_VERSION = "0.12.17"

PROTECTED_BRANCH_PATTERNS = {"main", "release/*", "hotfix/*"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _triggers(workflow: dict) -> dict:
    """The `on:` block. PyYAML follows YAML 1.1, where a bare `on` key parses as the boolean True."""
    for key in ("on", True):
        if key in workflow:
            return workflow[key]
    raise AssertionError("the workflow declares no triggers at all")


def _workflow() -> dict:
    assert COMPOSE_INIT_WORKFLOW.exists(), (
        f"{COMPOSE_INIT_WORKFLOW.relative_to(REPO)} does not exist, so nothing runs the fresh Compose"
        " init contract and a migration can break a new install while every build stays green"
    )
    return _load(COMPOSE_INIT_WORKFLOW)


def _job() -> dict:
    jobs = _workflow()["jobs"]
    assert JOB_ID in jobs, (
        f"no job is called {JOB_ID!r}; branch protection selects the gate by its status name, so"
        f" renaming it retires the gate without reporting anything. Jobs found: {sorted(jobs)}"
    )
    return jobs[JOB_ID]


def _steps() -> list:
    return _job()["steps"]


def _step(name: str) -> dict:
    matches = [step for step in _steps() if step.get("name") == name]
    assert len(matches) == 1, f"expected one step named {name!r}; found {len(matches)}"
    return matches[0]


def _steps_text() -> str:
    return "\n".join(step.get("run", "") for step in _steps())


def _contract_steps() -> list:
    return [step for step in _steps() if OPT_IN in (step.get("env") or {})]


def _contract_step() -> dict:
    steps = _contract_steps()
    assert len(steps) == 1, (
        f"expected exactly one step to set {OPT_IN}; found {len(steps)}. Without it the Compose test"
        " skips, and pytest reports a skipped test as a green run."
    )
    return steps[0]


# --- the workflow exists, parses, and reports under one stable name -----------------------------


def test_the_compose_init_workflow_exists_and_parses():
    workflow = _workflow()
    assert isinstance(workflow, dict) and workflow.get("jobs"), "the workflow parsed to no jobs"
    assert workflow.get("name") == WORKFLOW_NAME, (
        f"the workflow must be named {WORKFLOW_NAME!r} (found {workflow.get('name')!r})"
    )


def test_the_job_carries_the_exact_stable_name():
    job = _job()
    assert job.get("name") == JOB_NAME, (
        f"the job must report as {JOB_NAME!r}; a required status check is selected by that string"
        f" and silently stops being satisfied when it changes (found {job.get('name')!r})"
    )


def test_the_workflow_has_a_single_job_so_the_gate_is_the_whole_workflow():
    jobs = _workflow()["jobs"]
    assert list(jobs) == [JOB_ID], (
        f"the workflow holds jobs {sorted(jobs)}; a second job would be a check no rule requires,"
        " or would split the gate across names"
    )


def test_the_job_is_not_a_matrix_so_its_status_name_does_not_vary():
    assert "strategy" not in _job(), (
        "a matrix publishes one status per combination, and those names move with the matrix, so"
        " no single one can be required"
    )


def test_the_stable_names_are_unique_across_every_workflow():
    """Two checks with one name make a required-status rule ambiguous about which one it reads."""
    job_names = []
    workflow_names = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = _load(path)
        workflow_names.append(workflow.get("name"))
        for job_id, job in (workflow.get("jobs") or {}).items():
            job_names.append(job.get("name", job_id))
    assert job_names.count(JOB_NAME) == 1, f"{JOB_NAME!r} appears {job_names.count(JOB_NAME)} times"
    assert workflow_names.count(WORKFLOW_NAME) == 1, (
        f"{WORKFLOW_NAME!r} names {workflow_names.count(WORKFLOW_NAME)} workflows"
    )


# --- when it runs --------------------------------------------------------------------------------


def test_the_gate_runs_on_every_pull_request_without_a_filter():
    """A required check that a filter skips never reports, and the pull request waits forever."""
    triggers = _triggers(_workflow())
    assert "pull_request" in triggers, "pull requests do not run the gate, so it cannot be required"
    pull_request = triggers["pull_request"] or {}
    for narrowing in ("branches", "branches-ignore", "paths", "paths-ignore"):
        assert narrowing not in pull_request, (
            f"pull_request is narrowed by {narrowing!r}. A skipped required check never reports,"
            " so an unmatched pull request blocks forever -- and a stacked one is never checked."
        )
    assert "pull_request_target" not in triggers, (
        "pull_request_target runs fork code with the base repository's token and secrets"
    )


def test_the_gate_runs_on_protected_branch_pushes_and_on_demand():
    triggers = _triggers(_workflow())
    assert "push" in triggers, "nothing re-checks fresh init when work lands on a protected branch"
    branches = set(triggers["push"]["branches"])
    missing = PROTECTED_BRANCH_PATTERNS - branches
    assert not missing, f"the gate does not cover {sorted(missing)}; it covers {sorted(branches)}"
    assert "paths" not in triggers["push"] and "paths-ignore" not in triggers["push"]
    assert "workflow_dispatch" in triggers, "an operator cannot re-run the gate without a commit"


# --- where and how long -------------------------------------------------------------------------


def test_the_runner_image_is_pinned():
    runner = _job()["runs-on"]
    assert runner == "ubuntu-24.04", (
        f"the gate must stay on 'ubuntu-24.04' until a reviewed change moves it; found {runner!r}"
    )


def test_the_workflow_grants_no_more_than_read_access():
    permissions = _workflow().get("permissions")
    assert permissions == {"contents": "read"}, (
        f"the workflow declares permissions {permissions!r}; it only reads the repository"
    )
    assert "permissions" not in _job(), "the job overrides the read-only workflow permissions"


def test_a_hung_init_is_bounded_by_a_timeout():
    timeout = _job().get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 45, (
        f"timeout-minutes is {timeout!r}; without a bound a hung init holds a runner for six hours"
    )


def test_duplicate_runs_on_one_ref_cannot_pile_up():
    concurrency = _workflow().get("concurrency")
    assert isinstance(concurrency, dict), (
        "no concurrency group, so every push to a pull request starts another full Compose init"
    )
    group = str(concurrency.get("group", ""))
    assert "github.ref" in group, f"the concurrency group {group!r} is not scoped to the ref"
    assert "compose-init" in group, (
        f"the concurrency group {group!r} could collide with another workflow's group"
    )
    assert concurrency.get("cancel-in-progress") == "${{ github.event_name == 'pull_request' }}", (
        "only superseded pull-request runs may be cancelled; protected-branch pushes must queue"
    )


# --- what it installs and what it runs ----------------------------------------------------------


def test_dependencies_are_installed_from_the_committed_lockfile():
    steps = _steps_text()
    assert "uv sync --locked" in steps, (
        "without --locked, uv re-resolves from the version ranges instead of installing uv.lock"
    )
    for forbidden in ("uv lock", "uv pip install", "pip install"):
        assert forbidden not in steps, f"the workflow runs {forbidden!r} instead of the locked set"


def test_bootstrap_actions_and_uv_are_immutable():
    checkout = _step("Checkout repository")
    setup_uv = _step("Install uv")
    assert checkout.get("uses") == CHECKOUT_ACTION, (
        "checkout must use the reviewed commit SHA, not a movable release tag"
    )
    assert setup_uv.get("uses") == SETUP_UV_ACTION, (
        "setup-uv must use the reviewed commit SHA, not a movable release tag"
    )
    assert str((setup_uv.get("with") or {}).get("version")) == UV_VERSION, (
        f"the gate must install the reviewed uv version {UV_VERSION}, not a moving latest release"
    )


def test_the_opt_in_is_set_only_on_the_contract_step():
    """Set wider, it would also enable the contract anywhere else pytest runs in this job."""
    workflow = _workflow()
    job = _job()
    assert OPT_IN not in (workflow.get("env") or {}), f"{OPT_IN} is set for the whole workflow"
    assert OPT_IN not in (job.get("env") or {}), f"{OPT_IN} is set for the whole job"
    step = _contract_step()
    assert str(step["env"][OPT_IN]) == "1", (
        f"{OPT_IN} is {step['env'][OPT_IN]!r}; the test runs only when it is exactly '1'"
    )


def test_the_contract_step_invokes_only_the_real_compose_init_test():
    command = _contract_step()["run"]
    pytest_lines = [line for line in command.splitlines() if "pytest" in line]
    assert len(pytest_lines) == 1, f"expected one pytest invocation, found {pytest_lines}"
    words = shlex.split(pytest_lines[0])
    test_paths = [word for word in words if word.startswith("tests/")]
    assert test_paths == [COMPOSE_INIT_TEST], (
        f"the contract step runs {test_paths}; it must run {COMPOSE_INIT_TEST} and nothing else"
    )
    for narrowing in ("-k", "--deselect", "-m", "--ignore", "-p"):
        assert narrowing not in words, (
            f"the contract step passes {narrowing}, which can deselect or disable the contract"
        )


def test_the_contract_step_cannot_swallow_its_exit_code():
    step = _contract_step()
    assert step.get("continue-on-error") is not True, "a failing init would leave the build green"
    assert not re.search(r"\|\|\s*(true|:)", step["run"]), "the step swallows pytest's exit code"


def test_a_skipped_contract_fails_the_gate():
    """pytest exits 0 when every test skips. Docker missing on the runner must not read as green."""
    command = _contract_step()["run"]
    match = re.search(r"--junitxml[= ](\S+)", command)
    assert match, (
        "the contract step writes no JUnit report, so nothing can tell a run that passed from one"
        " that skipped because Docker or the opt-in was missing"
    )
    report = match.group(1)
    steps = _steps()
    index = steps.index(_contract_step())
    verifiers = [
        step
        for step in steps[index + 1 :]
        if report in step.get("run", "") and "skipped" in step.get("run", "")
    ]
    assert verifiers, (
        f"no step after the contract reads {report} and rejects skipped tests; a skip would pass"
    )
    verifier = verifiers[0]["run"]
    for counter in ("tests", "skipped", "failures", "errors"):
        assert counter in verifier, f"the skip check does not read the JUnit {counter!r} counter"


# --- what may never reach this job --------------------------------------------------------------


def test_no_database_url_hosted_dsn_or_secret_is_introduced():
    text = _text(COMPOSE_INIT_WORKFLOW)
    for forbidden in (
        "DATABASE_URL",
        "IGNIS_TEST_POSTGRES_DSN",
        "postgresql://",
        "postgres://",
        "secrets.",
        "supabase",
        "POSTGRES_PASSWORD",
        "POSTGRES_USER",
    ):
        assert forbidden not in text, (
            f"the workflow mentions {forbidden!r}; the Compose test generates throwaway credentials"
            " and owns its database, so any connection string or secret here is a leak surface"
        )


def test_the_workflow_does_not_restate_the_database_it_tests():
    """docker-compose.prod.yml is the subject. A second copy in CI would test the copy instead."""
    job = _job()
    assert "services" not in job, "the job declares its own database service instead of Compose"
    assert "container" not in job, "the job runs inside a container instead of on the runner"
    text = _text(COMPOSE_INIT_WORKFLOW)
    for restated in (
        "timescale/",
        "image:",
        "docker-entrypoint-initdb.d",
        "docker-compose.prod.yml",
        "docker run",
        "docker compose up",
        "psql",
        "sql/0",
    ):
        assert restated not in text, (
            f"the workflow restates {restated!r}; the image, mount and migration list must come"
            " from docker-compose.prod.yml and sql/ through the integration test"
        )


def test_the_integration_test_still_drives_the_production_compose_file_and_full_sql_mount():
    test_source = _text(REPO / COMPOSE_INIT_TEST)
    assert 'COMPOSE_FILE = REPO / "docker-compose.prod.yml"' in test_source, (
        "the Compose init test no longer drives docker-compose.prod.yml"
    )
    assert "all_postgres_migrations()" in test_source, (
        "the Compose init test no longer compares the init log with every file in sql/"
    )
    db = _load(COMPOSE_FILE)["services"]["db"]
    assert "./sql:/docker-entrypoint-initdb.d" in db["volumes"], (
        "the production db service no longer mounts the whole sql/ directory as its init scripts"
    )


# --- kept separate from the other gates ---------------------------------------------------------


def test_the_performance_gate_stays_in_its_own_workflow():
    text = _text(COMPOSE_INIT_WORKFLOW)
    assert "t021_read_path_benchmark" not in text, "the SC-001 benchmark moved into this workflow"
    performance = _text(PERFORMANCE_WORKFLOW)
    assert COMPOSE_INIT_TEST not in performance and OPT_IN not in performance, (
        "the performance workflow runs the Compose init contract, so the two gates are no longer"
        " distinguishable"
    )


def test_the_ordinary_matrix_does_not_enable_the_compose_contract():
    """One gate in two places is two gates to keep in step, and a matrix of four init runs."""
    assert OPT_IN not in _text(CI_WORKFLOW), (
        f"{CI_WORKFLOW.name} sets {OPT_IN}, so every Python matrix leg also runs the Compose init"
    )
