"""Contracts for what the public release says about itself, checked against what it is.

Plan 009 makes two distribution paths public: a tagged source checkout bootstrapped with one
command, and an OCI image on GHCR. Before it, the tracked surfaces disagreed with the runtime and
with each other: current guidance claimed 39 or 45 MCP tools while the server exposed 47, install
guidance stopped at migration `022` while `023` shipped, `server.json` advertised a PyPI package
that was never published, and the image defaulted to the scheduler worker while the manifest
declared an MCP stdio server.

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

# PyYAML arrives with fastmcp, a required runtime dependency. Parsed, not pattern-matched: a
# comment is not configuration, and indentation changes what a key means.
import yaml

REPO = Path(__file__).resolve().parents[2]

DOCKERFILE = REPO / "Dockerfile"
COMPOSE_FILES = (REPO / "docker-compose.yml", REPO / "docker-compose.prod.yml")
SERVER_JSON = REPO / "server.json"
DOCKER_PUBLISH = REPO / ".github" / "workflows" / "docker-publish.yml"
BACKLOG = REPO / "BACKLOG.md"

MCP_SERVER_MODULE = "ignis.interfaces.mcp.server"
SCHEDULER_MODULE = "ignis.interfaces.cli.scheduler"
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


# (relative path, section reader). Only these surfaces describe the current release; anything
# else in the repository may legitimately carry a dated measurement. A surface is listed by the
# section that makes the current claim so that history elsewhere in the same file stays valid.
GOVERNED_TOOL_COUNT_SURFACES = (
    ("AGENTS.md", _whole),
    ("CLAUDE.md", _whole),
    (".github/workflows/ci.yml", _whole),
    ("src/ignis/interfaces/cli/setup_bundle.py", _whole),
    ("docs/PROJECT_REVIEW_CONTEXT.md", _whole),
    ("README.md", _whole),
    ("README.vi.md", _whole),
    ("docs/USER_GUIDE.md", _whole),
    ("docs/USER_GUIDE.vi.md", _whole),
    ("docs/assets/architecture.html", _whole),
    ("docs/assets/architecture.svg", _whole),
    ("docs/diagrams/ignis-pipeline.html", _whole),
    ("docs/diagrams/ignis-pipeline.svg", _whole),
    ("BACKLOG.md", _backlog_banner),
    ("BACKLOG.md", _backlog_current_accomplishments),
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
VERIFIED_ENDPOINT_CLAIM = re.compile(r"(?:verified through|kiểm chứng tới)\s+`(\d{3})`", re.IGNORECASE)

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
    endpoint = newest.name[:3]
    offenders = []
    for relative in guides:
        text = _read(REPO / relative)
        claims = VERIFIED_ENDPOINT_CLAIM.findall(text)
        if not claims:
            offenders.append(f"{relative}: states no verified fresh-init endpoint")
        offenders.extend(
            f"{relative}: fresh init verified through `{claim}`, chain ends at `{endpoint}`"
            for claim in claims
            if claim != endpoint
        )
        if f"sql/{newest.name}" not in text:
            offenders.append(f"{relative}: upgrade guidance never names sql/{newest.name}")
    return offenders


def test_install_and_upgrade_guidance_reaches_the_newest_migration():
    offenders = migration_endpoint_offenders(_newest_migration())
    assert not offenders, (
        "Install guidance must reach the end of the packaged migration chain, and an existing "
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
    """PyPI is deferred for v0.6.0; a manifest naming it points clients at nothing."""
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


# --------------------------------------------------------------------------------------------
# Image role: the direct image is the MCP server, Compose selects the worker
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


def _compose_worker_command(path: Path) -> list[str] | None:
    services = yaml.safe_load(_read(path)).get("services", {})
    return services.get("worker", {}).get("command")


def test_both_compose_files_select_the_scheduler_explicitly():
    """The worker role survives the image default changing only because Compose names it."""
    for path in COMPOSE_FILES:
        assert _compose_worker_command(path) == ["python", "-m", SCHEDULER_MODULE], (
            f"{path.name}'s worker no longer runs the scheduler explicitly; with an MCP default "
            "image it would start the MCP server and exit when stdin closes"
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
tools = int(sys.argv[2]) if len(sys.argv) > 2 else 47
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
        result = {"tools": [{"name": f"tool_{i}", "inputSchema": {}} for i in range(tools)]}
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


def _fake(tmp_path, mode, tools=47) -> list[str]:
    import sys

    server = tmp_path / "fake_server.py"
    server.write_text(FAKE_SERVER, encoding="utf-8")
    return [sys.executable, str(server), mode, str(tools)]


def test_a_caller_supplied_command_completes_the_smoke(tmp_path):
    module = _smoke()
    result = module.run_smoke(_fake(tmp_path, "ok"), response_timeout=10, exit_timeout=10)
    assert result.tool_count == module.EXPECTED_TOOL_COUNT
    assert result.runtime_configs == 3


def test_a_wrong_tool_count_fails_the_smoke(tmp_path):
    module = _smoke()
    import pytest

    with pytest.raises(module.SmokeFailure, match="expected 47 tools, discovered 45"):
        module.run_smoke(_fake(tmp_path, "ok", tools=45), response_timeout=10, exit_timeout=10)


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
printf '#!/bin/sh\nexec "%s" "%s/fake_server.py" ok "${FAKE_TOOLS:-47}"\n' "$FAKE_PYTHON" "$PWD" > .venv/bin/python
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
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch, expected=fixture["main"])
    assert records["source_tag_checkout"].state == module.SurfaceState.FAILED
    assert records["source_tag_checkout"].failure_class == "behavior_mismatch"


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
    records, _ = _observe_source(module, fixture, tmp_path, monkeypatch, FAKE_TOOLS="45")
    assert records["source_bootstrap"].state == module.SurfaceState.VERIFIED
    assert records["source_mcp_runtime"].state == module.SurfaceState.FAILED
    assert "discovered 45" in records["source_mcp_runtime"].evidence
