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
    DEFERRED    policy excludes a non-required surface -- PyPI for v0.6.0

The verdict is derived, never typed: RELEASED only when every required surface is VERIFIED;
INDETERMINATE when any is UNREADABLE; NOT_RELEASED when something is proven missing or failed.
An empty stdout or a non-zero exit is never read as absence unless the answer matches a known
absence response.

Anonymous distribution and authenticated provenance are separate observations. The anonymous
paths run with an allowlisted environment and no credential; attestation verification needs the
release owner's registry authentication and is recorded as its own surface.

    python scripts/public_release_acceptance.py source --version 0.6.0 \\
        --repository https://github.com/fioenix/fn-ignis.git --expected-commit <sha>
    python scripts/public_release_acceptance.py container --version 0.6.0 \\
        --image ghcr.io/fioenix/fn-ignis
    python scripts/public_release_acceptance.py all --version 0.6.0 ... --json-output <path>
"""

from __future__ import annotations

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
