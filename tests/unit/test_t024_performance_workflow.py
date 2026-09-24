"""SC-001 needs a gate that runs on its own, not a number somebody remembers to measure.

T021 produced the benchmark and the evidence: twenty enforced runs, ten per backend, all under the
50 ms threshold. That evidence describes 22/09/2026 and nothing after it. A criterion is only held
if something re-measures it without being asked, and fails when it stops being true.

These contracts check the properties that decide whether the workflow is worth having. The
benchmark itself is far too slow to be a test here -- it seeds 10,000 observations twice -- so what
is asserted is the wiring around it: that it runs on the protected branches, that both backends
enforce rather than report, that PostgreSQL is reached only through the throwaway service, that no
credential can reach a public build log, and that the job carries a name stable enough to be named
as a required status check.

Deliberately also asserted: that this workflow is *not* wired into every pull request. Adding two
10,000-observation seeds to the ordinary matrix would cost every contributor minutes on every push
to catch a regression that only matters when it reaches a protected branch. That is a policy, so it
is pinned like one -- a later edit that quietly attaches `pull_request` has to change this test and
say why.
"""

import re
from pathlib import Path

# PyYAML arrives with fastmcp, a required runtime dependency, so it is present in every environment
# the suite runs in. Parsing rather than pattern-matching matters here: `on:` is the one key whose
# meaning a stray indent silently changes, and a regex over the text cannot tell a trigger that is
# configured from one that is commented out.
import yaml

REPO = Path(__file__).resolve().parents[2]
PERFORMANCE_WORKFLOW = REPO / ".github" / "workflows" / "performance.yml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
BENCHMARK_SCRIPT = "scripts/t021_read_path_benchmark.py"

# The job whose status name a branch-protection rule would select. Renaming it silently retires the
# gate -- protection keeps requiring a check that no longer reports -- so the name is pinned here.
JOB_ID = "sc001-read-path-p95"
JOB_NAME = "SC-001 get_top_clusters P95"

