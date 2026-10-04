"""Contracts for what the public release says about itself, checked against what it is.

Plan 009 makes two distribution paths public: a tagged source checkout bootstrapped with one
command, and an OCI image on GHCR. Before it, the tracked surfaces disagreed with the runtime and
with each other: current guidance claimed 39 or 45 MCP tools while the server exposed 47, install
guidance stopped at migration `023` while `024` shipped, and `server.json` advertised a PyPI
package that was never published while the image contract declared an MCP stdio server.

Each of those was a sentence or a setting somebody typed. These contracts read the authority each
claim depends on -- the running MCP catalog, the migration chain on disk, the committed manifests --
and fail when a governed current-state surface drifts from it. Historical records are deliberately
outside the governed set: a dated backlog entry that measured 39 tools was true on its date, and
rewriting it would erase provenance to make a text search look clean.

None of this proves that anything is publicly reachable. That is decided by
`scripts/public_release_acceptance.py` against public bytes, never by reading this repository.
"""

import asyncio
import json
import re
import tomllib
from pathlib import Path

import pytest

# PyYAML arrives with fastmcp, a required runtime dependency. Parsed, not pattern-matched: a
# comment is not configuration, and indentation changes what a key means.
import yaml

REPO = Path(__file__).resolve().parents[2]

DOCKERFILE = REPO / "Dockerfile"
SERVER_JSON = REPO / "server.json"
DOCKER_PUBLISH = REPO / ".github" / "workflows" / "docker-publish.yml"
BACKLOG = REPO / "BACKLOG.md"

MCP_SERVER_MODULE = "ignis.interfaces.mcp.server"
IMAGE_REPOSITORY = "ghcr.io/fioenix/fn-ignis"
SOURCE_REPOSITORY_URL = "https://github.com/fioenix/fn-ignis"
SOURCE_LABEL = "org.opencontainers.image.source"
MCP_NAME_LABEL = "io.modelcontextprotocol.server.name"

FULL_SHA = re.compile(r"[0-9a-f]{40}")
RELEASE_COMMENT = re.compile(r"#\s*v\d+\.\d+\.\d+\s*$")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _runtime_tool_count() -> int:
    """The catalog a client actually discovers, not a number any document states."""
    from ignis.interfaces.mcp.server import mcp

    return len(asyncio.run(mcp.list_tools()))


def _newest_migration() -> Path:
    migrations = sorted((REPO / "sql").glob("[0-9][0-9][0-9]_*.sql"))
    assert migrations, "sql/ holds no numbered migrations; the chain endpoint cannot be read"
    return migrations[-1]


# --------------------------------------------------------------------------------------------
# Governed current-state surfaces
# --------------------------------------------------------------------------------------------


def _whole(path: Path) -> str:
    return _read(path)


def _backlog_banner(path: Path) -> str:
    """The version banner: everything before the first horizontal rule."""
    return _read(path).split("\n---", 1)[0]


def _backlog_current_accomplishments(path: Path) -> str:
    """The section that describes the system as it stands, not the dated history around it."""
    text = _read(path)
    start = text.index("## 🚀 1.")
    return text[start: text.index("\n## ", start + 1)]


def _backlog_unreleased_status(path: Path) -> str:
    """Only the current branch's runtime claim, not its explicit v0.7.0 comparison."""
    section = _read(path).split("## Spec 011 — trạng thái nhánh phát triển, chưa phát hành", 1)[1]
    return section.split("\n---", 1)[0].split("; các con số", 1)[0]


# (relative path, section reader). Only these surfaces describe the current release; anything
# else in the repository may legitimately carry a dated measurement. A surface is listed by the
# section that makes the current claim so that history elsewhere in the same file stays valid.
GOVERNED_TOOL_COUNT_SURFACES = (
    ("AGENTS.md", _whole),
    ("CLAUDE.md", _whole),
    (".github/workflows/ci.yml", _whole),
    ("src/ignis/interfaces/cli/setup_bundle.py", _whole),
    ("README.md", _whole),
    ("README.vi.md", _whole),
    ("docs/USER_GUIDE.md", _whole),
    ("docs/USER_GUIDE.vi.md", _whole),
    ("BACKLOG.md", _backlog_unreleased_status),
)

# A number in front of the catalog noun, in either language the governed surfaces are written in:
# "47 tools", "39-tool", "39 MCP tools", "45 FastMCP Tools", "45 Handlers & Tools", and the
# Vietnamese catalog noun used by the regional guides.
# Two or three digits only: "two new MCP tools" or "3 tools for X" describe a subset, not the
# catalog.
TOOL_COUNT_CLAIM = re.compile(
    r"\b(\d{2,3})[\s-]+(?:FastMCP\s+|MCP\s+)?(?:Handlers\s*&\s*Tools|tools?\b|công cụ)",
    re.IGNORECASE,
)

# Guides that tell an operator how far the fresh-init chain is verified and which migrations an
# existing database must apply.
MIGRATION_GUIDES = ("README.md", "README.vi.md", "docs/USER_GUIDE.md", "docs/USER_GUIDE.vi.md")

# Public install surfaces that must not offer a package index install while PyPI is deferred.
PUBLIC_INSTALL_SURFACES = MIGRATION_GUIDES + ("server.json",)
PYPI_AVAILABILITY_CLAIM = re.compile(
    r"pip install\s+(?:-U\s+|--upgrade\s+)?fn-ignis\b|uvx\s+fn-ignis\b|pypi\.org/project/fn-ignis",
    re.IGNORECASE,
)


# A numbered catalog-category heading, "### 1. Research Mission Orchestration (10 Tools)", counts a
# subset. It is not a catalog claim on its own; the categories together must add up to the catalog.
CATEGORY_HEADING = re.compile(r"^#{3,}\s+\d+\.\s.*\((\d+)\s+Tools\)\s*$", re.MULTILINE)


def tool_count_offenders(expected: int, surfaces=GOVERNED_TOOL_COUNT_SURFACES) -> list[str]:
    offenders = []
    for relative, reader in surfaces:
        text = reader(REPO / relative)
        categories = [int(count) for count in CATEGORY_HEADING.findall(text)]
        if categories and sum(categories) != expected:
            offenders.append(
                f"{relative} ({reader.__name__}): catalog categories add up to {sum(categories)}"
            )
        for match in TOOL_COUNT_CLAIM.finditer(CATEGORY_HEADING.sub("", text)):
            if int(match.group(1)) != expected:
                offenders.append(f"{relative} ({reader.__name__}): {match.group(0)!r}")
    return offenders


def test_every_governed_tool_count_claim_matches_the_runtime_catalog():
    expected = _runtime_tool_count()
    offenders = tool_count_offenders(expected)
    assert not offenders, (
        f"The MCP server exposes {expected} tools, but these current-state surfaces claim a "
        "different catalog size:\n" + "\n".join(offenders)
    )


def migration_endpoint_offenders(newest: Path, guides=MIGRATION_GUIDES) -> list[str]:
    offenders = []
    for relative in guides:
        text = _read(REPO / relative)
        if f"sql/{newest.name}" not in text:
            offenders.append(f"{relative}: upgrade guidance never names sql/{newest.name}")
    return offenders


def test_install_and_upgrade_guidance_reaches_the_newest_migration():
    offenders = migration_endpoint_offenders(_newest_migration())
    assert not offenders, (
        "Install guidance must name the end of the packaged migration chain, and an existing "
        "database must be told to apply its newest file:\n" + "\n".join(offenders)
    )


def pypi_claim_offenders(surfaces=PUBLIC_INSTALL_SURFACES) -> list[str]:
    offenders = [
        f"{relative}: {match.group(0)!r}"
        for relative in surfaces
        for match in PYPI_AVAILABILITY_CLAIM.finditer(_read(REPO / relative))
    ]
    manifest = json.loads(_read(SERVER_JSON))
    offenders.extend(
        f"server.json: package {package.get('identifier')!r} declares registryType pypi"
        for package in manifest.get("packages", [])
        if package.get("registryType") == "pypi"
    )
    return offenders


def test_no_public_surface_claims_a_pypi_package():
    """PyPI is deferred; a manifest naming it points clients at nothing."""
    offenders = pypi_claim_offenders()
    assert not offenders, (
        "PyPI publication is deferred, yet these surfaces offer it:\n" + "\n".join(offenders)
    )


# --------------------------------------------------------------------------------------------
# Release version carriers
# --------------------------------------------------------------------------------------------


def _oci_package(manifest: dict) -> dict:
    packages = [p for p in manifest.get("packages", []) if p.get("registryType") == "oci"]
    assert len(packages) == 1, (
        f"server.json must declare exactly one OCI package, found {len(packages)}: "
        f"{[p.get('registryType') for p in manifest.get('packages', [])]}"
    )
    return packages[0]


def release_version_carriers() -> dict[str, str | None]:
    """Every place the release version is written, read with the grammar of its own file."""
    manifest = json.loads(_read(SERVER_JSON))
    oci = [p for p in manifest.get("packages", []) if p.get("registryType") == "oci"]
    identifier = oci[0].get("identifier", "") if len(oci) == 1 else ""
    image_tag = identifier.rsplit(":", 1)[1] if ":" in identifier.rsplit("/", 1)[-1] else None

    citation = yaml.safe_load(_read(REPO / "CITATION.cff"))
    openclaw_config = yaml.safe_load(_read(REPO / ".openclaw" / "config.yaml"))
    banner = re.search(r"\*\*Phiên bản:\*\*\s*`v(\d+\.\d+\.\d+)`", _backlog_banner(BACKLOG))
    lock = tomllib.loads(_read(REPO / "uv.lock"))
    locked = [p["version"] for p in lock["package"] if p["name"] == "fn-ignis"]

    return {
        "pyproject.toml": tomllib.loads(_read(REPO / "pyproject.toml"))["project"]["version"],
        "openclaw.json": json.loads(_read(REPO / "openclaw.json")).get("version"),
        "server.json version": manifest.get("version"),
        "server.json package version": oci[0].get("version") if len(oci) == 1 else None,
        "server.json OCI identifier tag": image_tag,
        "CITATION.cff": str(citation.get("version")),
        ".openclaw/config.yaml": str(openclaw_config.get("version")),
        "BACKLOG.md banner": banner.group(1) if banner else None,
        "uv.lock": locked[0] if len(locked) == 1 else None,
    }


def test_every_release_version_carrier_agrees():
    carriers = release_version_carriers()
    declared = carriers["pyproject.toml"]
    disagreeing = {name: value for name, value in carriers.items() if value != declared}
    assert not disagreeing, (
        f"pyproject.toml declares {declared}; these release carriers disagree: {disagreeing}"
    )


# The release this branch prepares and the date of the release before it. Both move with
# the next version bump, in the same commit as the carriers themselves.
RELEASE_CANDIDATE = "0.7.0"
PREVIOUS_RELEASE_DATE = "2026-09-28"


def test_every_carrier_names_the_release_candidate():
    """One MINOR increment, written everywhere at once -- the lock included."""
    carriers = release_version_carriers()
    stale = {name: value for name, value in carriers.items() if value != RELEASE_CANDIDATE}
    assert not stale, f"these release carriers do not read {RELEASE_CANDIDATE}: {stale}"


def test_the_citation_release_date_moves_with_the_version():
    released = str(yaml.safe_load(_read(REPO / "CITATION.cff")).get("date-released"))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", released), released
    assert released > PREVIOUS_RELEASE_DATE, (
        f"CITATION.cff still dates the release {released}, the previous release's date or earlier"
    )


# --------------------------------------------------------------------------------------------
# Image role: the direct image is the request-driven MCP server
# --------------------------------------------------------------------------------------------


def _dockerfile_instructions(name: str) -> list[str]:
    """Every value of one Dockerfile instruction in the final stage, continuation lines joined."""
    text = re.sub(r"\\\n\s*", " ", _read(DOCKERFILE))
    final_stage = re.split(r"(?im)^FROM\s", text)[-1]
    return [
        match.group(1).strip()
        for match in re.finditer(rf"(?im)^{name}\s+(.+)$", final_stage)
    ]


def _dockerfile_cmd() -> list[str]:
    commands = _dockerfile_instructions("CMD")
    assert commands, "the Dockerfile's final stage declares no CMD"
    return json.loads(commands[-1])


