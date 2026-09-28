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
