#!/usr/bin/env python3
"""Decide whether a version is publicly distributed, from public bytes rather than configuration.

`scripts/check_release_state.py` reads three facts from Git and GitHub: a tag, a published Release,
the repository visibility. None of them says whether a stranger can obtain and run the release. A
green publish workflow leaves a GHCR package private by default, a tag can omit a file the local
tree has, and a cached registry login makes a private image look public. So this script behaves
like that stranger: it clones the exact public tag into a disposable root, bootstraps it under an
empty home, pulls the image with an empty registry configuration, and holds an MCP conversation
with what it obtained.

Every surface is recorded in one of five states, and the difference between them is the point:

    VERIFIED    the owning surface positively satisfies the contract
    MISSING     the owning surface positively says the object or the access is absent
    FAILED      the artifact was obtained and violated its behavioral contract
    UNREADABLE  the fact could not be observed (network, auth scope, missing tool, not attempted)
    DEFERRED    policy excludes a non-required surface -- PyPI for this release

The verdict is derived, never typed: RELEASED only when every required surface is VERIFIED;
INDETERMINATE when any is UNREADABLE; NOT_RELEASED when something is proven missing or failed.
An empty stdout or a non-zero exit is never read as absence unless the answer matches a known
absence response.

Anonymous distribution and authenticated provenance are separate observations. The anonymous
paths run with an allowlisted environment and no credential; attestation verification needs the
release owner's registry authentication and is recorded as its own surface.

    python scripts/public_release_acceptance.py source --version 0.7.0 \\
        --repository https://github.com/fioenix/fn-ignis.git --expected-commit <sha>
    python scripts/public_release_acceptance.py container --version 0.7.0 \\
        --image ghcr.io/fioenix/fn-ignis
    python scripts/public_release_acceptance.py all --version 0.7.0 ... --json-output <path>
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

SCHEMA_VERSION = 1

# Captured output is evidence, not a log. Bounded so a runaway child cannot fill the bundle.
MAX_CAPTURED_CHARS = 8000


class SurfaceState(StrEnum):
    VERIFIED = "VERIFIED"
    MISSING = "MISSING"
    FAILED = "FAILED"
    UNREADABLE = "UNREADABLE"
    DEFERRED = "DEFERRED"


class Verdict(StrEnum):
    RELEASED = "RELEASED"
    NOT_RELEASED = "NOT_RELEASED"
    INDETERMINATE = "INDETERMINATE"


# The policy. Every required surface must appear exactly once in a bundle; an unknown name fails
# validation, so a typo cannot create an unchecked replacement for one of these.
REQUIRED_SURFACES = (
    "repository_public",
    "tag_on_main",
    "github_release_published",
    "version_parity",
    "source_tag_checkout",
    "source_bootstrap",
    "source_mcp_runtime",
    "container_workflow",
    "container_anonymous_pull",
    "container_digest",
    "container_mcp_runtime",
    "container_provenance",
    "mcp_registry_validation",
    "compose_worker_override",
)
DEFERRED_SURFACES = ("pypi_distribution",)

# Why a surface is not VERIFIED. `not_observed` marks a surface the chosen mode never attempted,
# which is unread rather than absent; `unclassified` is a failure whose answer matched no known
# response, which is also unread.
FAILURE_CLASSES = frozenset(
    {
        "missing",
        "behavior_mismatch",
        "auth",
        "network",
        "tool_unavailable",
        "not_observed",
        "unclassified",
    }
)

FULL_SHA = re.compile(r"[0-9a-f]{40}")
SEMVER = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


# --------------------------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------------------------

# Credential shapes that must never reach the bundle, whatever printed them.
_SECRET_SHAPES = (
    # userinfo in any URL: https://user:token@host, postgresql://user:password@host. The scheme and
    # userinfo are length-bounded: unbounded, a long run of letters with no "://" is quadratic.
    (
        re.compile(r"(?P<scheme>\b[a-z][a-z0-9+.-]{0,30}://)[^/\s@]{1,512}@", re.IGNORECASE),
        r"\g<scheme>[REDACTED]@",
    ),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED]"),
    (re.compile(r"\bey[A-Za-z0-9_-]{10,4096}\.[A-Za-z0-9_-]{10,4096}\.[A-Za-z0-9_-]{10,4096}\b"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"(?i)\b(authorization:\s*(?:bearer|basic|token))\s+\S+"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b((?:password|passwd|token|secret)\s*[=:]\s*)\S+"), r"\1[REDACTED]"),
)

# An ambient variable whose name says it holds a credential. Its exact value is scrubbed from any
# text, because a tool may echo a token in a shape none of the patterns above recognise.
_SECRET_ENV_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|KEY|DSN|DATABASE_URL|CREDENTIAL|AUTH", re.IGNORECASE)
_MIN_AMBIENT_SECRET_LENGTH = 8


def _ambient_secret_values() -> list[str]:
    values = {
        value
        for name, value in os.environ.items()
        if _SECRET_ENV_NAME.search(name) and len(value) >= _MIN_AMBIENT_SECRET_LENGTH
    }
    # Longest first, so a value containing another is scrubbed whole.
    return sorted(values, key=len, reverse=True)


def redact(text: str | None) -> str:
    """The text with every credential shape and every ambient secret value removed."""
    if not text:
        return text or ""
    for value in _ambient_secret_values():
        text = text.replace(value, "[REDACTED]")
    for pattern, replacement in _SECRET_SHAPES:
        text = pattern.sub(replacement, text)
    return text


def _bounded(text: str) -> str:
    text = redact(text)
    if len(text) <= MAX_CAPTURED_CHARS:
        return text
    marker = "\n...[truncated]...\n"
    keep = MAX_CAPTURED_CHARS - len(marker)
    return text[: keep // 2] + marker + text[-(keep - keep // 2):]


# --------------------------------------------------------------------------------------------
# Surface records and the verdict
# --------------------------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class SurfaceRecord:
    """One observation. Validated and redacted on construction, so an invalid record cannot exist."""

    name: str
    state: SurfaceState
    subject: str
    evidence: str
    failure_class: str | None = None
    command_exit: int | None = None
    observed_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.name not in REQUIRED_SURFACES and self.name not in DEFERRED_SURFACES:
            raise ValueError(f"unknown surface {self.name!r}")
        object.__setattr__(self, "state", SurfaceState(self.state))
        if self.state == SurfaceState.DEFERRED and self.required:
            raise ValueError(f"{self.name} is required; DEFERRED never satisfies a required surface")
        if self.state in (SurfaceState.VERIFIED, SurfaceState.DEFERRED):
            if self.failure_class is not None:
                raise ValueError(f"{self.name}: a {self.state} record carries no failure_class")
        elif self.failure_class not in FAILURE_CLASSES:
            raise ValueError(
                f"{self.name}: a {self.state} record needs a failure_class from {sorted(FAILURE_CLASSES)}, "
                f"got {self.failure_class!r}"
            )
        object.__setattr__(self, "subject", redact(self.subject))
        object.__setattr__(self, "evidence", _bounded(self.evidence))

    @property
    def required(self) -> bool:
        return self.name in REQUIRED_SURFACES

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "required": self.required,
            "state": self.state.value,
            "observed_at": self.observed_at,
            "subject": self.subject,
            "evidence": self.evidence,
            "command_exit": self.command_exit,
            "failure_class": self.failure_class,
        }


def complete_with_unobserved(records: list[SurfaceRecord]) -> list[SurfaceRecord]:
    """Add a record for every policy surface this run did not attempt.

    A required surface nobody looked at is UNREADABLE, never absent and never verified, so a
    partial run can only ever produce INDETERMINATE. PyPI stays DEFERRED.
    """
    seen = {record.name for record in records}
    completed = list(records)
    for name in REQUIRED_SURFACES:
        if name not in seen:
            completed.append(
                SurfaceRecord(
                    name=name,
                    state=SurfaceState.UNREADABLE,
                    subject=name,
                    evidence="not observed by this acceptance mode",
                    failure_class="not_observed",
                )
            )
    for name in DEFERRED_SURFACES:
        if name not in seen:
            completed.append(
                SurfaceRecord(
                    name=name,
                    state=SurfaceState.DEFERRED,
                    subject=name,
                    evidence="excluded from this release by distribution policy",
                )
            )
    return completed


def derive_verdict(surfaces: dict[str, SurfaceRecord]) -> Verdict:
    required = [surfaces[name].state for name in REQUIRED_SURFACES]
    if SurfaceState.UNREADABLE in required:
        return Verdict.INDETERMINATE
    if SurfaceState.MISSING in required or SurfaceState.FAILED in required:
        return Verdict.NOT_RELEASED
    if all(state == SurfaceState.VERIFIED for state in required):
        return Verdict.RELEASED
    return Verdict.INDETERMINATE


@dataclass(frozen=True)
class EvidenceBundle:
    version: str
    main_commit: str | None
    surfaces: dict[str, SurfaceRecord]
    verdict: Verdict
    missing: list[str]
    failed: list[str]
    unreadable: list[str]
    deferred: list[str]

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "version": self.version,
            "main_commit": self.main_commit,
            "surfaces": {name: record.to_dict() for name, record in self.surfaces.items()},
            "verdict": self.verdict.value,
            "missing": self.missing,
            "failed": self.failed,
            "unreadable": self.unreadable,
            "deferred": self.deferred,
        }


def build_bundle(version: str, main_commit: str | None, records: list[SurfaceRecord]) -> EvidenceBundle:
    """Validate a complete set of observations and derive its verdict.

    Every problem is listed even when one unreadable surface makes the verdict indeterminate, so an
    outage cannot hide a separately proven missing Release or failed runtime.
    """
    if not SEMVER.fullmatch(version or ""):
        raise ValueError(f"not a release version: {version!r}")
    if main_commit is not None and not FULL_SHA.fullmatch(main_commit):
        raise ValueError(f"main commit must be a full lowercase SHA, got {main_commit!r}")

    surfaces: dict[str, SurfaceRecord] = {}
    for record in records:
        if record.name in surfaces:
            raise ValueError(f"duplicate surface {record.name!r}")
        surfaces[record.name] = record
    absent = [name for name in REQUIRED_SURFACES + DEFERRED_SURFACES if name not in surfaces]
    if absent:
        raise ValueError(f"surfaces without a record: {absent}")

    def named(state: SurfaceState) -> list[str]:
        return [name for name in REQUIRED_SURFACES if surfaces[name].state == state]

    ordered = {name: surfaces[name] for name in REQUIRED_SURFACES + DEFERRED_SURFACES}
    return EvidenceBundle(
        version=version,
        main_commit=main_commit,
        surfaces=ordered,
        verdict=derive_verdict(ordered),
        missing=named(SurfaceState.MISSING),
        failed=named(SurfaceState.FAILED),
        unreadable=named(SurfaceState.UNREADABLE),
        deferred=[name for name in DEFERRED_SURFACES if surfaces[name].state == SurfaceState.DEFERRED],
    )


def write_evidence(bundle: EvidenceBundle, path: Path) -> None:
    text = json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Redacted again as a whole: a value can only be scrubbed if it is still in the environment.
    path.write_text(redact(text), encoding="utf-8")


# --------------------------------------------------------------------------------------------
# Bounded commands
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandOutcome:
    """A finished (or abandoned) command. `returncode` is None when it never produced one."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    tool_missing: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def summary(self) -> str:
        if self.tool_missing:
            return "tool not installed"
        if self.timed_out:
            return "timed out"
        text = (self.stderr.strip() or self.stdout.strip()).splitlines()
        return f"exit {self.returncode}: {text[-1][:200] if text else 'no output'}"