def _dockerfile_labels() -> dict[str, str]:
    labels = {}
    for value in _dockerfile_instructions("LABEL"):
        for key, raw in re.findall(r'([\w.\-/]+)=("[^"]*"|\S+)', value):
            labels[key] = raw.strip('"')
    return labels


def test_the_image_defaults_to_the_mcp_stdio_server():
    """server.json declares an OCI stdio package with no command override, so the default must speak MCP."""
    assert _dockerfile_cmd() == ["python", "-m", MCP_SERVER_MODULE], (
        f"the image's default command is {_dockerfile_cmd()}; a client following server.json "
        "would receive that process instead of the MCP server"
    )


def test_the_image_carries_its_source_and_mcp_ownership_labels():
    manifest = json.loads(_read(SERVER_JSON))
    labels = _dockerfile_labels()
    assert labels.get(SOURCE_LABEL) == SOURCE_REPOSITORY_URL, (
        f"the image does not link to its source repository: {labels}"
    )
    assert labels.get(MCP_NAME_LABEL) == manifest["name"], (
        f"{MCP_NAME_LABEL} is {labels.get(MCP_NAME_LABEL)!r}; the MCP Registry binds ownership "
        f"only when it equals server.json's name {manifest['name']!r}"
    )


# --------------------------------------------------------------------------------------------
# server.json advertises the OCI package that actually exists
# --------------------------------------------------------------------------------------------


def test_server_json_advertises_the_versioned_oci_stdio_package():
    manifest = json.loads(_read(SERVER_JSON))
    package = _oci_package(manifest)
    assert package["identifier"] == f"{IMAGE_REPOSITORY}:{manifest['version']}", (
        f"the OCI identifier {package['identifier']!r} is not the versioned public image"
    )
    assert package.get("version") == manifest["version"], (
        "server.json carries the release version twice; the package version drifted"
    )
    assert package.get("transport") == {"type": "stdio"}, package.get("transport")


def test_server_json_marks_the_sqlite_defaulted_database_url_optional():
    """The runtime falls back to SQLite, so demanding DATABASE_URL misstates what a client needs."""
    package = _oci_package(json.loads(_read(SERVER_JSON)))
    variables = {v["name"]: v for v in package.get("environmentVariables", [])}
    assert "DATABASE_URL" in variables, "server.json no longer documents DATABASE_URL at all"
    assert variables["DATABASE_URL"].get("isRequired") is False, variables["DATABASE_URL"]


def test_server_json_says_the_default_database_is_ephemeral_sqlite():
    """Optional is only honest if the client learns what it gets without the variable."""
    package = _oci_package(json.loads(_read(SERVER_JSON)))
    variables = {v["name"]: v for v in package.get("environmentVariables", [])}
    description = variables["DATABASE_URL"].get("description", "").lower()
    assert "sqlite" in description and "ephemeral" in description, description


# --------------------------------------------------------------------------------------------
# The tag-driven publish workflow
# --------------------------------------------------------------------------------------------


def _publish_workflow() -> dict:
    return yaml.safe_load(_read(DOCKER_PUBLISH))


def _publish_steps() -> list[dict]:
    return _publish_workflow()["jobs"]["build-and-push"]["steps"]


def _step_using(action: str) -> dict:
    matching = [s for s in _publish_steps() if str(s.get("uses", "")).startswith(f"{action}@")]
    assert len(matching) == 1, f"expected one {action} step, found {len(matching)}"
    return matching[0]


def _uses_lines() -> list[str]:
    return [line.strip() for line in _read(DOCKER_PUBLISH).splitlines() if "uses:" in line]


def test_every_external_action_is_pinned_to_a_full_commit_with_its_release():
    """A moving tag lets an upstream retag change what the release pipeline runs, with no diff here."""
    offenders = []
    for line in _uses_lines():
        reference = line.split("uses:", 1)[1].split("#", 1)[0].strip()
        if reference.startswith("./"):
            continue
        _, _, ref = reference.partition("@")
        if not FULL_SHA.fullmatch(ref) or not RELEASE_COMMENT.search(line):
            offenders.append(line)
    assert _uses_lines(), "the publish workflow uses no actions; the contract has nothing to read"
    assert not offenders, (
        "Every external action in docker-publish.yml must be a full commit SHA followed by its "
        "release comment:\n" + "\n".join(offenders)
    )


def _semver_gate_index() -> int:
    for index, step in enumerate(_publish_steps()):
        if "SemVer" in str(step.get("name", "")):
            return index
    raise AssertionError("the publish workflow has no step that validates the tag as SemVer")


def test_a_semver_gate_runs_before_anything_is_pushed():
    gate = _semver_gate_index()
    for action in ("docker/login-action", "docker/build-push-action"):
        position = _publish_steps().index(_step_using(action))
        assert gate < position, f"the SemVer gate runs after {action}; a bad tag could already push"


# Refs the gate must accept or refuse. A prerelease is valid SemVer and may publish its own exact
# tag; metadata-action then withholds `{{major}}.{{minor}}` and `latest` from it.
SEMVER_GATE_CASES = (
    ("tag", "v0.6.0", True),
    ("tag", "v10.20.30", True),
    ("tag", "v1.0.0-rc.1", True),
    ("tag", "v0.6", False),
    ("tag", "0.6.0", False),
    ("tag", "v01.2.3", False),
    ("tag", "v0.6.0.1", False),
    ("tag", "v0.6.0-", False),
    ("tag", "vlatest", False),
    ("branch", "main", False),
)


def test_the_semver_gate_refuses_malformed_tags_and_branches():
    """Executed, not read: the gate's own script decides each ref exactly as the runner would."""
    import subprocess

    step = _publish_steps()[_semver_gate_index()]
    assert step.get("env", {}).get("REF_TYPE") == "${{ github.ref_type }}", step.get("env")
    assert step.get("env", {}).get("REF_NAME") == "${{ github.ref_name }}", step.get("env")
    assert "${{" not in step["run"], (
        "the gate interpolates an expression into its script; read the ref through env instead"
    )
    wrong = []
    for ref_type, ref_name, accepted in SEMVER_GATE_CASES:
        completed = subprocess.run(
            ["bash", "-c", step["run"]],
            env={"PATH": "/usr/bin:/bin", "REF_TYPE": ref_type, "REF_NAME": ref_name},
            capture_output=True,
            text=True,
            check=False,
        )
        if (completed.returncode == 0) != accepted:
            wrong.append(f"{ref_type} {ref_name!r}: exit {completed.returncode}, expected accepted={accepted}")
    assert not wrong, "the SemVer gate misjudged these refs:\n" + "\n".join(wrong)


def _version_match_gate_index() -> int:
    for index, step in enumerate(_publish_steps()):
        if "matches project version" in str(step.get("name", "")).lower():
            return index
    raise AssertionError("the publish workflow has no gate matching the tag to the project version")


def test_the_release_tag_must_match_the_checked_out_project_before_login():
    """A valid but wrong SemVer tag must not publish this checkout under another version."""
    import subprocess

    gate = _version_match_gate_index()
    steps = _publish_steps()
    checkout = steps.index(_step_using("actions/checkout"))
    login = steps.index(_step_using("docker/login-action"))
    assert checkout < gate < login, "the version-match gate must read the checkout before registry login"

    step = steps[gate]
    assert step.get("env", {}).get("REF_NAME") == "${{ github.ref_name }}", step.get("env")
    for ref_name, accepted in ((f"v{RELEASE_CANDIDATE}", True), ("v0.7.1", False)):
        completed = subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=REPO,
            env={"PATH": "/usr/bin:/bin", "REF_NAME": ref_name},
            capture_output=True,
            text=True,
            check=False,
        )
        assert (completed.returncode == 0) == accepted, (
            f"project/tag version gate returned {completed.returncode} for {ref_name}: "
            f"{completed.stdout}{completed.stderr}"
        )


def test_image_tags_come_only_from_stable_semver_rules():
    meta = _step_using("docker/metadata-action")["with"]
    rules = [line.strip() for line in meta["tags"].splitlines() if line.strip()]
    assert rules == ["type=semver,pattern={{version}}", "type=semver,pattern={{major}}.{{minor}}"], (
        f"tag rules must be the two SemVer patterns only; found {rules}"
    )
    flavor = [line.strip() for line in str(meta.get("flavor", "")).splitlines() if line.strip()]
    assert "latest=auto" in flavor, (
        "latest must come from metadata-action's stable-only automatic rule, not a hand-written "
        f"ref filter; flavor is {flavor}"
    )


def test_publish_metadata_carries_source_and_mcp_ownership_labels():
    labels = str(_step_using("docker/metadata-action")["with"].get("labels", ""))
    manifest = json.loads(_read(SERVER_JSON))
    assert f"{SOURCE_LABEL}={SOURCE_REPOSITORY_URL}" in labels, labels
    assert f"{MCP_NAME_LABEL}={manifest['name']}" in labels, labels


def test_publish_grants_only_the_permissions_provenance_needs():
    permissions = _publish_workflow()["jobs"]["build-and-push"]["permissions"]
    assert permissions == {
        "contents": "read",
        "packages": "write",
        "attestations": "write",
        "id-token": "write",
    }, permissions


def test_publish_attests_the_exact_pushed_digest():
    build = _step_using("docker/build-push-action")
    assert build.get("id"), "the build step has no id, so its digest cannot be referenced"
    attest = _step_using("actions/attest")["with"]
    assert attest.get("subject-name") == "${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}", attest
    assert attest.get("subject-digest") == f"${{{{ steps.{build['id']}.outputs.digest }}}}", attest
    assert attest.get("push-to-registry") is True, attest
    steps = _publish_steps()
    assert steps.index(build) < steps.index(_step_using("actions/attest"))


# --------------------------------------------------------------------------------------------
# The release observation model in scripts/public_release_acceptance.py
# --------------------------------------------------------------------------------------------

ACCEPTANCE_SCRIPT = REPO / "scripts" / "public_release_acceptance.py"
MAIN_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _acceptance():
    assert ACCEPTANCE_SCRIPT.is_file(), "scripts/public_release_acceptance.py does not exist"
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    import public_release_acceptance  # noqa: PLC0415

    return public_release_acceptance


def _record(module, name, state=None, **fields):
    state = state or module.SurfaceState.VERIFIED
    defaults = {
        "subject": name,
        "evidence": "fixture",
        "failure_class": None if state == module.SurfaceState.VERIFIED else "behavior_mismatch",
    }
    if state == module.SurfaceState.DEFERRED:
        defaults["failure_class"] = None
    defaults.update(fields)
    return module.SurfaceRecord(name=name, state=state, **defaults)


def _full_policy(module) -> list:
    records = [_record(module, name) for name in module.REQUIRED_SURFACES]
    records += [_record(module, name, module.SurfaceState.DEFERRED) for name in module.DEFERRED_SURFACES]
    return records


def test_an_unknown_surface_name_is_refused():
    """A typo must not create an unchecked replacement for a required surface."""
    module = _acceptance()
    import pytest

    with pytest.raises(ValueError, match="unknown surface"):
        _record(module, "container_anonymous_pul")


def test_a_duplicate_surface_is_refused():
    module = _acceptance()
    import pytest

    records = _full_policy(module) + [_record(module, "source_bootstrap")]
    with pytest.raises(ValueError, match="duplicate"):
        module.build_bundle("0.6.0", MAIN_COMMIT, records)


def test_a_missing_required_surface_record_is_refused():
    """Every required surface appears exactly once; silence is not a pass."""
    module = _acceptance()
    import pytest

    records = [r for r in _full_policy(module) if r.name != "container_digest"]
    with pytest.raises(ValueError, match="container_digest"):
        module.build_bundle("0.6.0", MAIN_COMMIT, records)


def test_a_verified_record_carries_no_failure_class_and_others_must():
    module = _acceptance()
    import pytest

    with pytest.raises(ValueError, match="failure_class"):
        _record(module, "source_bootstrap", module.SurfaceState.VERIFIED, failure_class="network")
    with pytest.raises(ValueError, match="failure_class"):
        _record(module, "source_bootstrap", module.SurfaceState.FAILED, failure_class=None)
    with pytest.raises(ValueError, match="failure_class"):
        _record(module, "source_bootstrap", module.SurfaceState.FAILED, failure_class="bad luck")


