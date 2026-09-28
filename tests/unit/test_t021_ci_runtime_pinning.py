"""T021: every workflow runs on a pinned runner and installs uv through one reviewed action commit.

The v0.5.0 release runs printed two warnings. `astral-sh/setup-uv@v3` targets Node.js 20, which
GitHub has deprecated, and `ubuntu-latest` is a label GitHub re-points to a new Ubuntu release on
its own schedule. A moving tag and a moving runner mean the build that passed yesterday is not the
build that runs today, so a red run cannot say whether the code or the floor under it changed.

Compose Init already carried the reviewed configuration: a setup-uv release pinned by full commit
SHA and an explicit uv binary version. These contracts make that the only configuration: CI and
Performance must use the same SHA and version, every job in the four workflows must run on the
pinned runner, and the identities that branch protection and the release depend on -- workflow and
job names, the Python matrix, the enforced benchmarks, the Docker tag rules -- must not move while
the runtime underneath them does.
"""

import re
from collections import Counter
from pathlib import Path

# PyYAML arrives with fastmcp, a required runtime dependency. Parsed, not pattern-matched: `on:`
# and `runs-on:` change meaning with one stray indent, and a comment is not configuration.
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
PERFORMANCE = WORKFLOWS / "performance.yml"
COMPOSE_INIT = WORKFLOWS / "compose-init.yml"
DOCKER_PUBLISH = WORKFLOWS / "docker-publish.yml"

PINNED_RUNNER = "ubuntu-24.04"
SETUP_UV = "astral-sh/setup-uv"
UPLOAD_ARTIFACT = "actions/upload-artifact"
PINNED_UPLOAD_ARTIFACT = (
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
)
# Compose Init holds the reviewed pin; the other workflows are compared with it, not with a copy.
UV_WORKFLOWS = (CI, PERFORMANCE, COMPOSE_INIT)
FULL_SHA = re.compile(r"[0-9a-f]{40}")
ACTION_VERSION = re.compile(r"v\d+(?:\.\d+){0,2}")
UV_BINARY_VERSION = re.compile(r"\d+\.\d+\.\d+")

# Status names branch protection and the release selects. Renaming any of them detaches a rule.
NAMES = {
    CI: ("CI", {"secrets": "Secret scan", "test": "Test & Lint (Python ${{ matrix.python-version }})"}),
    PERFORMANCE: ("Performance", {"sc001-read-path-p95": "SC-001 get_top_clusters P95"}),
    COMPOSE_INIT: ("Compose Init", {"compose-fresh-init": "Fresh Compose database init"}),
    DOCKER_PUBLISH: ("Docker Publish to GHCR", {"build-and-push": "Build & Push Docker Image"}),
}
PYTHON_MATRIX = ["3.11", "3.12", "3.13", "3.14"]
POSTGRES_SERVICE_IMAGE = "timescale/timescaledb-ha:pg16"
BENCHMARK = "scripts/t021_read_path_benchmark.py"
DOCKER_TAG_RULES = (
    "type=semver,pattern={{version}}",
    "type=semver,pattern={{major}}.{{minor}}",
)
# Plan 009 replaced the hand-written `type=raw,value=latest,enable=...` filter, which only knew
# three prerelease spellings, with metadata-action's own stable-only rule.
DOCKER_LATEST_FLAVOR = "latest=auto"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    """The `on:` block. PyYAML follows YAML 1.1, where a bare `on` key parses as the boolean True."""
    for key in ("on", True):
        if key in workflow:
            return workflow[key]
    raise AssertionError("the workflow declares no triggers at all")


def _jobs(path: Path) -> dict:
    return _load(path)["jobs"]


def _setup_uv_steps(path: Path) -> list:
    return [
        step
        for job in _jobs(path).values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith(f"{SETUP_UV}@")
    ]