# Branches the gate has to cover: the release line, and the hotfix line that bypasses it.
PROTECTED_BRANCH_PATTERNS = {"main", "release/*", "hotfix/*"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _triggers(workflow: dict) -> dict:
    """The `on:` block, under whichever key PyYAML produced.

    YAML 1.1 resolves a bare `on` to the boolean True, and PyYAML still implements 1.1. A test that
    only looked up the string key would find nothing and pass every assertion phrased as "not
    present", which is the failure mode this helper exists to remove.
    """
    for key in ("on", True):
        if key in workflow:
            return workflow[key]
    raise AssertionError("the workflow declares no triggers at all")


def _job() -> dict:
    workflow = _load(PERFORMANCE_WORKFLOW)
    jobs = workflow["jobs"]
    assert JOB_ID in jobs, (
        f"no job is called {JOB_ID!r}; the branch-protection rule selects a job by its status name,"
        f" so renaming it retires the gate without reporting anything. Jobs found: {sorted(jobs)}"
    )
    return jobs[JOB_ID]


def _steps_text() -> str:
    """Every `run:` body in the job, concatenated."""
    return "\n".join(step.get("run", "") for step in _job()["steps"])


# --- the workflow exists and is its own thing ---------------------------------------------------


def test_the_performance_workflow_exists():
    assert PERFORMANCE_WORKFLOW.exists(), (
        "SC-001 has evidence from one afternoon and no gate. Without a workflow the threshold is"
        " re-checked only when somebody remembers, which is the state T021 already left behind."
    )


def test_the_gate_runs_on_the_protected_branches_on_a_schedule_and_on_demand():
    triggers = _triggers(_load(PERFORMANCE_WORKFLOW))

    assert "push" in triggers, "nothing re-measures SC-001 when work lands on a protected branch"
    branches = set(triggers["push"]["branches"])
    missing = PROTECTED_BRANCH_PATTERNS - branches
    assert not missing, f"the gate does not cover {sorted(missing)}; it covers {sorted(branches)}"

    assert "schedule" in triggers, (
        "a push-only gate measures the code and never the runner. Read-path latency also drifts"
        " with the hosted image and the service container, which only a scheduled run sees."
    )
    assert triggers["schedule"], "the schedule block is empty, so nothing is ever scheduled"
    assert all("cron" in entry for entry in triggers["schedule"])

    assert "workflow_dispatch" in triggers, (
        "no manual run, so re-measuring after a suspected regression means pushing a commit"
    )


def test_the_gate_is_not_attached_to_every_pull_request():
    """Policy, pinned. Two 10,000-observation seeds do not belong in the ordinary PR loop."""
    triggers = _triggers(_load(PERFORMANCE_WORKFLOW))
    assert "pull_request" not in triggers, (
        "the benchmark seeds 10,000 observations per backend; attaching it to every pull request"
        " charges every contributor for a regression that only matters on a protected branch"
    )
    assert "pull_request_target" not in triggers


def test_the_ordinary_test_matrix_does_not_run_the_benchmark():
    """Separate workflow, separate job. One gate in two places is two gates to keep in step."""
    assert BENCHMARK_SCRIPT not in _text(CI_WORKFLOW), (
        f"{CI_WORKFLOW.name} invokes {BENCHMARK_SCRIPT}, so the benchmark is inside the ordinary"
        " matrix after all and the separate workflow buys nothing"
    )


# --- the job reports under a name protection can select -----------------------------------------


def test_the_job_carries_an_explicit_stable_name():
    job = _job()
    assert job.get("name") == JOB_NAME, (
        f"the job must report as {JOB_NAME!r}; a required status check is selected by that string"
        f" and silently stops being satisfied when it changes (found {job.get('name')!r})"
    )


def test_the_job_is_not_a_matrix_so_its_status_name_does_not_vary():
    """A matrix job reports one status per combination, and the names change with the matrix."""
    assert "strategy" not in _job(), (
        "a matrix would publish several status names that move whenever the matrix does, so no"
        " single one can be required"
    )


def test_the_runner_image_is_pinned():
    """`ubuntu-latest` re-points without notice. A timing gate cannot use a moving floor."""
    runner = _job()["runs-on"]
    assert runner != "ubuntu-latest", (
        "`ubuntu-latest` follows GitHub's migration schedule, so the machine under a latency"
        " threshold changes on a date nobody here chose"
    )
    assert re.fullmatch(r"ubuntu-\d\d\.\d\d", str(runner)), (
        f"{runner!r} is not a pinned GitHub-hosted image label"
    )


def test_the_python_version_is_pinned():
    """Two runs on two interpreters are two measurements, not one series."""
    steps = _steps_text()
    assert re.search(r"uv python install \d+\.\d+", steps), (
        "the interpreter is not pinned, so a latency change and an interpreter change are"
        " indistinguishable in the record"
    )
    assert "${{ matrix." not in steps


# --- both backends, both enforcing --------------------------------------------------------------


def test_both_backends_run_the_benchmark_unchanged_and_enforce_the_threshold():
    steps = _steps_text()

    for backend in ("sqlite", "postgres"):
        pattern = re.compile(
            rf"\.venv/bin/python {re.escape(BENCHMARK_SCRIPT)} --backend {backend} --enforce\b"
        )
        assert pattern.search(steps), (
            f"the {backend} run does not invoke `{BENCHMARK_SCRIPT} --backend {backend} --enforce`."
            " Without --enforce the script prints `passed: false` and exits 0, so the build stays"
            " green while the criterion is violated."
        )


def test_neither_backend_can_swallow_the_exit_code():
    job = _job()
    for step in job["steps"]:
        command = step.get("run", "")
        if BENCHMARK_SCRIPT not in command:
            continue
        label = step.get("name", "<unnamed>")
        assert step.get("continue-on-error") is not True, (
            f"step {label!r} is continue-on-error, so an over-threshold P95 leaves the build green"
        )
        assert not re.search(r"\|\|\s*true", command), (
            f"step {label!r} swallows the benchmark exit code with `|| true`"
        )


def test_the_workflow_does_not_relax_the_benchmark_contract():
    """The threshold, corpus floor and protocol live in the script. CI may not restate them."""
    text = _text(PERFORMANCE_WORKFLOW)
    for forbidden in (
        "--threshold",
        "--observations",
        "--clusters",
        "--iterations",
        "--warmup",
        "REQUIRED_OBSERVATIONS",
        "THRESHOLD_P95_MS",
    ):
        assert forbidden not in text, (
            f"the workflow passes or sets {forbidden}, which would let CI measure a corpus or a"
            " threshold other than the one SC-001 names"
        )


def test_dependencies_are_installed_from_the_committed_lockfile():
    steps = _steps_text()
    assert "uv sync --locked" in steps, (
        "without --locked, uv re-resolves from the version ranges and the number describes a"
        " dependency set no checkout reproduces"
    )
    assert "uv pip install -e" not in steps


# --- what may never reach the runner, or the log ------------------------------------------------


def test_postgres_is_reached_only_through_the_test_dsn_variable():
    job = _job()
    env = job.get("env", {})
    assert "IGNIS_TEST_POSTGRES_DSN" in env, (
        "the PostgreSQL benchmark reads IGNIS_TEST_POSTGRES_DSN and refuses to run without it"
    )


def test_there_is_no_database_url_fallback():
    """DATABASE_URL points at a configured corpus. The benchmark seeds 10,000 synthetic rows."""
    assert "DATABASE_URL" not in _text(PERFORMANCE_WORKFLOW), (
        "the workflow mentions DATABASE_URL; a fallback onto it would seed a real database"
    )


def test_the_database_is_a_throwaway_service_on_the_approved_image_family():
    services = _job()["services"]
    assert "postgres" in services, (
        "no service container, so either nothing runs the PostgreSQL side or it reaches a database"
        " that outlives the job"
    )
    image = services["postgres"]["image"]
    assert image == "timescale/timescaledb-ha:pg16", (
        f"the service runs {image!r}; the repository's CI contract is timescale/timescaledb-ha:pg16"
        " and a benchmark on a different engine measures a different planner"
    )
    assert "options" in services["postgres"], (
        "no health check, so the benchmark can start against a database still coming up and"
        " publish the wait as latency"
    )


def test_the_workflow_needs_no_repository_secrets():
    """Nothing here is private. A workflow that reads secrets can leak them; this one cannot."""
    text = _text(PERFORMANCE_WORKFLOW)
    assert "secrets." not in text, (
        "the performance gate reads a repository secret. It seeds its own throwaway database and"
        " needs no credential, so any secret here is a leak surface bought for nothing."
    )


def test_nothing_echoes_a_connection_string_or_a_credential():
    """A public build log is a worse place for a DSN than the workflow file was."""
    steps = _steps_text()
    offenders = [
        line.strip()
        for line in steps.splitlines()
        if re.search(r"\b(echo|printenv|env\b|cat)\b", line)
        and re.search(r"DSN|PASSWORD|SECRET|TOKEN|POSTGRES_|\.env", line, re.I)
    ]
    assert not offenders, "these commands would print a credential into the build log:\n" + "\n".join(
        offenders
    )


def test_uploaded_artifacts_carry_only_the_benchmark_record():
    """The record holds timings, corpus counts and the query. Anything else is an unreviewed path."""
    job = _job()
    uploads = [
        step
        for step in job["steps"]
        if "upload-artifact" in str(step.get("uses", ""))
    ]
    for step in uploads:
        paths = str(step.get("with", {}).get("path", ""))
        for path in paths.split():
            assert path.startswith("benchmark-results/"), (
                f"an artifact step uploads {path!r}, which is outside the directory the benchmark"
                " writes its sanitized JSON record into"
            )


def test_the_workflow_grants_no_more_than_read_access():
    workflow = _load(PERFORMANCE_WORKFLOW)
    permissions = workflow.get("permissions")
    assert permissions == {"contents": "read"}, (
        f"the workflow declares permissions {permissions!r}; it only reads the repository, and a"
        " token wider than that is standing write access attached to a scheduled job"
    )