def test_the_main_commit_must_be_a_full_lowercase_sha():
    module = _acceptance()
    import pytest

    for commit in ("abc123", MAIN_COMMIT.upper(), MAIN_COMMIT + "0", "g" * 40):
        with pytest.raises(ValueError, match="commit"):
            module.build_bundle("0.6.0", commit, _full_policy(module))
    assert module.build_bundle("0.6.0", MAIN_COMMIT, _full_policy(module)).main_commit == MAIN_COMMIT


def test_the_version_must_be_semver_without_a_prefix():
    module = _acceptance()
    import pytest

    for version in ("v0.6.0", "0.6", "0.6.0.1", ""):
        with pytest.raises(ValueError, match="version"):
            module.build_bundle(version, MAIN_COMMIT, _full_policy(module))


def test_source_acceptance_modes_require_the_verified_main_commit_before_observation(tmp_path, monkeypatch):
    import pytest

    module = _acceptance()
    observed = []
    monkeypatch.setattr(module, "observe_source", lambda **kwargs: observed.append(kwargs))
    for mode in ("source", "all"):
        with pytest.raises(SystemExit) as stopped:
            module.main([mode, "--version", "0.6.0", "--work-root", str(tmp_path)])
        assert stopped.value.code == 2
    assert not observed, "source observation started before the verified main commit was supplied"


def test_release_quickstart_supplies_the_verified_main_commit_to_source_modes():
    quickstart = _read(REPO / "specs/009-public-distribution-v0-6-0/quickstart.md")
    for mode in ("source", "all"):
        command = re.search(
            rf"public_release_acceptance\.py {mode} \\\n(?P<body>(?:.*\n){{1,8}}?)```",
            quickstart,
        )
        assert command, f"quickstart has no {mode} acceptance command"
        assert '--expected-commit "$VERIFIED_MAIN_COMMIT"' in command.group("body"), (
            f"quickstart {mode} acceptance does not bind the public tag to the reviewed main commit"
        )


def test_redaction_removes_url_credentials_tokens_and_ambient_secret_values(monkeypatch):
    module = _acceptance()
    ambient = "ambient-" + "q" * 24
    monkeypatch.setenv("GITHUB_TOKEN", ambient)
    token = "ghp_" + "A" * 36
    text = (
        f"clone https://operator:{token}@github.com/fioenix/fn-ignis.git failed; "
        f"Authorization: Bearer {ambient}; postgresql://postgres:hunter22@127.0.0.1/db"
    )
    redacted = module.redact(text)
    for secret in (token, ambient, "hunter22", "operator:"):
        assert secret not in redacted, f"{secret!r} survived redaction: {redacted}"
    assert "github.com/fioenix/fn-ignis.git" in redacted, "redaction destroyed the non-secret subject"


def test_a_record_redacts_its_subject_and_evidence_on_construction(monkeypatch):
    module = _acceptance()
    ambient = "ambient-" + "z" * 24
    monkeypatch.setenv("DOCKER_REGISTRY_PASSWORD", ambient)
    record = _record(
        module,
        "source_tag_checkout",
        module.SurfaceState.UNREADABLE,
        failure_class="auth",
        subject="https://user:pw12345@github.com/fioenix/fn-ignis.git",
        evidence=f"git said {ambient}",
    )
    assert "pw12345" not in record.subject
    assert ambient not in record.evidence


def test_the_bundle_serializes_to_the_contract_shape():
    module = _acceptance()
    records = _full_policy(module)
    records[0] = _record(module, records[0].name, module.SurfaceState.MISSING, failure_class="missing")
    bundle = module.build_bundle("0.6.0", MAIN_COMMIT, records)
    payload = json.loads(json.dumps(bundle.to_dict()))

    assert set(payload) == {
        "schema_version",
        "version",
        "main_commit",
        "surfaces",
        "verdict",
        "missing",
        "failed",
        "unreadable",
        "deferred",
    }
    assert payload["schema_version"] == 1
    assert payload["verdict"] == "NOT_RELEASED"
    assert payload["missing"] == [records[0].name]
    assert payload["deferred"] == ["pypi_distribution"]
    surface = payload["surfaces"][records[0].name]
    assert set(surface) == {
        "name",
        "required",
        "state",
        "observed_at",
        "subject",
        "evidence",
        "command_exit",
        "failure_class",
    }
    assert surface["required"] is True and surface["state"] == "MISSING"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", surface["observed_at"])


def test_surfaces_a_mode_did_not_observe_are_unreadable_not_absent():
    """A source-only run proves nothing about GHCR, so it can never be RELEASED."""
    module = _acceptance()
    observed = [_record(module, "source_tag_checkout"), _record(module, "source_bootstrap")]
    records = module.complete_with_unobserved(observed)
    bundle = module.build_bundle("0.6.0", None, records)

    assert bundle.verdict == module.Verdict.INDETERMINATE
    assert "container_anonymous_pull" in bundle.unreadable
    assert "source_bootstrap" not in bundle.unreadable
    assert bundle.surfaces["container_anonymous_pull"].failure_class == "not_observed"
    assert bundle.surfaces["pypi_distribution"].state == module.SurfaceState.DEFERRED


# --------------------------------------------------------------------------------------------
# Bounded commands: known absence is not an outage
# --------------------------------------------------------------------------------------------


def test_a_missing_tool_is_unreadable_not_absent():
    module = _acceptance()
    outcome = module.run_bounded(["ignis-no-such-tool-for-release-acceptance"], timeout=5)
    assert outcome.tool_missing and outcome.returncode is None
    assert module.classify_failure(outcome) == (module.SurfaceState.UNREADABLE, "tool_unavailable")


def test_a_command_that_outlives_its_bound_is_stopped_and_unreadable():
    import sys

    module = _acceptance()
    outcome = module.run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert outcome.timed_out and outcome.returncode is None
    assert module.classify_failure(outcome) == (module.SurfaceState.UNREADABLE, "network")


def test_command_output_is_bounded_and_redacted():
    import sys

    module = _acceptance()
    token = "ghp_" + "B" * 36
    outcome = module.run_bounded(
        [sys.executable, "-c", f"print('x' * 200000); import sys; print('{token}', file=sys.stderr)"],
        timeout=30,
    )
    assert outcome.returncode == 0
    assert len(outcome.stdout) <= module.MAX_CAPTURED_CHARS
    assert token not in outcome.stderr


def test_a_known_absence_answer_is_missing():
    module = _acceptance()
    outcome = module.CommandOutcome(returncode=1, stdout="", stderr="release not found")
    assert module.classify_failure(outcome, absent_markers=("release not found",)) == (
        module.SurfaceState.MISSING,
        "missing",
    )


def test_a_forbidden_api_answer_with_empty_stdout_is_unreadable():
    """The contract's own negative control: 403 plus empty stdout is not proof of absence."""
    module = _acceptance()
    outcome = module.CommandOutcome(
        returncode=1, stdout="", stderr="gh: You need at least read:packages scope (HTTP 403)"
    )
    assert module.classify_failure(outcome, absent_markers=("not found",)) == (
        module.SurfaceState.UNREADABLE,
        "auth",
    )


def test_an_unrecognized_failure_is_unreadable_and_says_so():
    module = _acceptance()
    outcome = module.CommandOutcome(returncode=2, stdout="", stderr="something odd")
    assert module.classify_failure(outcome, absent_markers=("not found",)) == (
        module.SurfaceState.UNREADABLE,
        "unclassified",
    )


def test_a_network_failure_is_unreadable():
    module = _acceptance()
    outcome = module.CommandOutcome(
        returncode=128, stdout="", stderr="fatal: unable to access: Could not resolve host: github.com"
    )
    assert module.classify_failure(outcome) == (module.SurfaceState.UNREADABLE, "network")


# --------------------------------------------------------------------------------------------
# Temporary state belongs to the run that created it
# --------------------------------------------------------------------------------------------


def test_each_run_owns_a_unique_root_and_removes_it(tmp_path):
    module = _acceptance()
    with module.TemporaryRoot(parent=tmp_path) as first, module.TemporaryRoot(parent=tmp_path) as second:
        assert first.path != second.path
        assert first.path.parent == tmp_path and first.path.is_dir()
        (first.path / "checkout").mkdir()
    assert not first.path.exists() and not second.path.exists()
    assert tmp_path.is_dir(), "cleanup removed the parent it did not create"


def test_the_root_is_removed_when_the_run_fails(tmp_path):
    module = _acceptance()
    import pytest

    with pytest.raises(RuntimeError, match="boom"):
        with module.TemporaryRoot(parent=tmp_path) as root:
            created = root.path
            raise RuntimeError("boom")
    assert not created.exists()


def test_a_root_whose_ownership_marker_changed_is_not_deleted(tmp_path):
    """Remove only what this run created: a replaced marker means somebody else owns the tree."""
    module = _acceptance()
    root = module.TemporaryRoot(parent=tmp_path)
    root.__enter__()
    root.marker.write_text("someone-else", encoding="utf-8")
    root.__exit__(None, None, None)
    assert root.path.exists()


def test_the_isolated_environment_inherits_no_credentials(monkeypatch, tmp_path):
    module = _acceptance()
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "DATABASE_URL", "IGNIS_ENV_FILE", "DOCKER_AUTH_CONFIG", "VIRTUAL_ENV"):
        monkeypatch.setenv(name, "inherited-" + name.lower())
    env = module.isolated_env(tmp_path / "home", docker_config=tmp_path / "docker")

    assert env["HOME"] == str(tmp_path / "home")
    assert env["DOCKER_CONFIG"] == str(tmp_path / "docker")
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["PATH"]
    leaked = [value for value in env.values() if value.startswith("inherited-")]
    assert not leaked, f"credentials or developer state leaked into the isolated environment: {leaked}"


def test_evidence_json_carries_no_ambient_secret(monkeypatch, tmp_path):
    module = _acceptance()
    ambient = "ambient-" + "w" * 24
    monkeypatch.setenv("GH_TOKEN", ambient)
    records = module.complete_with_unobserved(
        [
            _record(
                module,
                "source_tag_checkout",
                module.SurfaceState.UNREADABLE,
                failure_class="auth",
                evidence=f"token {ambient} refused",
            )
        ]
    )
    output = tmp_path / "evidence.json"
    module.write_evidence(module.build_bundle("0.6.0", None, records), output)
    text = output.read_text(encoding="utf-8")
    assert ambient not in text
    assert json.loads(text)["verdict"] == "INDETERMINATE"


# --------------------------------------------------------------------------------------------
# One MCP smoke conversation for the wheel, the source checkout, and the container
# --------------------------------------------------------------------------------------------

SMOKE_SCRIPT = REPO / "scripts" / "wheel_mcp_smoke.py"

# A minimal stdio server. Each behaviour flag breaks one part of the protocol the smoke must catch.
FAKE_SERVER = r'''
import json, sys, time
mode = sys.argv[1]
tools = int(sys.argv[2]) if len(sys.argv) > 2 else 44
if mode == "banner":
    print("starting worker loop", flush=True)
for raw in sys.stdin:
    message = json.loads(raw)
    if "id" not in message:
        continue
    if mode == "silent":
        time.sleep(60)
    if mode == "garbage":
        print("{not json", flush=True)
        continue
    method = message["method"]
    if method == "initialize":
        result = {"protocolVersion": message["params"]["protocolVersion"], "capabilities": {},
                  "serverInfo": {"name": "fake", "version": "1"}}
    elif method == "tools/list":
        names = ["create_attention_mission", "confirm_market_brief", "submit_mission_claims", "get_mission_claims"]
        names += [f"tool_{i}" for i in range(max(0, tools - len(names)))]
        names = names[:tools]
        if mode == "missing-reset-tool":
            names[0] = "tool_missing"
        if mode == "retained-legacy-tool":
            names[-1] = "trigger_autonomous_discovery"
        result = {"tools": [{"name": name, "inputSchema": {}} for name in names]}
    else:
        failed = mode == "tool-error"
        payload = {"status": "ERROR" if failed else "SUCCESS", "total_configs": 3}
        result = {"isError": failed, "content": [{"type": "text", "text": json.dumps(payload)}]}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
if mode == "linger":
    time.sleep(60)
'''


def _smoke():
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    import wheel_mcp_smoke  # noqa: PLC0415

    assert hasattr(wheel_mcp_smoke, "run_smoke"), (
        "scripts/wheel_mcp_smoke.py cannot be driven with a caller-supplied server command"
    )
    return wheel_mcp_smoke


def _fake(tmp_path, mode, tools=44) -> list[str]:
    import sys

    server = tmp_path / "fake_server.py"
    server.write_text(FAKE_SERVER, encoding="utf-8")
    return [sys.executable, str(server), mode, str(tools)]