def _setup_uv_lines(path: Path) -> list:
    """The raw `uses:` lines, because the release comment beside the SHA is lost in parsing."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(rf"\s*(-\s+)?uses:\s*{re.escape(SETUP_UV)}@", line)
    ]


def _upload_artifact_steps(path: Path) -> list:
    return [
        step
        for job in _jobs(path).values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith(f"{UPLOAD_ARTIFACT}@")
    ]


def _upload_artifact_lines(path: Path) -> list:
    """The raw `uses:` lines, because the release comment beside the SHA is lost in parsing."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(rf"\s*(-\s+)?uses:\s*{re.escape(UPLOAD_ARTIFACT)}@", line)
    ]


def _canonical_setup_uv() -> dict:
    steps = _setup_uv_steps(COMPOSE_INIT)
    assert len(steps) == 1, f"Compose Init must hold exactly one setup-uv step; found {len(steps)}"
    return steps[0]


def _workflow_paths(root: Path) -> list[Path]:
    return sorted((*root.glob("*.yml"), *root.glob("*.yaml")), key=lambda path: path.name)


def _uses_actions(node) -> list[str]:
    if isinstance(node, dict):
        direct = [value for key, value in node.items() if key == "uses" and isinstance(value, str)]
        return direct + [action for value in node.values() for action in _uses_actions(value)]
    if isinstance(node, list):
        return [action for value in node for action in _uses_actions(value)]
    return []


def _source_occurrences(path: Path, action: str) -> list[tuple[int, str]]:
    """Find actual source occurrences and the comment that follows each action reference."""
    occurrences = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        action_at = line.find(action)
        if action_at < 0:
            continue
        comment_at = line.find("#")
        if 0 <= comment_at < action_at:
            continue
        comment = "" if comment_at < 0 else line[comment_at + 1 :].strip()
        occurrences.append((line_number, comment))
    return occurrences


def _workflow_action_policy_offenders(paths) -> list[str]:
    offenders = []
    for path in paths:
        external_actions = [
            action for action in _uses_actions(_load(path)) if not action.startswith("./")
        ]
        for action, expected_count in Counter(external_actions).items():
            occurrences = _source_occurrences(path, action)
            line_number = occurrences[0][0] if occurrences else "?"
            ref = action.rsplit("@", 1)[-1] if "@" in action else ""
            comments = [comment for _, comment in occurrences[:expected_count]]
            if (
                not FULL_SHA.fullmatch(ref)
                or len(occurrences) < expected_count
                or any(not ACTION_VERSION.fullmatch(comment) for comment in comments)
            ):
                offenders.append(f"{path.name}:{line_number}: {action}")
    return offenders


# --- runners -------------------------------------------------------------------------------------


def test_every_workflow_action_is_pinned_to_a_reviewable_commit():
    offenders = _workflow_action_policy_offenders(_workflow_paths(WORKFLOWS))
    assert offenders == [], (
        "every external action must use a full commit SHA with its reviewed release comment: "
        f"{offenders}"
    )


def test_action_contract_parses_every_valid_yaml_uses_shape(tmp_path):
    workflow = tmp_path / "shapes.yml"
    workflow.write_text(
        """name: Shapes
jobs:
  scan:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7<TRAILING>
      - {uses: astral-sh/setup-uv@v10}
      - "uses": "docker/login-action@v4"
""".replace("<TRAILING>", "   "),
        encoding="utf-8",
    )
    offenders = _workflow_action_policy_offenders((workflow,))
    assert {offender.split(": ", 1)[1] for offender in offenders} == {
        "actions/checkout@v7",
        "astral-sh/setup-uv@v10",
        "docker/login-action@v4",
    }


def test_action_contract_discovers_both_workflow_extensions(tmp_path):
    (tmp_path / "first.yml").write_text("name: First\n", encoding="utf-8")
    (tmp_path / "second.yaml").write_text("name: Second\n", encoding="utf-8")
    assert [path.name for path in _workflow_paths(tmp_path)] == ["first.yml", "second.yaml"]


