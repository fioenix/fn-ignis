"""A coverage threshold that is printed and never enforced is a number, not a promise.

SC-004 has promised at least 85% coverage for the Repository, the RSS Plugin, the YouTube Plugin
and the Registry since the feature was specified. Until 22/09/2026 CI measured coverage and printed
it: the 2026-09-13 run measured 73%, a later Timescale-backed run measured 75%, and both builds
were green. Nothing connected the promise to an exit code.

Two things have to hold for the gate to mean anything, and neither is visible in a coverage
percentage. The scope has to be the scope SC-004 names -- widening it to all of `src/ignis` or
narrowing it to a hand-picked subset both produce a number that answers a different question. And
the threshold has to fail the build, without an omit pattern quietly removing production code from
the denominator. Both are asserted here.

Deliberately not asserted: the percentage itself. That is a property of the test suite on the day
it runs, measured by the run, not a static fact about the repository. What is pinned here is the
gate that judges it.
"""

import configparser
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE_CONFIG = REPO / ".coveragerc.sc004"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

REQUIRED_FLOOR = 85.0

# The four names in SC-004, and the file patterns each one resolves to. Written here independently
# of the config so that a change to the config has to be made twice, deliberately, and explained.
SC004_SCOPE = {
    "*/ignis/infrastructure/persistence/*",
    "*/ignis/infrastructure/connectors/registry.py",
    "*/ignis/infrastructure/connectors/google_trends/*",
    "*/ignis/infrastructure/connectors/youtube/*",
}

# One real module per promised name. A pattern that stopped matching its module would leave the
# criterion nominally scoped and actually empty.
SCOPE_WITNESSES = {
    "Repository": "src/ignis/infrastructure/persistence/sqlite_repository.py",
    "Registry": "src/ignis/infrastructure/connectors/registry.py",
    "RSS Plugin": "src/ignis/infrastructure/connectors/google_trends/rss_plugin.py",
    "YouTube Plugin": "src/ignis/infrastructure/connectors/youtube/youtube_plugin.py",
}


def _gate() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(GATE_CONFIG, encoding="utf-8")
    return parser


def _include_patterns() -> set:
    raw = _gate().get("report", "include")
    return {line.strip() for line in raw.splitlines() if line.strip()}


def _ci_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


# --- the scope is the one the criterion names ---------------------------------------------------


def test_the_gate_config_exists():
    assert GATE_CONFIG.exists(), (
        "SC-004's scope is written nowhere, so the coverage number cannot be checked against the"
        " promise it is supposed to answer"
    )


def test_the_scope_is_exactly_the_four_things_sc004_promises():
    """Repository, RSS Plugin, YouTube Plugin, Registry. Not more, not fewer."""
    configured = _include_patterns()

    unexpected = configured - SC004_SCOPE
    missing = SC004_SCOPE - configured
    assert not missing, (
        "SC-004 names these and the gate does not measure them, so the promise is scored on a"
        f" smaller surface than it covers: {sorted(missing)}"
    )
    assert not unexpected, (
        "the gate measures code SC-004 does not name, so the percentage answers a different"
        f" question than the criterion asks: {sorted(unexpected)}"
    )


def test_every_promised_name_still_resolves_to_a_module_that_exists():
    """A pattern kept after its module moved leaves the scope nominally intact and actually empty."""
    for promised, module in SCOPE_WITNESSES.items():
        assert (REPO / module).exists(), (
            f"SC-004 promises coverage for the {promised}, and {module} is gone; the gate is now"
            " measuring a scope with nothing in it"
        )


def test_the_scope_matches_both_a_source_tree_and_an_installed_package():
    """CI installs the project; a pattern anchored to src/ would match nothing there."""
    for pattern in _include_patterns():
        assert pattern.startswith("*/ignis/"), (
            f"{pattern!r} is anchored to one layout, so the scope silently empties out under the"
            " other one and the gate passes on zero statements"
        )


# --- the threshold can fail the build -----------------------------------------------------------


def test_the_floor_is_the_one_the_criterion_states():
    gate = _gate()
    assert gate.has_option("report", "fail_under"), (
        "the gate config sets no fail_under, so `coverage report` prints a number and exits 0"
        " whatever it is -- which is the state SC-004 was already in"
    )
    assert gate.getfloat("report", "fail_under") == REQUIRED_FLOOR