def test_a_caller_supplied_command_completes_the_smoke(tmp_path):
    module = _smoke()
    result = module.run_smoke(_fake(tmp_path, "ok"), response_timeout=10, exit_timeout=10)
    assert result.tool_count == module.EXPECTED_TOOL_COUNT
    assert result.runtime_configs == 3


@pytest.mark.parametrize("mode", ["missing-reset-tool", "retained-legacy-tool"])
def test_wheel_smoke_rejects_a_wrong_mission_bound_catalog_even_at_41_tools(tmp_path, mode):
    module = _smoke()
    with pytest.raises(module.SmokeFailure, match="mission-bound catalog mismatch"):
        module.run_smoke(_fake(tmp_path, mode), response_timeout=10, exit_timeout=10)


def test_a_wrong_tool_count_fails_the_smoke(tmp_path):
    module = _smoke()
    import pytest

    with pytest.raises(module.SmokeFailure, match="expected 44 tools, discovered 39"):
        module.run_smoke(_fake(tmp_path, "ok", tools=39), response_timeout=10, exit_timeout=10)


def test_a_failed_tool_call_fails_the_smoke(tmp_path):
    module = _smoke()
    import pytest

    with pytest.raises(module.SmokeFailure, match="get_runtime_config"):
        module.run_smoke(_fake(tmp_path, "tool-error"), response_timeout=10, exit_timeout=10)


def test_malformed_json_fails_the_smoke(tmp_path):
    module = _smoke()
    import pytest

    with pytest.raises(module.SmokeFailure, match="non-MCP"):
        module.run_smoke(_fake(tmp_path, "garbage"), response_timeout=10, exit_timeout=10)


def test_a_process_that_prints_anything_but_json_rpc_fails_the_smoke(tmp_path):
    """A worker started instead of the server logs to stdout; that is a role failure, not noise."""
    module = _smoke()
    import pytest

    with pytest.raises(module.SmokeFailure, match="non-MCP"):
        module.run_smoke(_fake(tmp_path, "banner"), response_timeout=10, exit_timeout=10)


def test_a_silent_server_fails_the_smoke_within_its_bound(tmp_path):
    import time

    module = _smoke()
    import pytest

    started = time.monotonic()
    with pytest.raises(module.SmokeFailure, match="did not answer"):
        module.run_smoke(_fake(tmp_path, "silent"), response_timeout=1, exit_timeout=1)
    assert time.monotonic() - started < 20


def test_a_server_that_ignores_stdin_eof_fails_the_smoke(tmp_path):
    module = _smoke()
    import pytest

    with pytest.raises(module.SmokeFailure, match="stdin closed"):
        module.run_smoke(_fake(tmp_path, "linger"), response_timeout=10, exit_timeout=1)


def test_the_default_command_is_the_local_interpreter_serving_ignis(tmp_path, monkeypatch):
    """The wheel path is unchanged: no command means this interpreter's installed Ignis server."""
    import sys

    module = _smoke()
    assert module.default_server_command() == [sys.executable, "-m", MCP_SERVER_MODULE]

    env_file = tmp_path / "smoke.env"
    env_file.write_text(f"DATABASE_URL=sqlite:///{tmp_path / 'smoke.db'}\nDEFAULT_GEO=VN\n", encoding="utf-8")
    monkeypatch.setenv("IGNIS_ENV_FILE", str(env_file))
    result = module.run_smoke(None, response_timeout=120, exit_timeout=30)
    assert result.tool_count == _runtime_tool_count()


def test_the_wheel_default_still_requires_an_environment_file(monkeypatch):
    module = _smoke()
    import pytest

    monkeypatch.delenv("IGNIS_ENV_FILE", raising=False)
    with pytest.raises(SystemExit, match="IGNIS_ENV_FILE"):
        module.main([])


# --------------------------------------------------------------------------------------------
# Source mode: an exact public tag, bootstrapped under an empty home
# --------------------------------------------------------------------------------------------
#
# The fixture is a real Git repository with a real tag, cloned through a file:// URL, so tag
# resolution and clone behaviour are Git's own. Its bootstrap and server are stand-ins: the real
# bootstrap is covered by tests/integration/test_clean_user_journey.py, and the point here is how
# the observer classifies what it sees.

FAKE_BOOTSTRAP = r'''#!/bin/sh
set -e
cd "$(dirname "$0")/.."
env > bootstrap-env.txt
[ "${FAKE_BOOTSTRAP_FAIL:-}" = "1" ] && { echo "boom" >&2; exit 3; }
mkdir -p .venv/bin
printf '#!/bin/sh\nexec "%s" "%s/fake_server.py" ok "${FAKE_TOOLS:-44}"\n' "$FAKE_PYTHON" "$PWD" > .venv/bin/python
chmod +x .venv/bin/python
printf 'DATABASE_URL=sqlite:///ignis.db\n' > .env
"$FAKE_PYTHON" - <<'PY'
import os, re, sqlite3
from pathlib import Path
db = sqlite3.connect("ignis.db")
skip = os.environ.get("FAKE_SKIP_TABLE", "")
for migration in sorted(Path("sql").glob("*.sql")):
    for table in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", migration.read_text()):
        if table != skip:
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER)")
db.execute("CREATE TABLE IF NOT EXISTS market_lexicons (term TEXT)")
db.execute("INSERT INTO market_lexicons VALUES ('seed')")
db.commit()
PY
printf '{"mcpServers": {"fn-ignis": {"command": "%s/.venv/bin/python", "args": ["-m", "ignis.interfaces.mcp.server"], "env": {"IGNIS_ENV_FILE": "%s/.env"}}}}' "$PWD" "$PWD" > .mcp.json
echo "Installed the exact solution recorded in uv.lock."
'''

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def _git(repo: Path, *args: str) -> str:
    import os
    import subprocess

    env = {**os.environ, **GIT_IDENTITY, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


def _source_fixture(tmp_path: Path, *, extra_files: dict | None = None, omit: tuple = ()) -> dict:
    """A tagged repository plus the reference tree it is supposed to match."""
    repo = tmp_path / "origin"
    files = {
        "scripts/bootstrap.sh": FAKE_BOOTSTRAP,
        "fake_server.py": FAKE_SERVER,
        "sql/001_base.sql": "CREATE TABLE IF NOT EXISTS sources (id TEXT);\n",
        "sql/002_evidence.sql": "CREATE TABLE IF NOT EXISTS mission_probe_outcomes (id TEXT);\n"
        "CREATE TABLE IF NOT EXISTS mission_evidence_qualifications (id TEXT);\n",
        "src/ignis/application/use_cases/get_evidence_qualification_batch.py": "",
        "src/ignis/application/use_cases/submit_evidence_qualifications.py": "",
        "src/ignis/infrastructure/templates/html/mission_report.html": "<html></html>\n",
        "server.json": "{}\n",
        "openclaw.json": "{}\n",
        "hermes_manifest.json": "[]\n",
        ".hermes/tools.json": "[]\n",
        **(extra_files or {}),
    }
    for relative, content in files.items():
        if relative in omit:
            continue
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (repo / "scripts" / "bootstrap.sh").chmod(0o755)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Release fixture")
    _git(repo, "tag", "-a", "v0.6.0", "-m", "Release v0.6.0")
    tagged = _git(repo, "rev-parse", "HEAD")
    (repo / "later.txt").write_text("after the tag\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Move main past the tag")

    reference = tmp_path / "reference"
    for relative, content in files.items():
        path = reference / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return {"url": repo.as_uri(), "tagged": tagged, "main": _git(repo, "rev-parse", "HEAD"), "reference": reference}


def _observe_source(module, fixture, tmp_path, monkeypatch, *, expected=None, version="0.6.0", **env):
    import sys

    monkeypatch.setenv("FAKE_PYTHON", sys.executable)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with module.TemporaryRoot(parent=tmp_path) as root:
        records = module.observe_source(
            repository=fixture["url"],
            version=version,
            expected_commit=expected if expected is not None else fixture["tagged"],
            root=root.path,
            reference=fixture["reference"],
            passthrough_env=("FAKE_PYTHON", *env),
            smoke_timeout=15,
        )
        leaked = (root.path / "checkout" / "bootstrap-env.txt")
        seen_env = leaked.read_text(encoding="utf-8") if leaked.exists() else ""
    return {record.name: record for record in records}, seen_env


def test_a_public_url_carrying_credentials_is_refused_before_any_request():
    module = _acceptance()
    import pytest

    for url in (
        "https://operator:token@github.com/fioenix/fn-ignis.git",
        "https://github.com/fioenix/fn-ignis.git?access_token=abc",
        "http://github.com/fioenix/fn-ignis.git",
        "git@github.com:fioenix/fn-ignis.git",
    ):
        with pytest.raises(ValueError, match="public"):
            module.check_public_url(url)
    module.check_public_url("https://github.com/fioenix/fn-ignis.git")


def test_the_exact_tag_is_cloned_and_matches_the_verified_commit(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch)

    checkout = records["source_tag_checkout"]
    assert checkout.state == module.SurfaceState.VERIFIED, checkout
    assert fixture["tagged"] in checkout.evidence
    assert records["source_bootstrap"].state == module.SurfaceState.VERIFIED, records["source_bootstrap"]
    assert records["source_mcp_runtime"].state == module.SurfaceState.VERIFIED, records["source_mcp_runtime"]


def test_a_tag_on_the_wrong_commit_fails(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    records, marker = _observe_source(module, fixture, tmp_path, monkeypatch, expected=fixture["main"])
    assert records["source_tag_checkout"].state == module.SurfaceState.FAILED
    assert records["source_tag_checkout"].failure_class == "behavior_mismatch"
    assert records["source_bootstrap"].state == module.SurfaceState.UNREADABLE
    assert records["source_mcp_runtime"].state == module.SurfaceState.UNREADABLE
    assert not marker, "A mismatched release tag must not execute its bootstrap"


def test_without_an_expected_commit_the_checkout_is_not_verified(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch, expected="")
    assert records["source_tag_checkout"].state == module.SurfaceState.UNREADABLE
    assert records["source_tag_checkout"].failure_class == "not_observed"


def test_a_missing_tag_is_missing(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch, version="0.7.0")
    assert records["source_tag_checkout"].state == module.SurfaceState.MISSING
    # Nothing was obtained, so nothing downstream can be judged either way.
    assert records["source_bootstrap"].state == module.SurfaceState.UNREADABLE
    assert records["source_mcp_runtime"].state == module.SurfaceState.UNREADABLE


def test_a_repository_that_does_not_exist_is_missing(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    fixture["url"] = (tmp_path / "no-such-repository").as_uri()
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch)
    assert records["source_tag_checkout"].state == module.SurfaceState.MISSING


def test_bootstrap_runs_under_an_isolated_home_with_no_inherited_credentials(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "DATABASE_URL", "IGNIS_ENV_FILE", "VIRTUAL_ENV"):
        monkeypatch.setenv(name, f"inherited-{name.lower()}")
    records, seen = _observe_source(module, fixture, tmp_path, monkeypatch)

    assert records["source_bootstrap"].state == module.SurfaceState.VERIFIED, records["source_bootstrap"]
    home = next(line.split("=", 1)[1] for line in seen.splitlines() if line.startswith("HOME="))
    assert "ignis-release-acceptance-" in home and home.endswith("/home"), home
    assert "inherited-" not in seen, "the bootstrap child saw a developer credential or override"


def test_a_tag_that_ships_developer_state_fails_bootstrap(tmp_path, monkeypatch):
    """A committed .env or .venv would be inherited by every user who clones the tag."""
    module = _acceptance()
    fixture = _source_fixture(tmp_path, extra_files={".env": "DATABASE_URL=postgresql://x@y/z\n"})
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch)
    assert records["source_bootstrap"].state == module.SurfaceState.FAILED
    assert ".env" in records["source_bootstrap"].evidence


def test_a_failing_bootstrap_fails_with_its_output(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch, FAKE_BOOTSTRAP_FAIL="1")
    assert records["source_bootstrap"].state == module.SurfaceState.FAILED
    assert "boom" in records["source_bootstrap"].evidence
    assert records["source_mcp_runtime"].state == module.SurfaceState.UNREADABLE


def test_a_schema_missing_the_newest_migration_fails_bootstrap(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    records, _ = _observe_source(
        module, fixture, tmp_path, monkeypatch, FAKE_SKIP_TABLE="mission_evidence_qualifications"
    )
    assert records["source_bootstrap"].state == module.SurfaceState.FAILED
    assert "mission_evidence_qualifications" in records["source_bootstrap"].evidence


def test_a_tag_missing_a_file_the_release_tree_has_fails(tmp_path, monkeypatch):
    """The local tree passes and the public tag omits a new file: the tag is what users get."""
    module = _acceptance()
    fixture = _source_fixture(tmp_path, omit=("src/ignis/application/use_cases/submit_evidence_qualifications.py",))
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch)
    assert records["source_bootstrap"].state == module.SurfaceState.FAILED
    assert "submit_evidence_qualifications.py" in records["source_bootstrap"].evidence


def test_a_source_server_with_the_wrong_catalog_fails_runtime(tmp_path, monkeypatch):
    module = _acceptance()
    fixture = _source_fixture(tmp_path)
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch, FAKE_TOOLS="39")
    assert records["source_bootstrap"].state == module.SurfaceState.VERIFIED
    assert records["source_mcp_runtime"].state == module.SurfaceState.FAILED
    assert "discovered 39" in records["source_mcp_runtime"].evidence


