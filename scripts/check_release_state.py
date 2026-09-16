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
class ReleaseSurface:
    """The three facts, already read. Kept separate from the reading so the verdict is testable."""

    tag_exists: bool
    release_published: bool
    repository_public: bool


def release_verdict(version: str, surface: ReleaseSurface) -> tuple[bool, list[str]]:
    """Whether `version` is released, and what evidence is missing if it is not.

    Visibility is reported alongside but is not part of the verdict: a private repository can hold
    a tag and a Release, and a public one with neither has released nothing.
    """
    missing = []
    if not surface.tag_exists:
        missing.append(f"no git tag v{version}")
    if not surface.release_published:
        missing.append(f"no published GitHub Release v{version}")
    return not missing, missing


def declared_version() -> str:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _run(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False, cwd=REPO)
    return completed.returncode, completed.stdout.strip()


def read_surface(version: str) -> tuple[ReleaseSurface, list[str]]:
    """Read the three facts. Returns the surface plus any fact that could not be established."""
    unknown = []

    code, out = _run(["git", "tag", "--list", f"v{version}"])
    tag_exists = code == 0 and out != ""
    if code != 0:
        unknown.append("git tag --list failed")

    release_published = False
    repository_public = False
    if shutil.which("gh") is None:
        unknown.append("gh is not installed; GitHub Release and visibility unknown")
    else:
        code, out = _run(["gh", "release", "view", f"v{version}", "--json", "isDraft,publishedAt"])
        if code == 0:
            payload = json.loads(out)
            release_published = not payload.get("isDraft") and bool(payload.get("publishedAt"))
        elif "release not found" not in out.lower() and out:
            unknown.append(f"gh release view: {out.splitlines()[0][:90]}")

        code, out = _run(["gh", "repo", "view", "--json", "visibility"])
        if code == 0:
            repository_public = json.loads(out).get("visibility", "").upper() == "PUBLIC"
        else:
            unknown.append("gh repo view failed; visibility unknown")

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

    surface, unknown = read_surface(version)
    released, missing = release_verdict(version, surface)

    print(f"version            {version}")
    print(f"git tag v{version}    {'present' if surface.tag_exists else 'absent'}")
    print(f"GitHub Release     {'published' if surface.release_published else 'not published'}")
    print(f"visibility         {'PUBLIC' if surface.repository_public else 'not public'}")
    for note in unknown:
        print(f"unknown            {note}")
    print(f"verdict            {'RELEASED' if released else 'NOT RELEASED'}")
    for item in missing:
        print(f"  missing          {item}")
    # An unknown is not a pass: it means the surface was not read, not that it was read and was fine.
    return 0 if released and not unknown else 1


if __name__ == "__main__":
    sys.exit(main())
