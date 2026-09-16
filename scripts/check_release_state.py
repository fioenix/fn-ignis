#!/usr/bin/env python3
"""Decide whether a version is actually released, from Git and GitHub rather than from prose.

A document saying "shipped in v0.4.0" is a sentence somebody typed. The facts that make a release
a release live outside this repository's files:

    a git tag        ->  the commit the release names
    a GitHub Release ->  the thing a user can download
    visibility       ->  whether anyone outside the owners can reach either

Nothing here reads a tracked document, and that is deliberate. A checker that consulted `BACKLOG.md`
or the specs would certify the documents agreeing with themselves, which is the exact failure this
exists to catch. Consistency *between* documents is a separate, offline contract in
`tests/unit/test_diagram_and_release_claims.py`; it proves the documents agree and nothing more.

    python scripts/check_release_state.py            # version read from pyproject.toml
    python scripts/check_release_state.py 0.4.0
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CommandResult:
    """A finished command, with stderr kept.

    `gh` reports authentication and network failures on stderr and leaves stdout empty. Reading
    only stdout makes an outage indistinguishable from an answer, and the two call for opposite
    actions: one is "fix your credentials", the other is "you have not released this".
    """

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def message(self) -> str:
        """The first line the command said, wherever it said it."""
        text = self.stderr.strip() or self.stdout.strip()
        return text.splitlines()[0][:90] if text else ""


@dataclass(frozen=True)
class ReleaseSurface:
    """The three facts, already read. `None` means the fact could not be established.

    Tri-state on purpose. A fact that was never read is not a fact that came back negative, and
    collapsing the two is how a broken tool starts reporting findings.
    """

    tag_exists: bool | None
    release_published: bool | None
    repository_public: bool | None


def release_verdict(
    version: str, surface: ReleaseSurface
) -> tuple[bool, list[str], list[str]]:
    """Whether `version` is released, what evidence is absent, and what could not be read.

    Visibility is reported alongside but is not part of the verdict: a private repository can hold
    a tag and a Release, and a public one with neither has released nothing.
    """
    missing = []
    unknown = []
    for value, label in (
        (surface.tag_exists, f"git tag v{version}"),
        (surface.release_published, f"published GitHub Release v{version}"),
    ):
        if value is None:
            unknown.append(f"{label} could not be read")
        elif not value:
            missing.append(f"no {label}")
    return (not missing and not unknown), missing, unknown


def declared_version() -> str:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _run(command: list[str]) -> CommandResult:
    completed = subprocess.run(command, capture_output=True, text=True, check=False, cwd=REPO)
    return CommandResult(completed.returncode, completed.stdout.strip(), completed.stderr.strip())


# What `gh release view` says when the release genuinely is not there, as opposed to when the
# call could not be made at all. Only this answer is a fact about the repository.
RELEASE_NOT_FOUND = "release not found"


def read_surface(version: str) -> tuple[ReleaseSurface, list[str]]:
    """Read the three facts. Returns the surface plus a note for each one that could not be read."""
    unknown: list[str] = []

    result = _run(["git", "tag", "--list", f"v{version}"])
    if result.ok:
        tag_exists = result.stdout != ""
    else:
        tag_exists = None
        unknown.append(f"git tag --list failed: {result.message}")

    release_published: bool | None = None
    repository_public: bool | None = None

    if shutil.which("gh") is None:
        unknown.append("gh is not installed, so the Release and the visibility were not read")
        return ReleaseSurface(tag_exists, release_published, repository_public), unknown

    result = _run(["gh", "release", "view", f"v{version}", "--json", "isDraft,publishedAt"])
    if result.ok:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            unknown.append(f"gh release view returned unreadable JSON: {error}")
        else:
            release_published = not payload.get("isDraft") and bool(payload.get("publishedAt"))
    elif RELEASE_NOT_FOUND in f"{result.stderr} {result.stdout}".lower():
        release_published = False
    else:
        unknown.append(f"gh release view failed: {result.message or 'no output'}")

    result = _run(["gh", "repo", "view", "--json", "visibility"])
    if result.ok:
        try:
            repository_public = json.loads(result.stdout).get("visibility", "").upper() == "PUBLIC"
        except json.JSONDecodeError as error:
            unknown.append(f"gh repo view returned unreadable JSON: {error}")
    else:
        unknown.append(f"gh repo view failed: {result.message or 'no output'}")

    return ReleaseSurface(tag_exists, release_published, repository_public), unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "version", nargs="?", help="version to check; defaults to the one in pyproject.toml"
    )
    args = parser.parse_args(argv)

    version = args.version or declared_version()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"not a version: {version}")

    surface, read_notes = read_surface(version)
    released, missing, unread = release_verdict(version, surface)

    def state(value: bool | None, yes: str, no: str) -> str:
        return "unknown (not read)" if value is None else (yes if value else no)

    print(f"version            {version}")
    print(f"git tag v{version}    {state(surface.tag_exists, 'present', 'absent')}")
    print(f"GitHub Release     {state(surface.release_published, 'published', 'not published')}")
    print(f"visibility         {state(surface.repository_public, 'PUBLIC', 'not public')}")
    for note in read_notes:
        print(f"unknown            {note}")
    print(f"verdict            {'RELEASED' if released else 'NOT RELEASED'}")
    for item in missing:
        print(f"  missing          {item}")
    for item in unread:
        print(f"  unknown          {item}")
    # An unknown is not a pass: it means the surface was not read, not that it was read and was fine.
    return 0 if released else 1


if __name__ == "__main__":
    sys.exit(main())