# --------------------------------------------------------------------------------------------
# Container mode: an anonymous consumer pulls the image and talks MCP to its default process
# --------------------------------------------------------------------------------------------
#
# The registry is a fake speaking the OCI distribution protocol's anonymous-token dance, and
# `docker` is a fake executable, so these run offline. What they pin is the observer's judgment:
# which bytes it demands, which answers it calls missing, failed or unread, and that no credential
# reaches either side.

import hashlib  # noqa: E402

OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
REGISTRY = "https://ghcr.io"
IMAGE_PATH = "fioenix/fn-ignis"
ANONYMOUS_TOKEN = "anonymous-pull-token"


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None):
        self.status = status
        self.body = body
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}

    def chunks(self):
        yield self.body


class FakeRegistry:
    """Anonymous-token GHCR stand-in. Every request is recorded with its headers."""

    def __init__(self, *, labels=None, anonymous=True):
        self.requests: list[tuple[str, dict]] = []
        self.anonymous = anonymous
        self.overrides: dict[str, FakeResponse] = {}
        labels = labels if labels is not None else {
            SOURCE_LABEL: SOURCE_REPOSITORY_URL,
            MCP_NAME_LABEL: json.loads(_read(SERVER_JSON))["name"],
        }
        self.config = json.dumps({"config": {"Labels": labels}, "architecture": "amd64", "os": "linux"}).encode()
        self.layers = [b"layer-one" * 100, b"layer-two" * 50]
        self.image_manifest = json.dumps(
            {
                "mediaType": OCI_MANIFEST,
                "config": {"digest": _digest(self.config), "size": len(self.config)},
                "layers": [{"digest": _digest(layer), "size": len(layer)} for layer in self.layers],
            }
        ).encode()
        attestation = json.dumps({"mediaType": OCI_MANIFEST, "config": {"digest": "sha256:" + "0" * 64}, "layers": []}).encode()
        self.attestation = attestation
        self.index = json.dumps(
            {
                "mediaType": OCI_INDEX,
                "manifests": [
                    {"digest": _digest(self.image_manifest), "mediaType": OCI_MANIFEST,
                     "platform": {"os": "linux", "architecture": "amd64"}},
                    {"digest": _digest(attestation), "mediaType": OCI_MANIFEST,
                     "platform": {"os": "unknown", "architecture": "unknown"}},
                ],
            }
        ).encode()
        self.tags = {tag: self.index for tag in ("0.6.0", "0.6", "latest")}

    @property
    def index_digest(self) -> str:
        return _digest(self.index)

    def __call__(self, url: str, headers: dict) -> FakeResponse:
        self.requests.append((url, dict(headers)))
        if url in self.overrides:
            return self.overrides[url]
        if url.startswith(f"{REGISTRY}/token"):
            return FakeResponse(200, json.dumps({"token": ANONYMOUS_TOKEN}).encode()) if self.anonymous else FakeResponse(401)
        if headers.get("Authorization") != f"Bearer {ANONYMOUS_TOKEN}":
            return FakeResponse(
                401,
                headers={"WWW-Authenticate": f'Bearer realm="{REGISTRY}/token",service="ghcr.io",'
                                             f'scope="repository:{IMAGE_PATH}:pull"'},
            )
        if not self.anonymous:
            return FakeResponse(401)
        prefix = f"{REGISTRY}/v2/{IMAGE_PATH}/"
        if url.startswith(prefix + "manifests/"):
            reference = url.rsplit("/", 1)[1]
            body = self.tags.get(reference)
            if body is None:
                body = {_digest(self.image_manifest): self.image_manifest, _digest(self.attestation): self.attestation}.get(reference)
            if body is None:
                return FakeResponse(404, b'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}')
            media = json.loads(body)["mediaType"]
            return FakeResponse(200, body, {"Docker-Content-Digest": _digest(body), "Content-Type": media})
        if url.startswith(prefix + "blobs/"):
            digest = url.rsplit("/", 1)[1]
            for blob in [self.config, *self.layers]:
                if _digest(blob) == digest:
                    return FakeResponse(200, blob)
            return FakeResponse(404)
        return FakeResponse(404)


FAKE_DOCKER = r'''#!__PYTHON__
import json, os, sys
log = os.environ["FAKE_DOCKER_LOG"]
with open(log, "a") as handle:
    config_dir = os.environ.get("DOCKER_CONFIG", "")
    config = open(os.path.join(config_dir, "config.json")).read() if config_dir and os.path.exists(os.path.join(config_dir, "config.json")) else None
    handle.write(json.dumps({"argv": sys.argv[1:], "docker_config": config,
                             "github": [k for k in os.environ if k in ("GH_TOKEN", "GITHUB_TOKEN")]}) + "\n")
args = sys.argv[1:]
if args[:2] == ["image", "inspect"]:
    state = os.environ.get("FAKE_DOCKER_PRESENT", "")
    if state == "yes" or os.path.exists(log + ".pulled"):
        print(json.dumps([os.environ["FAKE_DOCKER_REPO_DIGEST"]]))
        sys.exit(0)
    print("Error: No such image", file=sys.stderr)
    sys.exit(1)
if args[0] == "pull":
    if os.environ.get("FAKE_DOCKER_PULL") == "unauthorized":
        print("Error response from daemon: Head \"https://ghcr.io/v2/fioenix/fn-ignis/manifests/0.6.0\": unauthorized", file=sys.stderr)
        sys.exit(1)
    open(log + ".pulled", "w").close()
    print("Digest: " + os.environ["FAKE_DOCKER_REPO_DIGEST"].split("@", 1)[1])
    sys.exit(0)
if args[0] == "run":
    os.execv(sys.executable, [sys.executable, os.environ["FAKE_SERVER_PATH"], os.environ.get("FAKE_SERVER_MODE", "ok"), "44"])
if args[:2] == ["image", "rm"]:
    sys.exit(0)
print("unexpected docker call: " + " ".join(args), file=sys.stderr)
sys.exit(2)
'''


def _fake_docker(tmp_path: Path, monkeypatch, registry: FakeRegistry, **env) -> tuple[str, Path]:
    import sys

    executable = tmp_path / "fake-bin" / "docker"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(FAKE_DOCKER.replace("__PYTHON__", sys.executable), encoding="utf-8")
    executable.chmod(0o755)
    server = tmp_path / "fake_server.py"
    server.write_text(FAKE_SERVER, encoding="utf-8")
    log = tmp_path / "docker-calls.jsonl"
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_SERVER_PATH", str(server))
    monkeypatch.setenv("FAKE_DOCKER_REPO_DIGEST", f"ghcr.io/{IMAGE_PATH}@{registry.index_digest}")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return str(executable), log


def _observe_container(module, tmp_path, monkeypatch, registry=None, version="0.6.0", **env):
    registry = registry or FakeRegistry()
    docker, log = _fake_docker(tmp_path, monkeypatch, registry, **env)
    with module.TemporaryRoot(parent=tmp_path) as root:
        records = module.observe_container(
            image=f"ghcr.io/{IMAGE_PATH}",
            version=version,
            root=root.path,
            fetch=registry,
            docker=docker,
            passthrough_env=("FAKE_DOCKER_LOG", "FAKE_SERVER_PATH", "FAKE_DOCKER_REPO_DIGEST", *env),
            smoke_timeout=15,
        )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return {record.name: record for record in records}, registry, calls


def test_the_container_is_pulled_digest_checked_and_serves_mcp_anonymously(tmp_path, monkeypatch):
    module = _acceptance()
    records, registry, _ = _observe_container(module, tmp_path, monkeypatch)
    for name in ("container_anonymous_pull", "container_digest", "container_mcp_runtime"):
        assert records[name].state == module.SurfaceState.VERIFIED, records[name]
    assert registry.index_digest in records["container_digest"].subject


def test_docker_runs_with_an_empty_config_and_no_github_credentials(tmp_path, monkeypatch):
    module = _acceptance()
    monkeypatch.setenv("GH_TOKEN", "inherited-gh-token")
    monkeypatch.setenv("GITHUB_TOKEN", "inherited-github-token")
    _, _, calls = _observe_container(module, tmp_path, monkeypatch)
    assert calls, "the observer never invoked docker"
    for call in calls:
        assert call["docker_config"] is not None and json.loads(call["docker_config"]) == {}, call
        assert call["github"] == [], call


def test_only_anonymous_registry_requests_are_made(tmp_path, monkeypatch):
    module = _acceptance()
    monkeypatch.setenv("GITHUB_TOKEN", "inherited-github-token")
    _, registry, _ = _observe_container(module, tmp_path, monkeypatch)
    for url, headers in registry.requests:
        authorization = headers.get("Authorization")
        assert authorization in (None, f"Bearer {ANONYMOUS_TOKEN}"), (url, authorization)
    token_requests = [url for url, headers in registry.requests if url.startswith(f"{REGISTRY}/token")]
    assert token_requests and all("Authorization" not in dict(h) for u, h in registry.requests if u in token_requests)


def test_the_selected_platform_config_and_every_layer_are_downloaded(tmp_path, monkeypatch):
    module = _acceptance()
    _, registry, _ = _observe_container(module, tmp_path, monkeypatch)
    fetched = {url.rsplit("/", 1)[1] for url, _ in registry.requests if "/blobs/" in url}
    expected = {_digest(registry.config), *(_digest(layer) for layer in registry.layers)}
    assert expected <= fetched, f"not every blob of the selected platform was fetched: {expected - fetched}"


def test_an_unauthorized_anonymous_consumer_is_missing_public_access(tmp_path, monkeypatch):
    """The v0.5.0 baseline: the package exists, the anonymous consumer is refused."""
    module = _acceptance()
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, FakeRegistry(anonymous=False))
    assert records["container_anonymous_pull"].state == module.SurfaceState.MISSING
    assert records["container_anonymous_pull"].failure_class == "missing"
    assert records["container_mcp_runtime"].state == module.SurfaceState.UNREADABLE


def test_a_daemon_pull_refused_after_registry_success_is_missing(tmp_path, monkeypatch):
    module = _acceptance()
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, FAKE_DOCKER_PULL="unauthorized")
    assert records["container_anonymous_pull"].state == module.SurfaceState.MISSING


def test_an_absent_release_tag_is_missing(tmp_path, monkeypatch):
    module = _acceptance()
    registry = FakeRegistry()
    del registry.tags["0.6.0"]
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry)
    assert records["container_anonymous_pull"].state == module.SurfaceState.MISSING


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_rate_limited_or_failed_registry_is_unreadable_not_absent(tmp_path, monkeypatch, status):
    module = _acceptance()
    registry = FakeRegistry()
    registry.overrides[f"{REGISTRY}/v2/{IMAGE_PATH}/manifests/0.6.0"] = FakeResponse(status)
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry)
    assert records["container_anonymous_pull"].state == module.SurfaceState.UNREADABLE


def test_a_malformed_anonymous_token_response_is_unreadable(tmp_path, monkeypatch):
    module = _acceptance()

    class MalformedTokenRegistry(FakeRegistry):
        def __call__(self, url, headers):
            if url.startswith(f"{REGISTRY}/token"):
                self.requests.append((url, dict(headers)))
                return FakeResponse(200, b"{")
            return super().__call__(url, headers)

    records, _, _ = _observe_container(module, tmp_path, monkeypatch, MalformedTokenRegistry())
    assert records["container_anonymous_pull"].state == module.SurfaceState.UNREADABLE