def test_every_job_in_the_four_workflows_runs_on_the_pinned_runner():
    """`ubuntu-latest` moves to a new Ubuntu release on GitHub's schedule, not this repository's."""
    offenders = {
        f"{path.name}:{job_id}": job.get("runs-on")
        for path in NAMES
        for job_id, job in _jobs(path).items()
        if job.get("runs-on") != PINNED_RUNNER
    }
    assert offenders == {}, f"these jobs do not run on {PINNED_RUNNER}: {offenders}"


def test_the_named_gates_each_run_on_the_pinned_runner():
    runners = {
        "Secret scan": _jobs(CI)["secrets"]["runs-on"],
        "Python test matrix": _jobs(CI)["test"]["runs-on"],
        "Performance": _jobs(PERFORMANCE)["sc001-read-path-p95"]["runs-on"],
        "Compose Init": _jobs(COMPOSE_INIT)["compose-fresh-init"]["runs-on"],
        "Docker Publish": _jobs(DOCKER_PUBLISH)["build-and-push"]["runs-on"],
    }
    assert runners == dict.fromkeys(runners, PINNED_RUNNER), runners


def test_no_workflow_job_uses_the_moving_runner_label():
    moving = [
        f"{path.name}:{job_id}"
        for path in NAMES
        for job_id, job in _jobs(path).items()
        if "latest" in str(job.get("runs-on", ""))
    ]
    assert moving == [], f"these jobs run on a moving runner label: {moving}"


# --- setup-uv ------------------------------------------------------------------------------------


def test_the_canonical_setup_uv_pin_is_an_exact_commit_and_an_explicit_uv_version():
    step = _canonical_setup_uv()
    ref = step["uses"].split("@", 1)[1]
    assert FULL_SHA.fullmatch(ref), f"Compose Init pins setup-uv to {ref!r}, not a 40-character SHA"
    version = str((step.get("with") or {}).get("version", ""))
    assert UV_BINARY_VERSION.fullmatch(version), (
        f"Compose Init installs uv {version!r}, not an explicit binary version"
    )


def test_every_setup_uv_use_matches_the_compose_init_pin():
    canonical = _canonical_setup_uv()
    canonical_version = str(canonical["with"]["version"])
    for path in UV_WORKFLOWS:
        steps = _setup_uv_steps(path)
        assert steps, f"{path.name} installs uv without setup-uv, so it escapes this contract"
        for step in steps:
            assert step["uses"] == canonical["uses"], (
                f"{path.name} uses {step['uses']!r}; the reviewed pin is {canonical['uses']!r}."
                " A tag such as @v3 targets deprecated Node.js 20 and moves without review."
            )
            version = str((step.get("with") or {}).get("version", ""))
            assert version == canonical_version, (
                f"{path.name} installs uv {version!r}; the reviewed version is {canonical_version!r}."
                " `latest` changes the resolver under the lockfile without a commit."
            )


def test_every_setup_uv_line_carries_the_same_release_comment():
    lines = {path.name: _setup_uv_lines(path) for path in UV_WORKFLOWS}
    distinct = {line for found in lines.values() for line in found}
    assert len(distinct) == 1, f"setup-uv lines differ across workflows: {lines}"
    assert re.search(r"# v\d+\.\d+\.\d+$", distinct.pop()), (
        "the pinned SHA carries no release comment, so a reviewer cannot tell which release it is"
    )


def test_no_movable_setup_uv_reference_remains():
    movable = [
        f"{path.name}: @{step['uses'].split('@', 1)[1]}"
        for path in UV_WORKFLOWS
        for step in _setup_uv_steps(path)
        if re.fullmatch(r"v\d+(\.\d+)*|main|master|latest", step["uses"].split("@", 1)[1])
    ]
    assert movable == [], f"these setup-uv references move without review: {movable}"