def run_bounded(
    command: list[str],
    *,
    timeout: float,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> CommandOutcome:
    """Run a command with a hard time bound; capture bounded, redacted output."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return CommandOutcome(None, "", f"{command[0]} not found", tool_missing=True)
    except subprocess.TimeoutExpired as expired:
        return CommandOutcome(
            None,
            _bounded(_text(expired.stdout)),
            _bounded(_text(expired.stderr)),
            timed_out=True,
        )
    return CommandOutcome(completed.returncode, _bounded(completed.stdout), _bounded(completed.stderr))


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


# Answers that mean the fact could not be read, as opposed to answers about the fact itself.
AUTH_MARKERS = (
    "http 401",
    "http 403",
    "authentication required",
    "authentication failed",
    "could not read username",
    "read:packages",
    "requires authentication",
    "bad credentials",
)
NETWORK_MARKERS = (
    "could not resolve host",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "timed out",
    "tls handshake",
    "temporary failure in name resolution",
    "cannot connect to the docker daemon",
)


def classify_failure(
    outcome: CommandOutcome, absent_markers: tuple[str, ...] = ()
) -> tuple[SurfaceState, str] | None:
    """State and failure class for a command that did not succeed; None when it succeeded.

    Only an answer matching a known absence response is MISSING. Auth and network markers are
    checked first, because a 403 that happens to contain "not found" in its help text is still an
    unread fact.
    """
    if outcome.tool_missing:
        return SurfaceState.UNREADABLE, "tool_unavailable"
    if outcome.timed_out:
        return SurfaceState.UNREADABLE, "network"
    if outcome.ok:
        return None
    said = f"{outcome.stderr}\n{outcome.stdout}".lower()
    if any(marker in said for marker in AUTH_MARKERS):
        return SurfaceState.UNREADABLE, "auth"
    if any(marker in said for marker in NETWORK_MARKERS):
        return SurfaceState.UNREADABLE, "network"
    if any(marker.lower() in said for marker in absent_markers):
        return SurfaceState.MISSING, "missing"
    return SurfaceState.UNREADABLE, "unclassified"


# --------------------------------------------------------------------------------------------
# Temporary state and isolation
# --------------------------------------------------------------------------------------------

_ROOT_PREFIX = "ignis-release-acceptance-"
_MARKER_NAME = ".ignis-release-acceptance-owner"


class TemporaryRoot:
    """A unique directory this run creates, owns, and removes -- and nothing else.

    Ownership is a random token written into a marker file. Cleanup deletes the tree only when the
    marker still holds that token, so a path reused or replaced by somebody else is left alone.
    """

    def __init__(self, parent: Path | None = None):
        self.parent = Path(parent) if parent else Path(tempfile.gettempdir())
        self.token = uuid.uuid4().hex
        self.path = self.parent / f"{_ROOT_PREFIX}{self.token[:12]}"
        self.marker = self.path / _MARKER_NAME

    def __enter__(self) -> TemporaryRoot:
        self.path.mkdir(parents=False, exist_ok=False)
        self.marker.write_text(self.token, encoding="utf-8")
        return self

    def owned(self) -> bool:
        try:
            return self.marker.read_text(encoding="utf-8") == self.token
        except OSError:
            return False

    def __exit__(self, *exc) -> None:
        if self.owned():
            shutil.rmtree(self.path, ignore_errors=True)


# The only ambient variables a clean-room child inherits. Everything else -- tokens, DSNs, env-file
# overrides, an activated virtualenv, a registry login -- is exactly what must not leak in.
_INHERITED_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "SYSTEMROOT")


def isolated_env(home: Path, *, docker_config: Path | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """An allowlisted child environment with its own home and no credential."""
    env = {name: os.environ[name] for name in _INHERITED_ENV if name in os.environ}
    env.setdefault("PATH", os.defpath)
    env.update(
        {
            "HOME": str(home),
            # Never prompt, and never consult the operator's global or system Git configuration,
            # which is where credential helpers live.
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHONNOUSERSITE": "1",
        }
    )
    if docker_config is not None:
        env["DOCKER_CONFIG"] = str(docker_config)
    if extra:
        env.update(extra)
    return env


# --------------------------------------------------------------------------------------------
# Shared MCP smoke
# --------------------------------------------------------------------------------------------

SCRIPTS = Path(__file__).resolve().parent
REFERENCE_TREE = SCRIPTS.parent


def _smoke_module():
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import wheel_mcp_smoke  # noqa: PLC0415

    return wheel_mcp_smoke


def _smoke_record(name: str, subject: str, command: list[str], *, env, cwd, timeout: float) -> SurfaceRecord:
    smoke = _smoke_module()
    try:
        result = smoke.run_smoke(command, env=env, cwd=cwd, response_timeout=timeout, exit_timeout=timeout)
    except smoke.SmokeFailure as failure:
        return SurfaceRecord(name, SurfaceState.FAILED, subject, str(failure), "behavior_mismatch")
    return SurfaceRecord(
        name,
        SurfaceState.VERIFIED,
        subject,
        f"MCP {result.protocol_version}: {result.tool_count} tools discovered, get_runtime_config "
        f"read {result.runtime_configs} configs, process exited when stdin closed",
    )


def _unread(name: str, subject: str, why: str) -> SurfaceRecord:
    """A downstream surface that cannot be judged because its input was never obtained."""
    return SurfaceRecord(name, SurfaceState.UNREADABLE, subject, why, "not_observed")


# --------------------------------------------------------------------------------------------
# Source mode
# --------------------------------------------------------------------------------------------

BOOTSTRAP_TIMEOUT_SECONDS = 900
GIT_TIMEOUT_SECONDS = 300
SOURCE_SMOKE_TIMEOUT_SECONDS = 120.0

# What `git` says when the repository or tag positively does not exist, as opposed to when it could
# not ask. Over HTTPS GitHub answers a nonexistent repository with an authentication prompt, which
# stays UNREADABLE: a prompt is not an answer about the repository.
GIT_ABSENT_MARKERS = (
    "repository not found",
    "does not appear to be a git repository",
    "remote branch v",
    "not found in upstream",
)

# Developer state a published tag must not carry: every user who clones it would inherit it.
INHERITED_STATE = (".venv", ".env", ".mcp.json", "ignis.db")

# The release inventory a tag must contain, read from the verified tree this script runs from.
# Patterns rather than names, so a new migration or template is required the day it is committed.
RELEASE_INVENTORY_PATTERNS = (
    "sql/[0-9][0-9][0-9]_*.sql",
    "src/ignis/infrastructure/templates/html/*.html",
    "src/ignis/application/use_cases/*qualification*.py",
    "server.json",
    "openclaw.json",
    "hermes_manifest.json",
    ".hermes/tools.json",
)

BOOTSTRAP_LOCKED_MARKER = "Installed the exact solution recorded in uv.lock."
FORBIDDEN_REGISTRATION_KEYS = ("DATABASE_URL", "IGNIS_ENCRYPTION_KEY", "YOUTUBE_API_KEY")


def check_public_url(url: str) -> None:
    """Refuse a clone URL that is not a plain public HTTPS address.

    Credentials in the URL would both authenticate the "anonymous" consumer and land in evidence.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"not a public HTTPS repository URL: {redact(url)!r}")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"a public repository URL carries no credentials, query or fragment: {redact(url)!r}")