def test_a_malformed_release_manifest_is_failed_not_a_crash(tmp_path, monkeypatch):
    module = _acceptance()
    registry = FakeRegistry()
    registry.overrides[f"{REGISTRY}/v2/{IMAGE_PATH}/manifests/0.6.0"] = FakeResponse(200, b"{")
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry)
    assert records["container_anonymous_pull"].state == module.SurfaceState.FAILED


def test_a_layer_refused_after_the_manifest_is_failed(tmp_path, monkeypatch):
    module = _acceptance()
    registry = FakeRegistry()
    registry.overrides[f"{REGISTRY}/v2/{IMAGE_PATH}/blobs/{_digest(registry.layers[1])}"] = FakeResponse(403)
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry)
    assert records["container_anonymous_pull"].state == module.SurfaceState.FAILED
    assert _digest(registry.layers[1]) in records["container_anonymous_pull"].evidence


def test_a_layer_whose_bytes_do_not_match_its_digest_is_failed(tmp_path, monkeypatch):
    module = _acceptance()
    registry = FakeRegistry()
    registry.overrides[f"{REGISTRY}/v2/{IMAGE_PATH}/blobs/{_digest(registry.layers[0])}"] = FakeResponse(200, b"tampered")
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry)
    assert records["container_anonymous_pull"].state == module.SurfaceState.FAILED


def test_a_registry_that_cannot_be_reached_is_unreadable(tmp_path, monkeypatch):
    module = _acceptance()

    def unreachable(url, headers):
        raise OSError("Could not resolve host: ghcr.io")

    docker, _ = _fake_docker(tmp_path, monkeypatch, FakeRegistry())
    with module.TemporaryRoot(parent=tmp_path) as root:
        records = module.observe_container(
            image=f"ghcr.io/{IMAGE_PATH}", version="0.6.0", root=root.path, fetch=unreachable, docker=docker
        )
    by_name = {record.name: record for record in records}
    assert by_name["container_anonymous_pull"].state == module.SurfaceState.UNREADABLE
    assert by_name["container_anonymous_pull"].failure_class == "network"


def test_a_moving_tag_on_another_digest_fails_the_digest_surface(tmp_path, monkeypatch):
    module = _acceptance()
    registry = FakeRegistry()
    registry.tags["latest"] = registry.image_manifest
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry)
    assert records["container_digest"].state == module.SurfaceState.FAILED
    assert "latest" in records["container_digest"].evidence


def test_an_absent_moving_tag_is_missing(tmp_path, monkeypatch):
    module = _acceptance()
    registry = FakeRegistry()
    del registry.tags["0.6"]
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry)
    assert records["container_digest"].state == module.SurfaceState.MISSING


def test_a_prerelease_is_checked_against_its_exact_tag_only(tmp_path, monkeypatch):
    """metadata-action never moves major.minor or latest for a prerelease, so neither is expected."""
    module = _acceptance()
    registry = FakeRegistry()
    registry.tags = {"1.0.0-rc.1": registry.index}
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry, version="1.0.0-rc.1")
    assert records["container_digest"].state == module.SurfaceState.VERIFIED, records["container_digest"]


def test_a_missing_or_different_ownership_label_fails_the_digest_surface(tmp_path, monkeypatch):
    module = _acceptance()
    for labels in (
        {SOURCE_LABEL: SOURCE_REPOSITORY_URL},
        {SOURCE_LABEL: SOURCE_REPOSITORY_URL, MCP_NAME_LABEL: "io.github.someone/else"},
        {MCP_NAME_LABEL: json.loads(_read(SERVER_JSON))["name"]},
    ):
        records, _, _ = _observe_container(module, tmp_path, monkeypatch, FakeRegistry(labels=labels))
        assert records["container_digest"].state == module.SurfaceState.FAILED, labels


def test_an_image_whose_default_process_is_not_mcp_fails_runtime(tmp_path, monkeypatch):
    """The scheduler default logs to stdout; that is exactly what the smoke must reject."""
    module = _acceptance()
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, FAKE_SERVER_MODE="banner")
    assert records["container_mcp_runtime"].state == module.SurfaceState.FAILED
    assert "non-MCP" in records["container_mcp_runtime"].evidence


def test_the_runtime_uses_the_pulled_digest_and_never_pulls_again(tmp_path, monkeypatch):
    module = _acceptance()
    registry = FakeRegistry()
    _, _, calls = _observe_container(module, tmp_path, monkeypatch, registry)
    runs = [call["argv"] for call in calls if call["argv"][:1] == ["run"]]
    assert len(runs) == 1
    assert f"ghcr.io/{IMAGE_PATH}@{registry.index_digest}" in runs[0]
    assert "--pull" in runs[0] and runs[0][runs[0].index("--pull") + 1] == "never"
    assert "--platform" in runs[0] and runs[0][runs[0].index("--platform") + 1] == "linux/amd64"


def test_an_image_the_run_pulled_is_removed_and_a_preexisting_one_is_kept(tmp_path, monkeypatch):
    module = _acceptance()
    _, registry, calls = _observe_container(module, tmp_path, monkeypatch)
    immutable = f"ghcr.io/{IMAGE_PATH}@{registry.index_digest}"
    pulls = [call["argv"] for call in calls if call["argv"][:1] == ["pull"]]
    assert len(pulls) == 1 and pulls[0][-1] == immutable, pulls
    removals = [call["argv"] for call in calls if call["argv"][:2] == ["image", "rm"]]
    assert len(removals) == 1 and removals[0][-1] == immutable, "the pulled immutable image was left behind"

    other = tmp_path / "second"
    other.mkdir()
    _, _, calls = _observe_container(module, other, monkeypatch, FAKE_DOCKER_PRESENT="yes")
    assert not any(call["argv"][:2] == ["image", "rm"] for call in calls), (
        "the observer removed an image that existed before it ran"
    )


# --------------------------------------------------------------------------------------------
# The Compose worker role, started for real rather than read from YAML
# --------------------------------------------------------------------------------------------

FAKE_COMPOSE_DOCKER = r'''#!__PYTHON__
import json, os, sys
log = os.environ["FAKE_DOCKER_LOG"]
args = sys.argv[1:]
with open(log, "a") as handle:
    handle.write(json.dumps({"argv": args}) + "\n")
mode = os.environ.get("FAKE_COMPOSE_MODE", "ok")
if mode == "no-daemon":
    print("Cannot connect to the Docker daemon at unix:///var/run/docker.sock", file=sys.stderr)
    sys.exit(1)
if args[0] == "compose":
    # Like the real CLI: an isolated DOCKER_CONFIG hides the user's cli-plugins directory unless the
    # config names it, and an override may not name a service its base file lacks.
    config = json.load(open(os.path.join(os.environ["DOCKER_CONFIG"], "config.json")))
    if set(config) - {"cliPluginsExtraDirs"} or not config.get("cliPluginsExtraDirs"):
        print("docker: unknown command: docker compose", file=sys.stderr)
        sys.exit(1)
    files = [args[i + 1] for i, a in enumerate(args) if a == "-f"]
    if files[0].endswith("docker-compose.yml") and "  db:" in open(files[1]).read():
        print('service "db" has neither an image nor a build context specified: invalid compose project', file=sys.stderr)
        sys.exit(15)
    if "config" in args:
        if mode == "config-error":
            print("yaml: line 3: invalid compose project", file=sys.stderr)
            sys.exit(15)
        command = ["python", "-m", "ignis.interfaces.cli.scheduler"]
        if mode == "no-override" and files[0].endswith("docker-compose.yml"):
            command = None
        worker = {"image": "x"}
        if command:
            worker["command"] = command
        print(json.dumps({"services": {"worker": worker}}))
        sys.exit(0)
    if "up" in args:
        sys.exit(0)
    if "down" in args:
        open(log + ".down", "w").close()
        sys.exit(0)
if args[0] == "inspect":
    print("running")
    sys.exit(0)
if args[0] == "top":
    module = "ignis.interfaces.mcp.server" if mode == "wrong-process" else "ignis.interfaces.cli.scheduler"
    print("UID PID CMD\nroot 1 python -m " + module)
    sys.exit(0)
if args[0] == "logs":
    print("Starting fn-ignis Worker Scheduler (Ingress: 8640s)...", file=sys.stderr)
    sys.exit(0)
if args[0] in ("ps", "volume", "network"):
    sys.exit(0)
print("unexpected: " + " ".join(args), file=sys.stderr)
sys.exit(2)
'''


def _observe_compose(module, tmp_path, monkeypatch, **env):
    import sys

    plugins = tmp_path / "operator-docker" / "cli-plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DOCKER_CONFIG", str(plugins.parent))
    executable = tmp_path / "compose-bin" / "docker"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(FAKE_COMPOSE_DOCKER.replace("__PYTHON__", sys.executable), encoding="utf-8")
    executable.chmod(0o755)
    log = tmp_path / "compose-calls.jsonl"
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with module.TemporaryRoot(parent=tmp_path) as root:
        record = module.observe_compose_worker(
            image_ref="ghcr.io/fioenix/fn-ignis@sha256:" + "1" * 64,
            root=root.path,
            docker=str(executable),
            passthrough_env=("FAKE_DOCKER_LOG", *env),
            settle_seconds=0,
            observe_seconds=1,
        )
        leftover_env = list(root.path.rglob("*.env"))
    calls = [json.loads(line)["argv"] for line in log.read_text().splitlines()] if log.exists() else []
    return record, calls, leftover_env, Path(str(log) + ".down").exists()


# --------------------------------------------------------------------------------------------
# Negative controls: every governed claim can turn its own contract red
# --------------------------------------------------------------------------------------------
#
# A contract that cannot fail certifies nothing. Each control copies the governed files into a
# temporary tree, proves the named contract passes on the unmodified copy, applies exactly one
# mutation, and proves the same contract then fails. The contracts are the test functions above,
# run unchanged against the copy by pointing this module's path constants at it.

import sys as _sys  # noqa: E402
import shutil as _shutil  # noqa: E402

THIS_MODULE = _sys.modules[__name__]

GOVERNED_FILES = sorted(
    {relative for relative, _ in GOVERNED_TOOL_COUNT_SURFACES}
    | set(MIGRATION_GUIDES)
    | {
        "server.json",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.prod.yml",
        ".github/workflows/docker-publish.yml",
        "pyproject.toml",
        "openclaw.json",
        "CITATION.cff",
        ".openclaw/config.yaml",
        "BACKLOG.md",
        "uv.lock",
    }
)


@pytest.fixture
def governed_copy(tmp_path, monkeypatch):
    for relative in GOVERNED_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(REPO / relative, target)
    _shutil.copytree(REPO / "sql", tmp_path / "sql")
    monkeypatch.setattr(THIS_MODULE, "REPO", tmp_path)
    monkeypatch.setattr(THIS_MODULE, "DOCKERFILE", tmp_path / "Dockerfile")
    monkeypatch.setattr(THIS_MODULE, "SERVER_JSON", tmp_path / "server.json")
    monkeypatch.setattr(THIS_MODULE, "DOCKER_PUBLISH", tmp_path / ".github" / "workflows" / "docker-publish.yml")
    monkeypatch.setattr(THIS_MODULE, "BACKLOG", tmp_path / "BACKLOG.md")
    return tmp_path


def _mutate(root: Path, relative: str, pattern: str, replacement: str) -> None:
    path = root / relative
    text, count = re.subn(pattern, replacement, _read(path), count=1, flags=re.MULTILINE)
    assert count == 1, f"negative control pattern {pattern!r} no longer matches {relative}; update the control"
    path.write_text(text, encoding="utf-8")