def test_no_workflow_installs_the_latest_uv_binary():
    latest = [
        path.name
        for path in UV_WORKFLOWS
        for step in _setup_uv_steps(path)
        if str((step.get("with") or {}).get("version", "latest")) == "latest"
    ]
    assert latest == [], f"these workflows install `latest` uv instead of a reviewed version: {latest}"


# --- upload-artifact -----------------------------------------------------------------------------


def test_upload_artifact_uses_the_reviewed_node24_release_commit():
    steps = _upload_artifact_steps(PERFORMANCE)
    assert len(steps) == 1, f"Performance must hold exactly one upload-artifact step; found {len(steps)}"
    assert steps[0]["uses"] == PINNED_UPLOAD_ARTIFACT, (
        f"Performance uses {steps[0]['uses']!r}; the reviewed Node.js 24 release is "
        f"{PINNED_UPLOAD_ARTIFACT!r}"
    )


def test_upload_artifact_pin_carries_its_release_comment():
    lines = _upload_artifact_lines(PERFORMANCE)
    assert lines == [f"uses: {PINNED_UPLOAD_ARTIFACT} # v7.0.1"], (
        "the upload-artifact SHA must carry its reviewed release beside it"
    )


def test_upload_artifact_keeps_the_benchmark_record_contract():
    step = _upload_artifact_steps(PERFORMANCE)[0]
    assert step.get("if") == "${{ !cancelled() }}"
    assert step.get("with") == {
        "name": "sc001-benchmark-${{ github.run_id }}",
        "path": "benchmark-results/",
        "retention-days": 90,
        "if-no-files-found": "warn",
    }


# --- identities that must not move with the runtime ----------------------------------------------


def test_workflow_and_job_names_are_unchanged():
    for path, (workflow_name, jobs) in NAMES.items():
        workflow = _load(path)
        assert workflow.get("name") == workflow_name, f"{path.name} was renamed"
        found = {job_id: job.get("name") for job_id, job in workflow["jobs"].items()}
        assert found == jobs, f"{path.name} jobs changed: {found}"


def test_the_ci_python_matrix_is_exactly_the_supported_range():
    matrix = _jobs(CI)["test"]["strategy"]["matrix"]
    assert matrix == {"python-version": PYTHON_MATRIX}, matrix


def test_the_postgres_services_keep_their_image():
    for path, job_id in ((CI, "test"), (PERFORMANCE, "sc001-read-path-p95")):
        image = _jobs(path)[job_id]["services"]["postgres"]["image"]
        assert image == POSTGRES_SERVICE_IMAGE, f"{path.name} runs PostgreSQL on {image!r}"


def test_performance_still_enforces_both_benchmarks():
    commands = "\n".join(
        step.get("run", "") for step in _jobs(PERFORMANCE)["sc001-read-path-p95"]["steps"]
    )
    for backend in ("sqlite", "postgres"):
        assert f"{BENCHMARK} --backend {backend} --enforce" in commands, (
            f"the {backend} benchmark no longer runs with --enforce"
        )


def test_docker_publish_keeps_its_trigger_and_tag_rules():
    triggers = _triggers(_load(DOCKER_PUBLISH))
    assert triggers["push"]["tags"] == ["v*"], triggers["push"]
    meta = next(
        step
        for step in _jobs(DOCKER_PUBLISH)["build-and-push"]["steps"]
        if str(step.get("uses", "")).startswith("docker/metadata-action@")
    )
    rules = [line.strip() for line in meta["with"]["tags"].splitlines() if line.strip()]
    for rule in DOCKER_TAG_RULES:
        assert rule in rules, f"Docker Publish lost the tag rule {rule!r}; found {rules}"
    flavor = [line.strip() for line in str(meta["with"].get("flavor", "")).splitlines() if line.strip()]
    assert DOCKER_LATEST_FLAVOR in flavor, f"Docker Publish lost stable-only latest; flavor is {flavor}"