def release_inventory(tree: Path) -> list[str]:
    found = set()
    for pattern in RELEASE_INVENTORY_PATTERNS:
        found.update(path.relative_to(tree).as_posix() for path in tree.glob(pattern) if path.is_file())
    return sorted(found)


def _migration_tables(migration: Path) -> list[str]:
    return re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", migration.read_text(encoding="utf-8"), re.IGNORECASE)


def _resolve_tag(repository: str, tag: str, env: dict) -> tuple[SurfaceRecord | None, str | None]:
    outcome = run_bounded(
        ["git", "ls-remote", "--tags", repository, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
        timeout=GIT_TIMEOUT_SECONDS,
        env=env,
    )
    subject = f"{repository} {tag}"
    failure = classify_failure(outcome, GIT_ABSENT_MARKERS)
    if failure:
        state, failure_class = failure
        return SurfaceRecord("source_tag_checkout", state, subject, outcome.summary, failure_class, outcome.returncode), None
    refs = dict(reversed(line.split("\t", 1)) for line in outcome.stdout.splitlines() if "\t" in line)
    commit = refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")
    if not commit:
        return SurfaceRecord("source_tag_checkout", SurfaceState.MISSING, subject, "the repository has no such tag", "missing", 0), None
    return None, commit


def _checkout_record(repository: str, tag: str, expected_commit: str | None, checkout: Path, env: dict) -> tuple[SurfaceRecord, bool]:
    """The source_tag_checkout record, and whether a usable checkout now exists."""
    unresolved, tag_commit = _resolve_tag(repository, tag, env)
    if unresolved:
        return unresolved, False

    subject = f"{repository} {tag}"
    outcome = run_bounded(
        ["git", "clone", "--quiet", "--depth", "1", "--single-branch", "--branch", tag, repository, str(checkout)],
        timeout=GIT_TIMEOUT_SECONDS,
        env=env,
    )
    failure = classify_failure(outcome, GIT_ABSENT_MARKERS)
    if failure:
        state, failure_class = failure
        return SurfaceRecord("source_tag_checkout", state, subject, outcome.summary, failure_class, outcome.returncode), False

    head = run_bounded(["git", "rev-parse", "HEAD"], timeout=30, env=env, cwd=checkout)
    resolved = head.stdout.strip() if head.ok else ""
    if resolved != tag_commit:
        return (
            SurfaceRecord(
                "source_tag_checkout",
                SurfaceState.FAILED,
                subject,
                f"tag {tag} advertises {tag_commit} but the clone checked out {resolved or 'nothing'}",
                "behavior_mismatch",
            ),
            False,
        )
    if not expected_commit:
        return (
            SurfaceRecord(
                "source_tag_checkout",
                SurfaceState.UNREADABLE,
                subject,
                f"tag {tag} resolved to {resolved}; no verified main commit was supplied to compare it with",
                "not_observed",
            ),
            True,
        )
    if resolved != expected_commit:
        return (
            SurfaceRecord(
                "source_tag_checkout",
                SurfaceState.FAILED,
                subject,
                f"tag {tag} resolved to {resolved}, not the verified main commit {expected_commit}",
                "behavior_mismatch",
            ),
            True,
        )
    return (
        SurfaceRecord(
            "source_tag_checkout",
            SurfaceState.VERIFIED,
            subject,
            f"exact-tag clone without credentials; {tag} resolved to the verified main commit {resolved}",
            command_exit=0,
        ),
        True,
    )


def _bootstrap_problems(checkout: Path, reference: Path, expected_migration: str | None) -> list[str]:
    """Everything wrong with a bootstrapped checkout, read from its own files and database."""
    import sqlite3

    problems = []
    missing = [name for name in release_inventory(reference) if not (checkout / name).is_file()]
    if missing:
        problems.append(f"the tag lacks release files the verified tree has: {missing}")

    migrations = sorted((checkout / "sql").glob("[0-9][0-9][0-9]_*.sql"))
    endpoint = migrations[-1].name[:3] if migrations else None
    if expected_migration and endpoint != expected_migration:
        problems.append(f"the packaged migration chain ends at {endpoint}, expected {expected_migration}")

    env_file = checkout / ".env"
    if not env_file.is_file() or "DATABASE_URL=sqlite:///ignis.db" not in env_file.read_text(encoding="utf-8"):
        problems.append("bootstrap did not write the SQLite default into .env")

    database = checkout / "ignis.db"
    if not database.is_file():
        problems.append("bootstrap created no SQLite database")
    elif migrations:
        with sqlite3.connect(database) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            seeded = (
                connection.execute("SELECT COUNT(*) FROM market_lexicons").fetchone()[0]
                if "market_lexicons" in tables
                else 0
            )
        absent = [table for table in _migration_tables(migrations[-1]) if table not in tables]
        if absent:
            problems.append(f"schema lacks the tables {migrations[-1].name} creates: {absent}")
        if not seeded:
            problems.append("schema holds no seed vocabulary in market_lexicons")

    registration = checkout / ".mcp.json"
    if not registration.is_file():
        problems.append("bootstrap registered no workspace MCP client")
    else:
        entry = json.loads(registration.read_text(encoding="utf-8")).get("mcpServers", {}).get("fn-ignis", {})
        copied = [key for key in FORBIDDEN_REGISTRATION_KEYS if key in json.dumps(entry)]
        if set(entry.get("env", {})) != {"IGNIS_ENV_FILE"} or copied:
            problems.append(f"the MCP registration carries more than a path to .env: {sorted(entry.get('env', {}))}")
    return problems


def observe_source(
    *,
    repository: str,
    version: str,
    expected_commit: str | None,
    root: Path,
    reference: Path = REFERENCE_TREE,
    expected_migration: str | None = None,
    passthrough_env: tuple[str, ...] = (),
    smoke_timeout: float = SOURCE_SMOKE_TIMEOUT_SECONDS,
) -> list[SurfaceRecord]:
    """Clone the exact tag, bootstrap it under an empty home, and talk MCP to the result."""
    tag = f"v{version}"
    home = root / "home"
    home.mkdir()
    checkout = root / "checkout"
    extra = {name: os.environ[name] for name in passthrough_env if name in os.environ}
    env = isolated_env(home, extra=extra)
    subject = f"{repository} {tag}"

    tag_record, cloned = _checkout_record(repository, tag, expected_commit, checkout, env)
    if not cloned:
        why = "the tagged source was not obtained"
        return [tag_record, _unread("source_bootstrap", subject, why), _unread("source_mcp_runtime", subject, why)]

    inherited = [name for name in INHERITED_STATE if (checkout / name).exists()]
    if inherited:
        bootstrap = SurfaceRecord(
            "source_bootstrap",
            SurfaceState.FAILED,
            subject,
            f"the tag ships developer state every clone would inherit: {inherited}",
            "behavior_mismatch",
        )
        return [tag_record, bootstrap, _unread("source_mcp_runtime", subject, "bootstrap did not pass")]

    outcome = run_bounded(["./scripts/bootstrap.sh"], timeout=BOOTSTRAP_TIMEOUT_SECONDS, env=env, cwd=checkout)
    output = f"{outcome.stdout}\n{outcome.stderr}"
    if outcome.timed_out or outcome.tool_missing:
        state, failure_class = classify_failure(outcome)
        bootstrap = SurfaceRecord("source_bootstrap", state, subject, outcome.summary, failure_class)
    elif not outcome.ok:
        bootstrap = SurfaceRecord(
            "source_bootstrap", SurfaceState.FAILED, subject, output.strip()[-3000:], "behavior_mismatch", outcome.returncode
        )
    elif BOOTSTRAP_LOCKED_MARKER not in output:
        bootstrap = SurfaceRecord(
            "source_bootstrap",
            SurfaceState.FAILED,
            subject,
            "bootstrap succeeded without the locked uv install:\n" + output.strip()[-2000:],
            "behavior_mismatch",
            outcome.returncode,
        )
    else:
        problems = _bootstrap_problems(checkout, reference, expected_migration)
        if problems:
            bootstrap = SurfaceRecord(
                "source_bootstrap", SurfaceState.FAILED, subject, "; ".join(problems), "behavior_mismatch", 0
            )
        else:
            migrations = sorted((checkout / "sql").glob("[0-9][0-9][0-9]_*.sql"))
            bootstrap = SurfaceRecord(
                "source_bootstrap",
                SurfaceState.VERIFIED,
                subject,
                f"locked install under an isolated home; SQLite schema through {migrations[-1].name} with "
                "seed vocabulary; workspace MCP registration carries only IGNIS_ENV_FILE",
                command_exit=0,
            )
    if bootstrap.state != SurfaceState.VERIFIED:
        return [tag_record, bootstrap, _unread("source_mcp_runtime", subject, "bootstrap did not pass")]

    server = [str(checkout / ".venv" / "bin" / "python"), "-m", "ignis.interfaces.mcp.server"]
    runtime_env = {**env, "IGNIS_ENV_FILE": str((checkout / ".env").resolve())}
    runtime = _smoke_record("source_mcp_runtime", subject, server, env=runtime_env, cwd=str(checkout), timeout=smoke_timeout)
    return [tag_record, bootstrap, runtime]


# --------------------------------------------------------------------------------------------
# Container mode
# --------------------------------------------------------------------------------------------

SOURCE_REPOSITORY_URL = "https://github.com/fioenix/fn-ignis"
SOURCE_LABEL = "org.opencontainers.image.source"
MCP_NAME_LABEL = "io.modelcontextprotocol.server.name"
REGISTRY_TIMEOUT_SECONDS = 60
PULL_TIMEOUT_SECONDS = 900
CONTAINER_SMOKE_TIMEOUT_SECONDS = 180.0
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
DOCKER_ABSENT_MARKERS = ("unauthorized", "denied", "manifest unknown", "not found")


class RegistryAnswer(Exception):
    """The registry answered, and the answer is not the object asked for."""

    def __init__(self, status: int, what: str):
        # "(HTTP n)" rather than ": HTTP n": after a word like "token", a colon reads as a secret
        # assignment to the redactor and the status would be blanked out of the evidence.
        super().__init__(f"{what} (HTTP {status})")
        self.status = status


class RegistryProtocolError(Exception):
    """The registry control plane answered, but its response could not be interpreted safely."""


class RegistryArtifactError(Exception):
    """The registry returned an OCI object whose bytes are not a valid manifest."""


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    _stream: object = None
    body: bytes = b""

    def chunks(self):
        if self._stream is None:
            yield self.body
            return
        try:
            while chunk := self._stream.read(1 << 20):
                yield chunk
        finally:
            self._stream.close()


def http_fetch(url: str, headers: dict[str, str]) -> HttpResponse:
    """GET without ambient credentials, following redirects by hand.

    urllib forwards an Authorization header across a redirect. Blob downloads redirect to object
    storage on another host, where a stray bearer token is at best refused, so it is dropped the
    moment the host changes.
    """
    from urllib.error import HTTPError
    from urllib.parse import urljoin, urlsplit
    from urllib.request import HTTPRedirectHandler, Request, build_opener

    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = build_opener(_NoRedirect)
    current, current_headers = url, dict(headers)
    for _ in range(6):
        try:
            response = opener.open(Request(current, headers=current_headers), timeout=REGISTRY_TIMEOUT_SECONDS)
        except HTTPError as error:
            if error.code in (301, 302, 303, 307, 308) and error.headers.get("Location"):
                target = urljoin(current, error.headers["Location"])
                if urlsplit(target).netloc != urlsplit(current).netloc:
                    current_headers.pop("Authorization", None)
                current = target
                error.close()
                continue
            body = error.read()
            error.close()
            return HttpResponse(error.code, {k.lower(): v for k, v in error.headers.items()}, body=body)
        return HttpResponse(response.status, {k.lower(): v for k, v in response.headers.items()}, response)
    raise OSError(f"too many redirects fetching {redact(url)}")


class AnonymousRegistry:
    """The OCI distribution protocol, as a client with no credential sees it."""

    def __init__(self, image: str, fetch=http_fetch):
        host, _, self.path = image.partition("/")
        self.base = f"https://{host}"
        self.fetch = fetch
        self.token: str | None = None
        self.requested_token = False

    def _authorize(self, challenge: str) -> None:
        from urllib.parse import urlencode

        fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        if not challenge.lower().startswith("bearer") or "realm" not in fields or self.requested_token:
            raise RegistryAnswer(401, "the registry refused the anonymous consumer")
        self.requested_token = True
        query = urlencode({key: fields[key] for key in ("service", "scope") if key in fields})
        answer = self.fetch(f"{fields['realm']}?{query}", {})
        if answer.status != 200:
            raise RegistryAnswer(answer.status, "the registry issued no anonymous pull token")
        try:
            document = json.loads(b"".join(answer.chunks()) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RegistryProtocolError("the anonymous token response was malformed") from error
        if not isinstance(document, dict):
            raise RegistryProtocolError("the anonymous token response was not an object")
        self.token = document.get("token") or None
        if not self.token:
            raise RegistryAnswer(401, "the registry issued no anonymous pull token")

    def get(self, kind: str, reference: str, accept: str | None = None) -> HttpResponse:
        url = f"{self.base}/v2/{self.path}/{kind}/{reference}"
        for _ in range(2):
            headers = {"Accept": accept} if accept else {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            answer = self.fetch(url, headers)
            if answer.status == 401 and not self.token:
                self._authorize(answer.headers.get("www-authenticate", ""))
                continue
            return answer
        return answer

    def manifest(self, reference: str) -> tuple[str, dict]:
        answer = self.get("manifests", reference, MANIFEST_ACCEPT)
        if answer.status != 200:
            raise RegistryAnswer(answer.status, f"manifest {reference}")
        body = b"".join(answer.chunks())
        digest = answer.headers.get("docker-content-digest") or "sha256:" + hashlib.sha256(body).hexdigest()
        try:
            document = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RegistryArtifactError(f"manifest {reference} was malformed") from error
        if not isinstance(document, dict):
            raise RegistryArtifactError(f"manifest {reference} was not an object")
        return digest, document

    def blob(self, digest: str) -> bytes | int:
        """The blob's bytes after verifying their digest, or the failing HTTP status (0: digest mismatch)."""
        answer = self.get("blobs", digest)
        if answer.status != 200:
            return answer.status
        hasher = hashlib.sha256()
        kept = bytearray()
        for chunk in answer.chunks():
            hasher.update(chunk)
            if len(kept) < 1 << 20:
                kept.extend(chunk)
        return bytes(kept) if f"sha256:{hasher.hexdigest()}" == digest else 0


def _host_platform() -> str:
    import platform as host

    machine = host.machine().lower()
    return "linux/arm64" if machine in ("arm64", "aarch64") else "linux/amd64"


def _select_platform(index: dict, requested: str | None) -> tuple[str, str] | None:
    """(platform, manifest digest) to pull: the requested one, the only runnable one, or the host's."""
    runnable = {}
    for entry in index.get("manifests", []):
        platform = entry.get("platform", {})
        if platform.get("os") in (None, "unknown"):
            continue
        name = f"{platform['os']}/{platform['architecture']}" + (f"/{platform['variant']}" if platform.get("variant") else "")
        runnable[name] = entry["digest"]
    if requested:
        return (requested, runnable[requested]) if requested in runnable else None
    if len(runnable) == 1:
        return next(iter(runnable.items()))
    host = _host_platform()
    return (host, runnable[host]) if host in runnable else None


def _expected_tags(version: str) -> list[str]:
    """The tags one release event must move: the exact version, plus major.minor and latest when stable."""
    match = SEMVER.fullmatch(version)
    if match.group(4):
        return [version]
    return [version, f"{match.group(1)}.{match.group(2)}", "latest"]


def _docker(docker: str, args: list[str], env: dict, timeout: float) -> CommandOutcome:
    return run_bounded([docker, *args], timeout=timeout, env=env)


def _expected_mcp_name(reference: Path) -> str | None:
    try:
        return json.loads((reference / "server.json").read_text(encoding="utf-8")).get("name")
    except (OSError, json.JSONDecodeError):
        return None


def _registry_pull(
    registry: AnonymousRegistry, image: str, version: str, platform: str | None
) -> tuple[SurfaceRecord | None, dict]:
    """Fetch tag, platform manifest, config and every layer anonymously. Returns (problem, facts)."""
    subject = f"{image}:{version}"
    facts: dict = {}
    try:
        index_digest, index = registry.manifest(version)
    except RegistryAnswer as answer:
        if answer.status in (401, 403, 404):
            return SurfaceRecord("container_anonymous_pull", SurfaceState.MISSING, subject,
                                 f"{answer}: the anonymous consumer cannot obtain the release tag", "missing"), facts
        failure_class = "auth" if answer.status == 429 else "unclassified"
        return SurfaceRecord("container_anonymous_pull", SurfaceState.UNREADABLE, subject,
                             f"{answer}: the registry did not provide a conclusive release-tag answer",
                             failure_class), facts
    except RegistryProtocolError as error:
        return SurfaceRecord("container_anonymous_pull", SurfaceState.UNREADABLE, subject,
                             str(error), "unclassified"), facts
    except RegistryArtifactError as error:
        return SurfaceRecord("container_anonymous_pull", SurfaceState.FAILED, subject,
                             str(error), "behavior_mismatch"), facts
    facts["digest"] = index_digest
    try:
        selected = _select_platform(index, platform) if "manifests" in index else None
    except (KeyError, TypeError) as error:
        return SurfaceRecord("container_anonymous_pull", SurfaceState.FAILED, subject,
                             f"the release index has an invalid platform entry: {error}",
                             "behavior_mismatch"), facts
    if "manifests" in index:
        if not selected:
            return SurfaceRecord("container_anonymous_pull", SurfaceState.FAILED, subject,
                                 f"no runnable platform{f' {platform}' if platform else ''} in {index_digest}",
                                 "behavior_mismatch"), facts
        facts["platform"], manifest_digest = selected
        try:
            _, manifest = registry.manifest(manifest_digest)
        except RegistryAnswer as answer:
            if answer.status == 429 or answer.status >= 500:
                return SurfaceRecord("container_anonymous_pull", SurfaceState.UNREADABLE, subject,
                                     f"the index resolved but its {facts['platform']} manifest was unreadable: {answer}",
                                     "auth" if answer.status == 429 else "unclassified"), facts
            return SurfaceRecord("container_anonymous_pull", SurfaceState.FAILED, subject,
                                 f"the index resolved but its {facts['platform']} manifest did not: {answer}",
                                 "behavior_mismatch"), facts
        except RegistryProtocolError as error:
            return SurfaceRecord("container_anonymous_pull", SurfaceState.UNREADABLE, subject,
                                 str(error), "unclassified"), facts
        except RegistryArtifactError as error:
            return SurfaceRecord("container_anonymous_pull", SurfaceState.FAILED, subject,
                                 str(error), "behavior_mismatch"), facts
    else:
        manifest = index
        facts["platform"] = platform or _host_platform()

    try:
        blobs = [manifest["config"]["digest"], *(layer["digest"] for layer in manifest.get("layers", []))]
    except (KeyError, TypeError) as error:
        return SurfaceRecord("container_anonymous_pull", SurfaceState.FAILED, subject,
                             f"the selected image manifest has an invalid blob list: {error}",
                             "behavior_mismatch"), facts
    refused = []
    unreadable = []
    for digest in blobs:
        got = registry.blob(digest)
        if isinstance(got, int):
            detail = f"{digest} ({'bytes do not match the digest' if got == 0 else f'HTTP {got}'})"
            (unreadable if got == 429 or got >= 500 else refused).append(detail)
        elif digest == blobs[0]:
            try:
                facts["labels"] = (json.loads(got).get("config") or {}).get("Labels") or {}
            except json.JSONDecodeError:
                facts["labels"] = {}
    if unreadable:
        return SurfaceRecord("container_anonymous_pull", SurfaceState.UNREADABLE, subject,
                             f"the registry could not conclusively return these blobs: {unreadable}",
                             "unclassified"), facts
    if refused:
        return SurfaceRecord("container_anonymous_pull", SurfaceState.FAILED, subject,
                             f"the manifest resolved anonymously but these blobs did not download intact: {refused}",
                             "behavior_mismatch"), facts
    facts["blob_count"] = len(blobs)
    return None, facts


def observe_container(
    *,
    image: str,
    version: str,
    root: Path,
    reference: Path = REFERENCE_TREE,
    platform: str | None = None,
    source_url: str = SOURCE_REPOSITORY_URL,
    fetch=http_fetch,
    docker: str = "docker",
    passthrough_env: tuple[str, ...] = (),
    smoke_timeout: float = CONTAINER_SMOKE_TIMEOUT_SECONDS,
    check_worker: bool = False,
) -> list[SurfaceRecord]:
    """Pull the release image as a stranger would, check what it is, and talk MCP to it.

    With `check_worker`, the Compose worker role is then started on the same pulled digest before
    the image is cleaned up; without a verified anonymous pull there is nothing to run, and the
    role is recorded as unread.
    """
    subject = f"{image}:{version}"
    docker_config = root / "docker-config"
    docker_config.mkdir()
    (docker_config / "config.json").write_text("{}\n", encoding="utf-8")
    home = root / "home"
    home.mkdir(exist_ok=True)
    extra = {name: os.environ[name] for name in passthrough_env if name in os.environ}
    env = isolated_env(home, docker_config=docker_config, extra=extra)

    def downstream(why: str) -> list[SurfaceRecord]:
        unread = [_unread("container_digest", subject, why), _unread("container_mcp_runtime", subject, why)]
        if check_worker:
            unread.append(_unread("compose_worker_override", subject, why))
        return unread

    registry = AnonymousRegistry(image, fetch)
    try:
        problem, facts = _registry_pull(registry, image, version, platform)
    except OSError as error:
        record = SurfaceRecord("container_anonymous_pull", SurfaceState.UNREADABLE, subject,
                               f"the registry could not be reached: {error}", "network")
        return [record, *downstream("the registry could not be reached")]
    if problem:
        return [problem, *downstream("the image was not obtained anonymously")]

    selected = facts["platform"]
    digest_subject = f"{image}@{facts['digest']}"
    before = _docker(docker, ["image", "inspect", digest_subject, "--format", "{{json .RepoDigests}}"], env, 60)
    preexisting = before.ok
    pulled = _docker(docker, ["pull", "--platform", selected, digest_subject], env, PULL_TIMEOUT_SECONDS)
    try:
        failure = classify_failure(pulled, DOCKER_ABSENT_MARKERS)
        if failure:
            state, failure_class = failure
            record = SurfaceRecord("container_anonymous_pull", state, subject,
                                   f"docker pull with an empty credential store: {pulled.summary}",
                                   failure_class, pulled.returncode)
            return [record, *downstream("the daemon did not pull the image anonymously")]
        pulled_digest = next(iter(re.findall(r"Digest:\s*(sha256:[0-9a-f]{64})", pulled.stdout)), None)
        pull_record = SurfaceRecord(
            "container_anonymous_pull",
            SurfaceState.VERIFIED,
            f"{image}@{facts['digest']}",
            f"no credential: anonymous token, {selected} manifest, config and all {facts['blob_count'] - 1} "
            f"layers downloaded and digest-verified; docker pull with an empty DOCKER_CONFIG succeeded",
            command_exit=0,
        )

        digest_problems, digest_missing = [], []
        if pulled_digest != facts["digest"]:
            digest_problems.append(f"docker pulled {pulled_digest}, the registry tag names {facts['digest']}")
        tag_digests = {}
        for tag in _expected_tags(version):
            try:
                tag_digests[tag] = registry.manifest(tag)[0]
            except RegistryAnswer as answer:
                digest_missing.append(f"{tag}: {answer}")
        moved_elsewhere = [f"{tag} -> {digest}" for tag, digest in tag_digests.items() if digest != facts["digest"]]
        if moved_elsewhere:
            digest_problems.append(f"tags resolve to another digest: {moved_elsewhere}")
        labels = facts.get("labels", {})
        expected_name = _expected_mcp_name(reference)
        if labels.get(SOURCE_LABEL) != source_url:
            digest_problems.append(f"{SOURCE_LABEL} is {labels.get(SOURCE_LABEL)!r}, expected {source_url!r}")
        if not expected_name or labels.get(MCP_NAME_LABEL) != expected_name:
            digest_problems.append(f"{MCP_NAME_LABEL} is {labels.get(MCP_NAME_LABEL)!r}, expected {expected_name!r}")
        if digest_problems:
            digest_record = SurfaceRecord("container_digest", SurfaceState.FAILED, digest_subject,
                                          "; ".join(digest_problems + digest_missing), "behavior_mismatch")
        elif digest_missing:
            digest_record = SurfaceRecord("container_digest", SurfaceState.MISSING, digest_subject,
                                          f"release tags absent: {digest_missing}", "missing")
        else:
            digest_record = SurfaceRecord(
                "container_digest",
                SurfaceState.VERIFIED,
                digest_subject,
                f"tags {sorted(tag_digests)} all resolve to {facts['digest']}; {SOURCE_LABEL}={source_url}; "
                f"{MCP_NAME_LABEL}={expected_name}",
            )

        runtime = _smoke_record(
            "container_mcp_runtime",
            digest_subject,
            [docker, "run", "--rm", "-i", "--pull", "never", "--platform", selected, digest_subject],
            env=env,
            cwd=None,
            timeout=smoke_timeout,
        )
        records = [pull_record, digest_record, runtime]
        if check_worker:
            records.append(
                observe_compose_worker(
                    image_ref=digest_subject,
                    root=root,
                    reference=reference,
                    docker=docker,
                    platform=selected,
                    passthrough_env=passthrough_env,
                )
            )
        return records
    finally:
        if not preexisting and pulled.ok:
            _docker(docker, ["image", "rm", digest_subject], env, 120)


# --------------------------------------------------------------------------------------------
# The Compose worker role
# --------------------------------------------------------------------------------------------

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")
PRODUCTION_COMPOSE = "docker-compose.prod.yml"
SCHEDULER_COMMAND = ["python", "-m", "ignis.interfaces.cli.scheduler"]
SCHEDULER_STARTED_MARKER = "Starting fn-ignis Worker Scheduler"
COMPOSE_UP_TIMEOUT_SECONDS = 900
WORKER_OBSERVE_SECONDS = 90


def _operator_cli_plugins() -> list[str]:
    """Where the operator's Docker CLI plugins live. Compose is one of them.

    The CLI finds user plugins under $DOCKER_CONFIG/cli-plugins, so an isolated DOCKER_CONFIG hides
    `docker compose`. The directory holds executables, not credentials, so naming it is safe.
    """
    base = Path(os.environ.get("DOCKER_CONFIG") or Path.home() / ".docker")
    plugins = base / "cli-plugins"
    return [str(plugins)] if plugins.is_dir() else []


def _compose_worker_command(docker: str, compose_file: Path, override: Path, env: dict) -> tuple[list | None, CommandOutcome]:
    """The worker command Compose itself resolves, not a YAML reading of it."""
    outcome = _docker(
        docker,
        ["compose", "-f", str(compose_file), "-f", str(override), "config", "--format", "json"],
        env,
        120,
    )
    if not outcome.ok:
        return None, outcome
    try:
        worker = json.loads(outcome.stdout).get("services", {}).get("worker", {})
    except json.JSONDecodeError:
        return None, outcome
    return worker.get("command"), outcome


def observe_compose_worker(
    *,
    image_ref: str,
    root: Path,
    reference: Path = REFERENCE_TREE,
    docker: str = "docker",
    platform: str | None = None,
    passthrough_env: tuple[str, ...] = (),
    settle_seconds: float = 5,
    observe_seconds: float = WORKER_OBSERVE_SECONDS,
) -> SurfaceRecord:
    """Both Compose files select the scheduler, and the production worker really runs it."""
    import secrets
    import time

    subject = f"{PRODUCTION_COMPOSE} worker on {image_ref}"
    run_dir = root / "compose"
    run_dir.mkdir()
    docker_config = root / "compose-docker-config"
    docker_config.mkdir()
    # No auths, no credsStore: only where the compose plugin is.
    (docker_config / "config.json").write_text(
        json.dumps({"cliPluginsExtraDirs": _operator_cli_plugins()}) + "\n", encoding="utf-8"
    )
    extra = {name: os.environ[name] for name in passthrough_env if name in os.environ}
    env = isolated_env(root / "home", docker_config=docker_config, extra=extra)

    # Only what isolation needs: a unique project and names, no published ports, no restart, no
    # operator env file, and the image under test instead of the moving `latest`.
    project = f"ignis-accept-{uuid.uuid4().hex[:8]}"
    worker = f"{project}-worker"
    override = run_dir / "override.yml"
    override.write_text(
        "services:\n"
        "  db:\n"
        f"    container_name: {project}-db\n"
        "    ports: !reset []\n"
        '    restart: "no"\n'
        "  worker:\n"
        f"    image: {image_ref}\n"
        "    pull_policy: never\n"
        f"    container_name: {worker}\n"
        '    restart: "no"\n'
        "    env_file: !reset []\n"
        + (f"    platform: {platform}\n" if platform else "")
        + "  reports:\n"
        f"    container_name: {project}-reports\n"
        "    ports: !reset []\n"
        '    restart: "no"\n',
        encoding="utf-8",
    )

    # Resolving the command needs only the worker, which is the one service both files define.
    config_override = run_dir / "config-override.yml"
    config_override.write_text("services:\n  worker:\n    env_file: !reset []\n", encoding="utf-8")
    wrong = []
    for name in COMPOSE_FILES:
        command, outcome = _compose_worker_command(docker, reference / name, config_override, env)
        failure = classify_failure(outcome)
        if failure and failure[1] in ("network", "tool_unavailable"):
            return SurfaceRecord("compose_worker_override", failure[0], subject,
                                 f"docker compose config for {name}: {outcome.summary}", failure[1], outcome.returncode)
        if not outcome.ok:
            return SurfaceRecord("compose_worker_override", SurfaceState.FAILED, subject,
                                 f"docker compose could not resolve {name}: {outcome.summary}",
                                 "behavior_mismatch", outcome.returncode)
        if command != SCHEDULER_COMMAND:
            wrong.append(f"{name} worker command resolves to {command!r}")
    if wrong:
        return SurfaceRecord("compose_worker_override", SurfaceState.FAILED, subject,
                             "; ".join(wrong) + f"; expected {SCHEDULER_COMMAND}", "behavior_mismatch")

    env_file = run_dir / "compose.env"
    env_file.write_text(
        f"POSTGRES_USER=postgres\nPOSTGRES_DB=ignis\nPOSTGRES_PASSWORD={secrets.token_hex(24)}\n", encoding="utf-8"
    )
    env_file.chmod(0o600)
    compose = [
        "compose", "-p", project, "--env-file", str(env_file),
        "-f", str(reference / PRODUCTION_COMPOSE), "-f", str(override),
    ]
    try:
        up = _docker(docker, [*compose, "up", "-d", "worker"], env, COMPOSE_UP_TIMEOUT_SECONDS)
        failure = classify_failure(up)
        if failure:
            state, failure_class = failure
            if state == SurfaceState.MISSING or failure_class == "unclassified":
                state, failure_class = SurfaceState.FAILED, "behavior_mismatch"
            return SurfaceRecord("compose_worker_override", state, subject,
                                 f"docker compose up worker: {up.summary}", failure_class, up.returncode)

        time.sleep(settle_seconds)
        deadline = time.monotonic() + observe_seconds
        status = processes = logs = ""
        while True:
            status = _docker(docker, ["inspect", "-f", "{{.State.Status}}", worker], env, 30).stdout.strip()
            processes = _docker(docker, ["top", worker], env, 30).stdout if status == "running" else ""
            logged = _docker(docker, ["logs", worker], env, 30)
            logs = f"{logged.stdout}\n{logged.stderr}"
            if (SCHEDULER_STARTED_MARKER in logs and "ignis.interfaces.cli.scheduler" in processes) or status not in (
                "running",
                "created",
                "restarting",
            ):
                break
            if time.monotonic() > deadline:
                break
            time.sleep(min(3, observe_seconds))

        if status == "running" and "ignis.interfaces.cli.scheduler" in processes and SCHEDULER_STARTED_MARKER in logs:
            return SurfaceRecord(
                "compose_worker_override",
                SurfaceState.VERIFIED,
                subject,
                f"both Compose files resolve the worker command to {SCHEDULER_COMMAND}; the production worker "
                f"is running `python -m ignis.interfaces.cli.scheduler` and logged '{SCHEDULER_STARTED_MARKER}'",
            )
        return SurfaceRecord(
            "compose_worker_override",
            SurfaceState.FAILED,
            subject,
            f"worker state {status!r}; processes: {processes.strip()[-400:]!r}; log tail: {logs.strip()[-800:]!r}",
            "behavior_mismatch",
        )
    finally:
        _docker(docker, [*compose, "down", "-v", "--remove-orphans"], env, 300)
        env_file.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------
# GitHub facts, version parity, provenance and registry validation
# --------------------------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
PUBLISH_WORKFLOW = "docker-publish.yml"
PROVENANCE_TIMEOUT_SECONDS = 300


def _owner_repo(repository: str) -> str:
    from urllib.parse import urlsplit

    path = urlsplit(repository).path.strip("/")
    return path[:-4] if path.endswith(".git") else path


def _api(fetch, url: str) -> tuple[int, dict | None, str]:
    """(status, JSON body or None, message). Anonymous: no Authorization header is ever sent."""
    answer = fetch(url, {"Accept": "application/vnd.github+json"})
    raw = b"".join(answer.chunks())
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = None
    message = body.get("message", "") if isinstance(body, dict) else ""
    return answer.status, body, message


def _api_failure(name: str, subject: str, status: int, message: str) -> SurfaceRecord:
    """404 is GitHub positively saying the object is not there for an anonymous reader."""
    if status == 404:
        return SurfaceRecord(name, SurfaceState.MISSING, subject, f"GitHub answered 404 ({message})", "missing")
    failure_class = "auth" if status in (401, 403, 429) else "unclassified"
    return SurfaceRecord(name, SurfaceState.UNREADABLE, subject, f"GitHub answered HTTP {status}: {message}", failure_class)


def observe_github(*, repository: str, version: str, expected_commit: str | None, fetch=http_fetch) -> list[SurfaceRecord]:
    """Repository visibility, tag on main, the published Release and the publish workflow, read anonymously."""
    slug = _owner_repo(repository)
    base = f"{GITHUB_API}/repos/{slug}"
    tag = f"v{version}"
    records: list[SurfaceRecord] = []

    def guarded(name: str, subject: str, observe) -> SurfaceRecord:
        try:
            return observe()
        except OSError as error:
            return SurfaceRecord(name, SurfaceState.UNREADABLE, subject, f"GitHub could not be reached: {error}", "network")

    def repository_public() -> SurfaceRecord:
        status, body, message = _api(fetch, base)
        if status != 200:
            return _api_failure("repository_public", slug, status, message)
        if body.get("private") is False:
            return SurfaceRecord("repository_public", SurfaceState.VERIFIED, slug, "an anonymous reader sees a public repository")
        return SurfaceRecord("repository_public", SurfaceState.MISSING, slug, "the repository is not public", "missing")

    tag_commit: list[str] = []

    def tag_on_main() -> SurfaceRecord:
        subject = f"{slug} {tag}"
        status, body, message = _api(fetch, f"{base}/git/ref/tags/{tag}")
        if status != 200:
            return _api_failure("tag_on_main", subject, status, message)
        target = body.get("object", {})
        if target.get("type") != "tag":
            return SurfaceRecord("tag_on_main", SurfaceState.FAILED, subject,
                                 f"{tag} is a lightweight tag; the release contract requires an annotated tag",
                                 "behavior_mismatch")
        status, body, message = _api(fetch, f"{base}/git/tags/{target.get('sha')}")
        if status != 200:
            return _api_failure("tag_on_main", subject, status, message)
        target = body.get("object", {})
        if target.get("type") != "commit":
            return SurfaceRecord("tag_on_main", SurfaceState.FAILED, subject,
                                 f"the annotated tag targets {target.get('type')!r}, not a commit",
                                 "behavior_mismatch")
        commit = target.get("sha", "")
        tag_commit.append(commit)
        if expected_commit and commit != expected_commit:
            return SurfaceRecord("tag_on_main", SurfaceState.FAILED, subject,
                                 f"{tag} names {commit}, not the verified main commit {expected_commit}", "behavior_mismatch")
        status, body, message = _api(fetch, f"{base}/compare/{commit}...main")
        if status != 200:
            return _api_failure("tag_on_main", subject, status, message)
        if body.get("behind_by") != 0:
            return SurfaceRecord("tag_on_main", SurfaceState.FAILED, subject,
                                 f"{commit} is not an ancestor of main (compare status {body.get('status')!r})",
                                 "behavior_mismatch")
        if not expected_commit:
            return SurfaceRecord("tag_on_main", SurfaceState.UNREADABLE, subject,
                                 f"{tag} names {commit} on main; no verified main commit was supplied to compare it with",
                                 "not_observed")
        return SurfaceRecord("tag_on_main", SurfaceState.VERIFIED, subject, f"{tag} names {commit}, which is on main")

    def release_published() -> SurfaceRecord:
        subject = f"{slug} Release {tag}"
        status, body, message = _api(fetch, f"{base}/releases/tags/{tag}")
        if status != 200:
            return _api_failure("github_release_published", subject, status, message)
        if body.get("draft") or not body.get("published_at"):
            return SurfaceRecord("github_release_published", SurfaceState.MISSING, subject, "the Release is a draft", "missing")
        return SurfaceRecord("github_release_published", SurfaceState.VERIFIED, body.get("html_url", subject),
                             f"published {body.get('published_at')}")

    def workflow() -> SurfaceRecord:
        subject = f"{slug} {PUBLISH_WORKFLOW} for {tag}"
        status, body, message = _api(
            fetch, f"{base}/actions/workflows/{PUBLISH_WORKFLOW}/runs?branch={tag}&event=push&per_page=5"
        )
        if status != 200:
            return _api_failure("container_workflow", subject, status, message)
        runs = body.get("workflow_runs", [])
        if not runs:
            return SurfaceRecord("container_workflow", SurfaceState.MISSING, subject, "no tag-driven publish run exists", "missing")
        run = runs[0]
        commit = tag_commit[0] if tag_commit else expected_commit
        if run.get("status") != "completed":
            return SurfaceRecord("container_workflow", SurfaceState.UNREADABLE, run.get("html_url", subject),
                                 f"the newest run is still {run.get('status')}", "unclassified")
        if run.get("conclusion") != "success":
            return SurfaceRecord("container_workflow", SurfaceState.FAILED, run.get("html_url", subject),
                                 f"the newest run concluded {run.get('conclusion')}", "behavior_mismatch")
        if commit and run.get("head_sha") != commit:
            return SurfaceRecord("container_workflow", SurfaceState.FAILED, run.get("html_url", subject),
                                 f"the run built {run.get('head_sha')}, not the tag commit {commit}", "behavior_mismatch")
        return SurfaceRecord("container_workflow", SurfaceState.VERIFIED, run.get("html_url", subject),
                             f"tag-driven publish succeeded on {run.get('head_sha')}")

    records.append(guarded("repository_public", slug, repository_public))
    records.append(guarded("tag_on_main", f"{slug} {tag}", tag_on_main))
    records.append(guarded("github_release_published", f"{slug} Release {tag}", release_published))
    records.append(guarded("container_workflow", f"{slug} {PUBLISH_WORKFLOW}", workflow))
    return records


def version_carriers(tree: Path) -> dict[str, str | None]:
    """Every release-controlled version value in a tree, each read with its own file's grammar."""
    import tomllib

    def text(relative: str) -> str:
        return (tree / relative).read_text(encoding="utf-8")

    def yaml_version(relative: str) -> str | None:
        found = re.search(r"^version:\s*['\"]?([^\s'\"]+)", text(relative), re.MULTILINE)
        return found.group(1) if found else None

    manifest = json.loads(text("server.json"))
    oci = [p for p in manifest.get("packages", []) if p.get("registryType") == "oci"]
    identifier = oci[0].get("identifier", "") if len(oci) == 1 else ""
    banner = re.search(r"\*\*Phiên bản:\*\*\s*`v([^`]+)`", text("BACKLOG.md").split("\n---", 1)[0])
    locked = [p["version"] for p in tomllib.loads(text("uv.lock")).get("package", []) if p.get("name") == "fn-ignis"]
    return {
        "pyproject.toml": tomllib.loads(text("pyproject.toml"))["project"]["version"],
        "openclaw.json": json.loads(text("openclaw.json")).get("version"),
        "server.json version": manifest.get("version"),
        "server.json package version": oci[0].get("version") if len(oci) == 1 else None,
        "server.json OCI identifier tag": identifier.rsplit(":", 1)[1] if ":" in identifier.rsplit("/", 1)[-1] else None,
        "CITATION.cff": yaml_version("CITATION.cff"),
        ".openclaw/config.yaml": yaml_version(".openclaw/config.yaml"),
        "BACKLOG.md banner": banner.group(1) if banner else None,
        "uv.lock": locked[0] if len(locked) == 1 else None,
    }


def observe_version_parity(tree: Path | None, version: str) -> SurfaceRecord:
    subject = f"release carriers at v{version}"
    if tree is None or not (tree / "pyproject.toml").is_file():
        return _unread("version_parity", subject, "no tagged source tree to read")
    try:
        carriers = version_carriers(tree)
    except (OSError, ValueError, KeyError) as error:
        return SurfaceRecord("version_parity", SurfaceState.FAILED, subject, f"a carrier could not be parsed: {error}",
                             "behavior_mismatch")
    wrong = {name: value for name, value in carriers.items() if value != version}
    if wrong:
        return SurfaceRecord("version_parity", SurfaceState.FAILED, subject, f"carriers disagree with {version}: {wrong}",
                             "behavior_mismatch")
    return SurfaceRecord("version_parity", SurfaceState.VERIFIED, subject, f"all {len(carriers)} carriers read {version}")


def observe_provenance(
    *, image: str, digest: str | None, version: str, repository: str, expected_commit: str | None, gh: str = "gh"
) -> SurfaceRecord:
    """Authenticated, and deliberately separate from the anonymous consumer: it uses the operator's gh."""
    if not digest:
        return _unread("container_provenance", f"{image}:{version}", "no anonymously verified digest to check")
    slug = _owner_repo(repository)
    subject = f"{image}@{digest}"
    command = [
        gh, "attestation", "verify", f"oci://{subject}",
        "--repo", slug,
        "--source-ref", f"refs/tags/v{version}",
        "--signer-workflow", f"{slug}/.github/workflows/{PUBLISH_WORKFLOW}",
    ]
    if expected_commit:
        command += ["--source-digest", expected_commit]
    outcome = run_bounded(command, timeout=PROVENANCE_TIMEOUT_SECONDS)
    failure = classify_failure(outcome, ("no attestations found",))
    if failure:
        state, failure_class = failure
        if failure_class == "unclassified":
            state, failure_class = SurfaceState.FAILED, "behavior_mismatch"
        return SurfaceRecord("container_provenance", state, subject, outcome.summary, failure_class, outcome.returncode)
    return SurfaceRecord("container_provenance", SurfaceState.VERIFIED, subject,
                         f"gh attestation verify constrained to {slug}, refs/tags/v{version} and {PUBLISH_WORKFLOW}"
                         + (f" at {expected_commit}" if expected_commit else ""), command_exit=0)


def observe_registry_validation(
    tree: Path, *, publisher: str = "mcp-publisher", passthrough_env: tuple[str, ...] = ()
) -> SurfaceRecord:
    """`mcp-publisher validate` on the tagged server.json, with the publisher version recorded.

    It runs under an empty home so no publisher login redirects validation to another registry.
    """
    subject = str(tree / "server.json")
    (tree.parent / "publisher-home").mkdir(exist_ok=True)
    extra = {name: os.environ[name] for name in passthrough_env if name in os.environ}
    env = isolated_env(tree.parent / "publisher-home", extra=extra)
    version = run_bounded([publisher, "--version"], timeout=60, env=env, cwd=tree)
    if version.tool_missing:
        return SurfaceRecord("mcp_registry_validation", SurfaceState.UNREADABLE, subject,
                             "mcp-publisher is not installed", "tool_unavailable")
    outcome = run_bounded([publisher, "validate"], timeout=300, env=env, cwd=tree)
    failure = classify_failure(outcome)
    publisher_version = (version.stdout.strip() or version.stderr.strip()).splitlines()[:1]
    if failure:
        state, failure_class = failure
        if failure_class == "unclassified":
            state, failure_class = SurfaceState.FAILED, "behavior_mismatch"
        return SurfaceRecord("mcp_registry_validation", state, subject, outcome.summary, failure_class, outcome.returncode)
    return SurfaceRecord("mcp_registry_validation", SurfaceState.VERIFIED, subject,
                         f"{publisher_version[0] if publisher_version else 'mcp-publisher'}: validate passed", command_exit=0)


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------


def _newest_reference_migration() -> str | None:
    migrations = sorted((REFERENCE_TREE / "sql").glob("[0-9][0-9][0-9]_*.sql"))
    return migrations[-1].name[:3] if migrations else None


def print_report(bundle: EvidenceBundle) -> None:
    """One line per surface, then the verdict and grouped problems. Never an environment dump."""
    width = max(len(name) for name in bundle.surfaces)
    for name, record in bundle.surfaces.items():
        detail = record.failure_class or ""
        print(f"{name:<{width}}  {record.state.value:<10}  {detail:<18}  {record.evidence.splitlines()[0][:110] if record.evidence else ''}")
    print(f"verdict  {bundle.verdict.value}")
    for label, names in (
        ("missing", bundle.missing),
        ("failed", bundle.failed),
        ("unreadable", bundle.unreadable),
        ("deferred", bundle.deferred),
    ):
        for name in names:
            print(f"  {label:<10}  {name}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("source", "container", "all"), help="which public path to accept")
    parser.add_argument("--version", required=True, help="release version without the v prefix")
    parser.add_argument("--repository", default="https://github.com/fioenix/fn-ignis.git")
    parser.add_argument("--expected-commit", default=None, help="the verified main commit the tag must name")
    parser.add_argument(
        "--expected-migration",
        default=_newest_reference_migration(),
        help="migration prefix the packaged chain must end at (default: this tree's newest)",
    )
    parser.add_argument("--image", default="ghcr.io/fioenix/fn-ignis", help="container repository without a tag")
    parser.add_argument("--platform", default=None, help="platform to pull, e.g. linux/amd64 (default: the image's)")
    parser.add_argument("--work-root", type=Path, default=None, help="parent for the run's temporary root")
    parser.add_argument("--json-output", type=Path, default=None, help="write the redacted evidence bundle here")
    args = parser.parse_args(argv)

    if not SEMVER.fullmatch(args.version):
        parser.error(f"not a release version: {args.version}")
    if args.mode in ("source", "all") and not args.expected_commit:
        parser.error("--expected-commit is required for source and all modes")
    if args.expected_commit and not FULL_SHA.fullmatch(args.expected_commit):
        parser.error("--expected-commit must be a full lowercase commit SHA")
    check_public_url(args.repository)

    records: list[SurfaceRecord] = []
    with TemporaryRoot(parent=args.work_root) as root:
        checkout = None
        if args.mode in ("source", "all"):
            source_root = root.path / "source"
            source_root.mkdir()
            records += observe_source(
                repository=args.repository,
                version=args.version,
                expected_commit=args.expected_commit,
                root=source_root,
                expected_migration=args.expected_migration,
            )
            checkout = source_root / "checkout" if (source_root / "checkout").is_dir() else None
        if args.mode in ("container", "all"):
            container_root = root.path / "container"
            container_root.mkdir()
            records += observe_container(
                image=args.image, version=args.version, root=container_root, platform=args.platform, check_worker=True
            )
        if args.mode == "all":
            records += observe_github(
                repository=args.repository, version=args.version, expected_commit=args.expected_commit
            )
            records.append(observe_version_parity(checkout, args.version))
            pulled = next((r for r in records if r.name == "container_anonymous_pull"), None)
            digest = (
                pulled.subject.rsplit("@", 1)[1] if pulled and pulled.state == SurfaceState.VERIFIED else None
            )
            # The only authenticated observation: it runs with the operator's gh, never in isolation.
            records.append(
                observe_provenance(
                    image=args.image,
                    digest=digest,
                    version=args.version,
                    repository=args.repository,
                    expected_commit=args.expected_commit,
                )
            )
            records.append(
                observe_registry_validation(checkout)
                if checkout
                else _unread("mcp_registry_validation", "server.json", "no tagged source tree to validate")
            )

    bundle = build_bundle(args.version, args.expected_commit, complete_with_unobserved(records))
    print_report(bundle)
    if args.json_output:
        write_evidence(bundle, args.json_output)
    return 0 if bundle.verdict == Verdict.RELEASED else 1


if __name__ == "__main__":
    raise SystemExit(main())