# (control name, file, regex, replacement, contract test it must turn red)
NEGATIVE_CONTROLS = (
    ("AGENTS tool count", "AGENTS.md", r"all 44 FastMCP tools", "all 39 FastMCP tools",
     "test_every_governed_tool_count_claim_matches_the_runtime_catalog"),
    ("CLAUDE tool count", "CLAUDE.md", r"All 44 tools", "All 39 tools",
     "test_every_governed_tool_count_claim_matches_the_runtime_catalog"),
    ("BACKLOG branch tool count", "BACKLOG.md", r"\*\*44 tools\*\*", "**39 tools**",
     "test_every_governed_tool_count_claim_matches_the_runtime_catalog"),
    ("README tool count", "README.md", r"\*\*44 tools\*\*", "**39 tools**",
     "test_every_governed_tool_count_claim_matches_the_runtime_catalog"),
    ("user guide tool count", "docs/USER_GUIDE.md", r"\*\*44 tools\*\*", "**39 tools**",
     "test_every_governed_tool_count_claim_matches_the_runtime_catalog"),
    ("README migration endpoint", "README.md", r"`sql/026_partial_degraded_probe_outcomes\.sql`", "`sql/024_youtube_quota_ledger.sql`",
     "test_install_and_upgrade_guidance_reaches_the_newest_migration"),
    ("Vietnamese guide upgrade file", "docs/USER_GUIDE.vi.md", r"`sql/026_partial_degraded_probe_outcomes\.sql`",
     "`sql/023_evidence_qualification.sql`", "test_install_and_upgrade_guidance_reaches_the_newest_migration"),
    ("PyPI install claim", "README.md", r"^(## Local source setup)$", r"\1\n\npip install fn-ignis\n",
     "test_no_public_surface_claims_a_pypi_package"),
    ("PyPI package in server.json", "server.json", r'"registryType": "oci"', '"registryType": "pypi"',
     "test_no_public_surface_claims_a_pypi_package"),
    ("OCI identifier not versioned", "server.json", r'"identifier": "ghcr\.io/fioenix/fn-ignis:[^"]+"',
     '"identifier": "ghcr.io/fioenix/fn-ignis:latest"', "test_server_json_advertises_the_versioned_oci_stdio_package"),
    ("OCI transport", "server.json", r'"type": "stdio"', '"type": "streamable-http"',
     "test_server_json_advertises_the_versioned_oci_stdio_package"),
    ("DATABASE_URL required again", "server.json", r'"isRequired": false,\n(\s*)"format"', r'"isRequired": true,\n\1"format"',
     "test_server_json_marks_the_sqlite_defaulted_database_url_optional"),
    ("Docker default role", "Dockerfile", r'^CMD \["python", "-m", "ignis\.interfaces\.mcp\.server"\]',
     'CMD ["python", "-m", "ignis.interfaces.cli.scheduler"]', "test_the_image_defaults_to_the_mcp_stdio_server"),
    ("Dockerfile source label", "Dockerfile", r'^LABEL org\.opencontainers\.image\.source=.*\n', "",
     "test_the_image_carries_its_source_and_mcp_ownership_labels"),
    ("Dockerfile MCP name label", "Dockerfile", r'io\.modelcontextprotocol\.server\.name="io\.github\.fioenix/fn-ignis"',
     'io.modelcontextprotocol.server.name="io.github.fioenix/ignis"', "test_the_image_carries_its_source_and_mcp_ownership_labels"),
    ("workflow source label", ".github/workflows/docker-publish.yml", r"^\s*org\.opencontainers\.image\.source=.*\n", "",
     "test_publish_metadata_carries_source_and_mcp_ownership_labels"),
    ("workflow MCP name label", ".github/workflows/docker-publish.yml",
     r"io\.modelcontextprotocol\.server\.name=io\.github\.fioenix/fn-ignis", "io.modelcontextprotocol.server.name=fn-ignis",
     "test_publish_metadata_carries_source_and_mcp_ownership_labels"),
    ("workflow moving action tag", ".github/workflows/docker-publish.yml",
     r"docker/metadata-action@[0-9a-f]{40} # v\d+\.\d+\.\d+", "docker/metadata-action@v6",
     "test_every_external_action_is_pinned_to_a_full_commit_with_its_release"),
    ("workflow hand-written latest", ".github/workflows/docker-publish.yml", r"latest=auto", "latest=true",
     "test_image_tags_come_only_from_stable_semver_rules"),
    ("workflow attestation subject", ".github/workflows/docker-publish.yml",
     r"subject-digest: \$\{\{ steps\.push\.outputs\.digest \}\}", "subject-digest: ${{ steps.meta.outputs.version }}",
     "test_publish_attests_the_exact_pushed_digest"),
    ("pyproject version", "pyproject.toml", r'^version = "(\d+)\.(\d+)\.(\d+)"', r'version = "\1.\2.99"',
     "test_every_release_version_carrier_agrees"),
    ("openclaw.json version", "openclaw.json", r'"version": "\d+\.\d+\.\d+"', '"version": "9.9.9"',
     "test_every_release_version_carrier_agrees"),
    ("server.json root version", "server.json", r'^  "version": "\d+\.\d+\.\d+"', '  "version": "9.9.9"',
     "test_every_release_version_carrier_agrees"),
    ("server.json package version", "server.json", r'^      "version": "\d+\.\d+\.\d+"', '      "version": "9.9.9"',
     "test_every_release_version_carrier_agrees"),
    ("server.json OCI identifier tag", "server.json", r'(ghcr\.io/fioenix/fn-ignis):\d+\.\d+\.\d+', r"\1:9.9.9",
     "test_every_release_version_carrier_agrees"),
    ("CITATION version", "CITATION.cff", r"^version: \d+\.\d+\.\d+", "version: 9.9.9",
     "test_every_release_version_carrier_agrees"),
    ("openclaw config version", ".openclaw/config.yaml", r"^version: \d+\.\d+\.\d+", "version: 9.9.9",
     "test_every_release_version_carrier_agrees"),
    ("BACKLOG banner version", "BACKLOG.md", r"\*\*Phiên bản:\*\* `v\d+\.\d+\.\d+`", "**Phiên bản:** `v9.9.9`",
     "test_every_release_version_carrier_agrees"),
    ("uv.lock left behind", "uv.lock", r'(name = "fn-ignis"\nversion = )"\d+\.\d+\.\d+"', r'\1"9.9.9"',
     "test_every_release_version_carrier_agrees"),
)


@pytest.mark.parametrize(
    ("relative", "pattern", "replacement", "contract"),
    [control[1:] for control in NEGATIVE_CONTROLS],
    ids=[control[0] for control in NEGATIVE_CONTROLS],
)
def test_each_negative_control_turns_its_contract_red(governed_copy, relative, pattern, replacement, contract):
    check = getattr(THIS_MODULE, contract)
    check()  # the unmodified copy satisfies the contract
    _mutate(governed_copy, relative, pattern, replacement)
    with pytest.raises(AssertionError):
        check()


@pytest.mark.parametrize("moved_tag", ["0.6", "latest"])
def test_each_moving_release_tag_on_another_digest_is_caught(tmp_path, monkeypatch, moved_tag):
    module = _acceptance()
    registry = FakeRegistry()
    registry.tags[moved_tag] = registry.image_manifest
    records, _, _ = _observe_container(module, tmp_path, monkeypatch, registry)
    assert records["container_digest"].state == module.SurfaceState.FAILED
    assert moved_tag in records["container_digest"].evidence


def test_a_daemon_digest_that_differs_from_the_release_tag_is_caught(tmp_path, monkeypatch):
    module = _acceptance()
    records, _, _ = _observe_container(
        module, tmp_path, monkeypatch, FAKE_DOCKER_REPO_DIGEST=f"ghcr.io/{IMAGE_PATH}@sha256:{'e' * 64}"
    )
    assert records["container_digest"].state == module.SurfaceState.FAILED


# --------------------------------------------------------------------------------------------
# History stays history: dated measurements are not current claims
# --------------------------------------------------------------------------------------------


def _backlog_history(path: Path) -> str:
    """The dated release history outside the current development section."""
    text = _read(path)
    current = text.split("## Spec 011 — trạng thái nhánh phát triển, chưa phát hành", 1)[1].split("\n---", 1)[0]
    return text.replace(current, "")


def test_dated_backlog_measurements_keep_their_original_counts():
    """The v0.4.0 preparation log measured 39 tools on its date; that sentence stays true."""
    history = _backlog_history(BACKLOG)
    assert re.search(r"\b39 tool\b", history), (
        "the dated v0.4.0 measurement of 39 tools disappeared from BACKLOG's history; history is "
        "not rewritten to make a text search look clean"
    )
    assert not tool_count_offenders(_runtime_tool_count(), (("BACKLOG.md", GOVERNED_TOOL_COUNT_SURFACES[-1][1]),))


def test_a_dated_history_entry_is_not_governed_but_a_current_one_is(governed_copy):
    expected = _runtime_tool_count()
    history_anchor = r"^(### Chuẩn bị release v0\.4\.0.*)$"
    _mutate(governed_copy, "BACKLOG.md", history_anchor, r"\1\n\nMeasured 14/09/2026: 39 tools.")
    assert not tool_count_offenders(expected), "a dated history line was treated as a current claim"

    _mutate(governed_copy, "BACKLOG.md", r"^(## Spec 011 — trạng thái nhánh phát triển, chưa phát hành.*)$", r"\1\n\nIgnis exposes 39 tools.")
    assert tool_count_offenders(expected), "an unlabeled current claim inside a governed section passed"


def test_upgrade_guidance_may_name_earlier_migrations():
    """`022` in the per-migration upgrade list is correct history for older databases, not drift."""
    for relative in MIGRATION_GUIDES:
        assert "sql/022_builtin_uuid_defaults.sql" in _read(REPO / relative), relative
    assert not migration_endpoint_offenders(_newest_migration())
    assert (REPO / "sql" / "022_builtin_uuid_defaults.sql").is_file()


def test_migration_file_names_and_upgrade_tests_are_outside_the_count_gate():
    """Migration files and the tests that upgrade 021 to 022 name old endpoints by design."""
    governed = {relative for relative, _ in GOVERNED_TOOL_COUNT_SURFACES} | set(MIGRATION_GUIDES)
    assert not any(relative.startswith(("sql/", "tests/", "specs/")) for relative in governed), governed


# --------------------------------------------------------------------------------------------
# The provisioner reports the catalog it can prove, never a remembered number
# --------------------------------------------------------------------------------------------


