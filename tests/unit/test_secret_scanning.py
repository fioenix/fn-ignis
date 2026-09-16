"""CI must scan for secrets, and the scan must be able to fail.

The repository had no secret scanning at all until 17/09/2026. The history was clean when that was
first checked by hand, which is the weakest kind of assurance: it says nothing about the next
commit, and a hand scan is run by whoever remembers to run it.

What the scan does not do is worth writing down. gitleaks matches identifiable shapes -- a
`ghp_` prefix, an `AKIA` key id, a Slack token's segments. A bare forty-character random string
assigned to a plausible variable name went through undetected when this was tested on 17/09, so
the scan raises the floor and is not a reason to stop reading diffs. GitHub's own push protection,
free once a repository is public, is the complementary control: it blocks the push rather than
reporting afterwards.

These contracts check the properties that decide whether the scan is worth having -- that it runs,
that a finding stops the build, that the tool version is pinned, and that the allowlist exempts
named files rather than whole trees. A scan wired up with `continue-on-error` reports findings into
a log nobody reads and turns the build green, which is the same failure as having no scan while
believing you have one.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
GITLEAKS_CONFIG = REPO / ".gitleaks.toml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Steps are indented six spaces under `steps:`; a job name sits at four. Slicing on the first
# match for "secret scan" found the job name instead and returned an empty block, which would have
# passed every assertion below that looked for something absent.
STEP_SEPARATOR = "\n      - name:"


def _scan_step() -> str:
    """The workflow step that runs the secret scan, from its name to the next step."""
    blocks = _read(WORKFLOW).split(STEP_SEPARATOR)
    matching = [b for b in blocks if "secret" in b.split("\n", 1)[0].lower()]
    assert matching, (
        "No step in .github/workflows/ci.yml is named for a secret scan. Every commit reaches CI; "
        "a scan that only runs when somebody remembers is not a control."
    )
    assert len(matching) == 1, (
        f"{len(matching)} steps claim to be the secret scan; which one gates the build is ambiguous"
    )
    return matching[0]


def test_ci_runs_a_secret_scan():
    step = _scan_step()
    assert "gitleaks" in step.lower(), (
        "the secret-scan step does not invoke a scanner:\n" + step
    )


def test_the_secret_scan_can_fail_the_build():
    """A scan that cannot turn the build red is a log entry, not a gate."""
    step = _scan_step()
    assert "continue-on-error: true" not in step, (
        "the secret-scan step is marked continue-on-error, so a finding leaves the build green:\n"
        + step
    )
    assert not re.search(r"\|\|\s*true", step), (
        "the secret-scan command swallows its exit code with `|| true`:\n" + step
    )


def test_the_scanner_version_is_pinned():
    """`latest` means the rules that run are whatever shipped that morning."""
    step = _scan_step()
    assert "gitleaks:latest" not in step, "the scanner image is unpinned (:latest)"
    assert re.search(r"gitleaks:v\d+\.\d+\.\d+", step), (
        "the scanner image carries no explicit version tag:\n" + step
    )


def test_the_allowlist_exempts_named_files_rather_than_trees():
    """An allowlist wide enough to cover a directory hides the next real secret in it."""
    if not GITLEAKS_CONFIG.exists():
        pytest.skip("no allowlist is configured, so there is nothing to keep narrow")

    text = _read(GITLEAKS_CONFIG)
    paths = re.findall(r"^\s*'''([^']+)'''", text, re.M) + re.findall(r'^\s*"([^"]+)"\s*,?\s*$', text, re.M)
    offenders = [
        p
        for p in paths
        if p.rstrip("$").endswith((".*", "/", "/.*")) or p.count("*") > 1
    ]
    assert not offenders, (
        "These allowlist entries exempt a tree rather than a file:\n" + "\n".join(offenders)
    )


def test_every_allowlisted_file_still_exists():
    """An entry for a file nobody has means a rule kept alive by nothing."""
    if not GITLEAKS_CONFIG.exists():
        pytest.skip("no allowlist is configured")

    text = _read(GITLEAKS_CONFIG)
    named = re.findall(r"(tests/[\w/]+\.py|src/[\w/]+\.py|docs/[\w/.-]+)", text)
    missing = sorted({p for p in named if not (REPO / p).exists()})
    assert not missing, (
        "The allowlist names files that no longer exist:\n" + "\n".join(missing)
    )