def test_ci_runs_the_gate_and_does_not_swallow_its_exit_code():
    text = _ci_text()
    assert ".coveragerc.sc004" in text, (
        "ci.yml never invokes the gate, so the threshold is enforced only by whoever remembers to"
        " run it locally"
    )

    command_lines = [line for line in text.splitlines() if "coverage report" in line]
    assert command_lines, "no `coverage report` command in ci.yml"
    for line in command_lines:
        assert not re.search(r"\|\|\s*true", line), (
            f"the gate's exit code is swallowed: {line.strip()}"
        )
    assert "continue-on-error: true" not in text.split("Enforce the SC-004 Coverage Floor")[-1], (
        "the gate step is continue-on-error, so falling below the floor leaves the build green"
    )


def test_the_gate_reads_the_coverage_data_the_test_run_produced():
    """Measuring twice would double the suite's cost and could disagree with the printed report."""
    text = _ci_text()
    test_step = text.index("Run Test Suite with Coverage")
    gate_step = text.index("Enforce the SC-004 Coverage Floor")
    assert test_step < gate_step, (
        "the gate runs before the suite, so it reads stale or absent coverage data"
    )
    assert "--cov=ignis" in text, (
        "the suite no longer measures the package, so the gate has nothing to read"
    )


# --- nothing inside the scope is hidden ---------------------------------------------------------


def test_the_gate_excludes_nothing_inside_the_promised_scope():
    """An omit is the one edit that raises the number without testing anything."""
    gate = _gate()
    assert not gate.has_option("report", "omit"), (
        "the gate omits files inside the SC-004 scope. Coverage then rises by removing production"
        " code from the denominator, which is the opposite of what the criterion asks for."
    )
    assert not gate.has_option("report", "exclude_lines"), (
        "the gate adds exclude_lines, which drops matching source lines from the denominator"
    )
    assert not gate.has_option("report", "exclude_also")


def test_no_pragma_no_cover_was_added_to_the_promised_scope():
    """`# pragma: no cover` removes a line from the denominator wherever it is written."""
    offenders = []
    for module in (
        REPO / "src/ignis/infrastructure/persistence",
        REPO / "src/ignis/infrastructure/connectors/google_trends",
        REPO / "src/ignis/infrastructure/connectors/youtube",
    ):
        for path in module.rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "pragma: no cover" in line:
                    offenders.append(f"{path.relative_to(REPO)}:{number}")
    registry = REPO / "src/ignis/infrastructure/connectors/registry.py"
    for number, line in enumerate(registry.read_text(encoding="utf-8").splitlines(), 1):
        if "pragma: no cover" in line:
            offenders.append(f"{registry.relative_to(REPO)}:{number}")

    assert not offenders, (
        "these lines inside the SC-004 scope are exempted from measurement:\n" + "\n".join(offenders)
    )


# --- the PostgreSQL half of the scope is actually exercised --------------------------------------


def test_ci_still_reaches_postgres_only_through_the_test_dsn():
    """Half the Repository is the PostgreSQL adapter; without a database those tests skip."""
    text = _ci_text()
    assert "IGNIS_TEST_POSTGRES_DSN" in text, (
        "CI no longer provides a test DSN, so the PostgreSQL adapter's tests skip and the gate"
        " scores the Repository on its SQLite half alone"
    )
    assert "timescale/timescaledb-ha:pg16" in text, (
        "the PostgreSQL service is gone or on a different engine"
    )
    # The suite must reach PostgreSQL through the test DSN and nothing else. `DATABASE_URL` is the
    # runtime connection variable, and the wheel smoke step legitimately writes a SQLite one into
    # its own throwaway env file -- so what is refused here is a DATABASE_URL carrying a PostgreSQL
    # connection, or one exported to the job where the suite would pick it up.
    offenders = [
        line.strip()
        for line in text.splitlines()
        if "DATABASE_URL" in line and "postgres" in line.lower()
    ]
    assert not offenders, (
        "CI points DATABASE_URL at a PostgreSQL server, so the suite can reach a configured"
        " database instead of the throwaway service:\n" + "\n".join(offenders)
    )
    job_env = text.split("env:", 1)[1].split("services:", 1)[0]
    assert "DATABASE_URL" not in job_env, (
        "DATABASE_URL is exported to the whole test job, where the repository would read it in"
        " preference to the throwaway service"
    )


def test_the_performance_workflow_is_untouched_by_the_coverage_gate():
    """SC-001's benchmark stays out of ordinary PR CI; the two gates are separate on purpose."""
    text = _ci_text()
    assert "t021_read_path_benchmark" not in text, (
        "the SC-001 benchmark has been pulled into the ordinary test matrix, which charges every"
        " pull request for two 10,000-observation seeds"
    )
    assert (REPO / ".github/workflows/performance.yml").exists(), (
        "the separate SC-001 performance workflow is gone"
    )