def test_generated_antigravity_instructions_state_the_manifest_catalog(tmp_path, monkeypatch):
    from ignis.interfaces.cli import setup_bundle

    home = tmp_path / "home"
    (home / ".gemini" / "config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(setup_bundle, "register_mcp_to_json_file", lambda *args, **kwargs: True)
    monkeypatch.setattr(setup_bundle, "get_claude_desktop_config_path", lambda: tmp_path / "nowhere" / "c.json")
    monkeypatch.setattr(setup_bundle.sys, "platform", "linux")
    project = tmp_path / "project"
    project.mkdir()
    _shutil.copy2(REPO / "hermes_manifest.json", project / "hermes_manifest.json")

    setup_bundle.setup_all_mcp_clients(project, "/usr/bin/python3")

    instructions = _read(home / ".gemini" / "antigravity" / "mcp" / "fn-ignis" / "instructions.md")
    expected = len(json.loads(_read(REPO / "hermes_manifest.json")))
    assert f"Provides {expected} tools" in instructions, instructions


def test_a_failed_tool_discovery_is_not_reported_as_a_successful_count(monkeypatch):
    """A fallback number printed on failure is a false success; the report must say discovery failed."""
    from ignis.interfaces.cli import setup_bundle
    from ignis.interfaces.mcp import server

    monkeypatch.setattr(setup_bundle, "ensure_environment_file", lambda root: (False, "exists"))

    async def ok_database():
        return True, "ready"

    async def diagnostics():
        return {"database": "healthy", "google_rss": "skipped", "lexicon_count": 1}

    async def broken_discovery():
        raise RuntimeError("tool registry failed to load")

    monkeypatch.setattr(setup_bundle, "bootstrap_database", ok_database)
    monkeypatch.setattr(setup_bundle, "setup_all_mcp_clients", lambda root, python: [])
    monkeypatch.setattr(setup_bundle, "run_synthetic_diagnostics", diagnostics)
    monkeypatch.setattr(server.mcp, "list_tools", broken_discovery)

    report = setup_bundle.auto_provision(json_output=True)

    assert report["capabilities"]["tools_count"] is None, report["capabilities"]
    assert report["status"] != "success", report["status"]
    assert "tool registry failed to load" in report["capabilities"].get("discovery_error", "")


# --------------------------------------------------------------------------------------------
# `all` mode: the GitHub facts, version parity, provenance and registry validation
# --------------------------------------------------------------------------------------------

API = "https://api.github.com/repos/fioenix/fn-ignis"
TAG_COMMIT = "1" * 40


class FakeGitHub:
    """Anonymous GitHub REST answers for one release, each overridable."""

    def __init__(self):
        self.answers = {
            API: (200, {"private": False, "visibility": "public"}),
            f"{API}/git/ref/tags/v0.6.0": (200, {"object": {"type": "tag", "sha": "a" * 40}}),
            f"{API}/git/tags/{'a' * 40}": (200, {"object": {"type": "commit", "sha": TAG_COMMIT}}),
            f"{API}/compare/{TAG_COMMIT}...main": (200, {"status": "behind", "behind_by": 0, "ahead_by": 2}),
            f"{API}/releases/tags/v0.6.0": (200, {"draft": False, "published_at": "2026-09-30T00:00:00Z",
                                                  "html_url": "https://github.com/fioenix/fn-ignis/releases/tag/v0.6.0"}),
            f"{API}/actions/workflows/docker-publish.yml/runs?branch=v0.6.0&event=push&per_page=5": (
                200, {"workflow_runs": [{"status": "completed", "conclusion": "success", "head_sha": TAG_COMMIT,
                                         "html_url": "https://github.com/fioenix/fn-ignis/actions/runs/1"}]}),
        }
        self.requests = []

    def __call__(self, url, headers):
        self.requests.append((url, dict(headers)))
        status, body = self.answers.get(url, (404, {"message": "Not Found"}))
        return FakeResponse(status, json.dumps(body).encode())


def _github(module, fake=None, expected=TAG_COMMIT):
    fake = fake or FakeGitHub()
    records = module.observe_github(
        repository="https://github.com/fioenix/fn-ignis.git", version="0.6.0", expected_commit=expected, fetch=fake
    )
    return {record.name: record for record in records}, fake


def test_a_public_repository_tag_on_main_release_and_green_workflow_are_verified():
    module = _acceptance()
    records, fake = _github(module)
    for name in ("repository_public", "tag_on_main", "github_release_published", "container_workflow"):
        assert records[name].state == module.SurfaceState.VERIFIED, records[name]
    assert all("Authorization" not in headers for _, headers in fake.requests), "GitHub facts must be read anonymously"


def test_a_repository_hidden_from_anonymous_readers_is_not_public():
    module = _acceptance()
    fake = FakeGitHub()
    fake.answers[API] = (404, {"message": "Not Found"})
    records, _ = _github(module, fake)
    assert records["repository_public"].state == module.SurfaceState.MISSING


def test_a_rate_limited_github_answer_is_unreadable_not_absent():
    module = _acceptance()
    fake = FakeGitHub()
    fake.answers[f"{API}/releases/tags/v0.6.0"] = (403, {"message": "API rate limit exceeded"})
    records, _ = _github(module, fake)
    assert records["github_release_published"].state == module.SurfaceState.UNREADABLE


def test_a_missing_release_is_missing():
    module = _acceptance()
    fake = FakeGitHub()
    del fake.answers[f"{API}/releases/tags/v0.6.0"]
    records, _ = _github(module, fake)
    assert records["github_release_published"].state == module.SurfaceState.MISSING


def test_a_lightweight_release_tag_fails_the_annotated_tag_contract():
    module = _acceptance()
    fake = FakeGitHub()
    fake.answers[f"{API}/git/ref/tags/v0.6.0"] = (200, {"object": {"type": "commit", "sha": TAG_COMMIT}})
    records, _ = _github(module, fake)
    assert records["tag_on_main"].state == module.SurfaceState.FAILED


def test_a_tag_off_main_or_on_another_commit_fails():
    module = _acceptance()
    fake = FakeGitHub()
    fake.answers[f"{API}/compare/{TAG_COMMIT}...main"] = (200, {"status": "diverged", "behind_by": 3, "ahead_by": 1})
    records, _ = _github(module, fake)
    assert records["tag_on_main"].state == module.SurfaceState.FAILED

    records, _ = _github(module, FakeGitHub(), expected="2" * 40)
    assert records["tag_on_main"].state == module.SurfaceState.FAILED


def test_a_failed_or_foreign_publish_workflow_is_not_verified():
    module = _acceptance()
    runs = f"{API}/actions/workflows/docker-publish.yml/runs?branch=v0.6.0&event=push&per_page=5"
    fake = FakeGitHub()
    fake.answers[runs] = (200, {"workflow_runs": [{"status": "completed", "conclusion": "failure", "head_sha": TAG_COMMIT,
                                                   "html_url": "x"}]})
    assert _github(module, fake)[0]["container_workflow"].state == module.SurfaceState.FAILED
    fake.answers[runs] = (200, {"workflow_runs": [{"status": "completed", "conclusion": "success", "head_sha": "3" * 40,
                                                   "html_url": "x"}]})
    assert _github(module, fake)[0]["container_workflow"].state == module.SurfaceState.FAILED
    fake.answers[runs] = (200, {"workflow_runs": []})
    assert _github(module, fake)[0]["container_workflow"].state == module.SurfaceState.MISSING


def test_version_parity_reads_every_carrier_in_the_tagged_tree(tmp_path):
    module = _acceptance()
    for relative in ("pyproject.toml", "openclaw.json", "server.json", "CITATION.cff", ".openclaw/config.yaml",
                     "BACKLOG.md", "uv.lock"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(REPO / relative, target)
    declared = tomllib.loads(_read(REPO / "pyproject.toml"))["project"]["version"]

    assert module.observe_version_parity(tmp_path, declared).state == module.SurfaceState.VERIFIED
    assert module.observe_version_parity(tmp_path, "9.9.9").state == module.SurfaceState.FAILED
    _mutate(tmp_path, "uv.lock", r'(name = "fn-ignis"\nversion = )"\d+\.\d+\.\d+"', r'\1"9.9.9"')
    record = module.observe_version_parity(tmp_path, declared)
    assert record.state == module.SurfaceState.FAILED and "uv.lock" in record.evidence
    assert module.observe_version_parity(None, declared).state == module.SurfaceState.UNREADABLE


FAKE_TOOL = r'''#!__PYTHON__
import json, os, sys
with open(os.environ["FAKE_TOOL_LOG"], "a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\n")
mode = os.environ.get("FAKE_TOOL_MODE", "ok")
if "--version" in sys.argv:
    print("mcp-publisher 1.2.3")
    sys.exit(0)
if mode == "ok":
    print("✅ server.json is valid" if "validate" in sys.argv else "Loaded 1 attestation")
    sys.exit(0)
if mode == "no-attestation":
    print("Error: no attestations found for subject", file=sys.stderr)
    sys.exit(1)
if mode == "auth":
    print("error: HTTP 401: Bad credentials", file=sys.stderr)
    sys.exit(1)
print("verification failed: signer workflow mismatch", file=sys.stderr)
sys.exit(1)
'''


def _fake_tool(tmp_path, monkeypatch, name, mode="ok"):
    import sys

    tool = tmp_path / "tools" / name
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text(FAKE_TOOL.replace("__PYTHON__", sys.executable), encoding="utf-8")
    tool.chmod(0o755)
    log = tmp_path / f"{name}.jsonl"
    monkeypatch.setenv("FAKE_TOOL_LOG", str(log))
    monkeypatch.setenv("FAKE_TOOL_MODE", mode)
    return str(tool), log


@pytest.mark.parametrize(
    ("mode", "state"),
    [("ok", "VERIFIED"), ("no-attestation", "MISSING"), ("auth", "UNREADABLE"), ("mismatch", "FAILED")],
)
def test_provenance_is_verified_against_the_digest_repository_ref_and_workflow(tmp_path, monkeypatch, mode, state):
    module = _acceptance()
    gh, log = _fake_tool(tmp_path, monkeypatch, "gh", mode)
    digest = "sha256:" + "a" * 64
    record = module.observe_provenance(
        image="ghcr.io/fioenix/fn-ignis", digest=digest, version="0.6.0",
        repository="https://github.com/fioenix/fn-ignis.git", expected_commit=TAG_COMMIT, gh=gh,
    )
    assert record.name == "container_provenance" and record.state == state, record
    argv = json.loads(log.read_text().splitlines()[0])
    assert argv[:3] == ["attestation", "verify", f"oci://ghcr.io/fioenix/fn-ignis@{digest}"]
    for flag, value in (("--repo", "fioenix/fn-ignis"), ("--source-ref", "refs/tags/v0.6.0"),
                        ("--signer-workflow", "fioenix/fn-ignis/.github/workflows/docker-publish.yml"),
                        ("--source-digest", TAG_COMMIT)):
        assert argv[argv.index(flag) + 1] == value, argv


def test_provenance_without_a_verified_digest_is_unread(tmp_path, monkeypatch):
    module = _acceptance()
    gh, _ = _fake_tool(tmp_path, monkeypatch, "gh")
    record = module.observe_provenance(image="ghcr.io/fioenix/fn-ignis", digest=None, version="0.6.0",
                                       repository="https://github.com/fioenix/fn-ignis.git", expected_commit=None, gh=gh)
    assert record.state == module.SurfaceState.UNREADABLE


@pytest.mark.parametrize(("mode", "state"), [("ok", "VERIFIED"), ("mismatch", "FAILED")])
def test_registry_validation_runs_the_publisher_on_the_tagged_manifest(tmp_path, monkeypatch, mode, state):
    module = _acceptance()
    publisher, log = _fake_tool(tmp_path, monkeypatch, "mcp-publisher", mode)
    tree = tmp_path / "checkout"
    tree.mkdir()
    _shutil.copy2(REPO / "server.json", tree / "server.json")
    record = module.observe_registry_validation(
        tree, publisher=publisher, passthrough_env=("FAKE_TOOL_LOG", "FAKE_TOOL_MODE")
    )
    assert record.state == state, record
    if state == "VERIFIED":
        assert "mcp-publisher 1.2.3" in record.evidence
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert ["validate"] in calls or any(call[:1] == ["validate"] for call in calls), calls


def test_a_missing_publisher_leaves_registry_validation_unread(tmp_path):
    module = _acceptance()
    tree = tmp_path / "checkout"
    tree.mkdir()
    record = module.observe_registry_validation(tree, publisher=str(tmp_path / "no-such-publisher"))
    assert record.state == module.SurfaceState.UNREADABLE
    assert record.failure_class == "tool_unavailable"


def test_all_mode_combines_every_observation_into_one_verdict(tmp_path, monkeypatch):
    module = _acceptance()
    digest = "sha256:" + "b" * 64
    seen = {}

    def verified(name, subject=None):
        return _record(module, name, subject=subject or name)

    def source(**kwargs):
        checkout = kwargs["root"] / "checkout"
        checkout.mkdir(parents=True)
        seen["checkout"] = checkout
        return [verified(n) for n in ("source_tag_checkout", "source_bootstrap", "source_mcp_runtime")]

    def container(**kwargs):
        return [
            verified("container_anonymous_pull", f"ghcr.io/fioenix/fn-ignis@{digest}"),
            verified("container_digest", f"ghcr.io/fioenix/fn-ignis@{digest}"),
            verified("container_mcp_runtime"),
        ]

    monkeypatch.setattr(module, "observe_source", source)
    monkeypatch.setattr(module, "observe_container", container)
    monkeypatch.setattr(module, "observe_github", lambda **kwargs: [verified(n) for n in (
        "repository_public", "tag_on_main", "github_release_published", "container_workflow")])

    def parity(tree, version):
        seen["parity_tree"] = tree
        return verified("version_parity")

    def provenance(**kwargs):
        seen["provenance_digest"] = kwargs["digest"]
        return verified("container_provenance")

    def registry(tree, **kwargs):
        seen["registry_tree"] = tree
        return verified("mcp_registry_validation")

    monkeypatch.setattr(module, "observe_version_parity", parity)
    monkeypatch.setattr(module, "observe_provenance", provenance)
    monkeypatch.setattr(module, "observe_registry_validation", registry)

    output = tmp_path / "evidence.json"
    exit_code = module.main(["all", "--version", "0.6.0", "--expected-commit", MAIN_COMMIT,
                             "--work-root", str(tmp_path), "--json-output", str(output)])

    assert exit_code == 0
    assert json.loads(_read(output))["verdict"] == "RELEASED"
    assert seen["parity_tree"] == seen["checkout"] and seen["registry_tree"] == seen["checkout"]
    assert seen["provenance_digest"] == digest
