"""The SQL seeds must be reachable from an installed wheel, not only from a checkout.

`pip install fn-ignis` used to start with an empty vocabulary: the loader looked for `sql/` at the
repository root, which does not exist next to an installed package, so no lexicon, taxonomy or
runtime config was ever seeded and the failure was silent.
"""

import copy
import tomllib

import pytest
from pathlib import Path

import ignis.resources as resources
from ignis.resources import sql_seed_dir, sql_seed_file

SEED_FILES = (
    "003_market_lexicons.sql",
    "004_global_lexicons.sql",
    "007_runtime_configs.sql",
    "036_threads_attribution.sql",
    "037_threads_action_labels.sql",
    "038_tiktok_attribution_locales.sql",
    # Run by the SQLite bootstrap after the vocabulary replay; missing from a wheel, the retired
    # UI-noise terms would silently come back on every installed SQLite database.
    "020_retire_ambiguous_tiktok_ui_noise.sql",
)
# Not a seed: PostgreSQL-only, and read by no bootstrap. The Compose init and an operator applying
# sql/ by hand need the whole chain, so the newest migration is pinned here and shipped with it.
NEWEST_POSTGRES_ONLY_MIGRATION = "035_watchlist_listening_plans.sql"
NEWEST_MIGRATION = "038_tiktok_attribution_locales.sql"
# The closed sdist member list: runtime package, the SQL chain, and the build metadata. Anything
# else -- tests, docs, examples, reports, handoff notes, agent or local settings -- must not ship.
SDIST_MEMBERS = {"src/ignis", "sql", "pyproject.toml", "README.md", "LICENSE"}


def _packaging_offenders(project):
    """Reason codes for each way a parsed pyproject leaves the approved declaration; empty if exact.

    This checks the declared configuration, not Hatch's precedence rules: the approved sdist
    declares only the closed member list, so exclude/include/force-include keys are refused as
    outside that declaration rather than interpreted.
    """
    targets = project.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {})
    wheel, sdist = targets.get("wheel", {}), targets.get("sdist", {})
    offenders = []
    if wheel.get("force-include", {}).get("sql") != "ignis/sql":
        offenders.append("WHEEL_SQL_NOT_FORCE_INCLUDED")
    members = sdist.get("only-include")
    if not isinstance(members, list) or set(members) != SDIST_MEMBERS or len(members) != len(SDIST_MEMBERS):
        offenders.append("SDIST_MEMBERS_NOT_EXACT")
    # Any exclusion could remove a required member (README.md, LICENSE, sql, even "**").
    for key, reason in (("exclude", "SDIST_EXCLUDE_UNSUPPORTED"), ("include", "SDIST_INCLUDE_UNSUPPORTED"),
                        ("force-include", "SDIST_FORCE_INCLUDE_UNSUPPORTED")):
        if key in sdist:
            offenders.append(reason)
    return offenders


def test_seed_directory_is_found_in_this_layout():
    directory = sql_seed_dir()
    assert directory is not None and directory.is_dir()
    for name in SEED_FILES:
        assert (directory / name).is_file(), f"{name} must ship with the package"


def test_every_seed_the_bootstrap_reads_resolves():
    for name in SEED_FILES:
        assert sql_seed_file(name) is not None


def test_packaged_location_wins_over_the_checkout(tmp_path, monkeypatch):
    """An installed wheel has no repository root, so the packaged copy must be tried first."""
    packaged = tmp_path / "packaged"
    packaged.mkdir()
    (packaged / "003_market_lexicons.sql").write_text("-- packaged", encoding="utf-8")
    monkeypatch.setattr(resources, "PACKAGED_SQL_DIR", packaged)
    monkeypatch.setattr(resources, "REPOSITORY_SQL_DIR", tmp_path / "missing")

    assert sql_seed_dir() == packaged
    assert sql_seed_file("003_market_lexicons.sql").read_text(encoding="utf-8") == "-- packaged"


def test_checkout_location_is_the_fallback(tmp_path, monkeypatch):
    repository = tmp_path / "repo-sql"
    repository.mkdir()
    (repository / "003_market_lexicons.sql").write_text("-- checkout", encoding="utf-8")
    monkeypatch.setattr(resources, "PACKAGED_SQL_DIR", tmp_path / "absent")
    monkeypatch.setattr(resources, "REPOSITORY_SQL_DIR", repository)

    assert sql_seed_dir() == repository


def test_missing_seeds_report_none_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "PACKAGED_SQL_DIR", tmp_path / "a")
    monkeypatch.setattr(resources, "REPOSITORY_SQL_DIR", tmp_path / "b")

    assert sql_seed_dir() is None
    assert sql_seed_file("003_market_lexicons.sql") is None


def test_wheel_ships_the_seeds_alongside_the_package():
    """Guards the force-include in pyproject.toml against being dropped."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    assert "[tool.hatch.build.targets.wheel.force-include]" in content
    assert '"sql" = "ignis/sql"' in content


def test_the_whole_postgres_migration_chain_ships_not_only_the_seeds():
    """The wheel copies the directory and the sdist keeps it, so no migration is left behind."""
    directory = sql_seed_dir()
    assert directory is not None and (directory / NEWEST_POSTGRES_ONLY_MIGRATION).is_file(), (
        f"{NEWEST_POSTGRES_ONLY_MIGRATION} is missing from the SQL directory the package ships"
    )
    assert NEWEST_POSTGRES_ONLY_MIGRATION not in SEED_FILES, "a PostgreSQL-only migration is not a seed"
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert _packaging_offenders(project) == []

    # Each wrong contract must be rejected, so the check above cannot pass vacuously.
    def variant(change):
        changed = copy.deepcopy(project)
        change(changed["tool"]["hatch"]["build"]["targets"])
        return _packaging_offenders(changed)

    assert variant(lambda t: t["sdist"]["only-include"].remove("sql")) == ["SDIST_MEMBERS_NOT_EXACT"]
    assert variant(lambda t: t["wheel"]["force-include"].update({"sql": "sql"})) == ["WHEEL_SQL_NOT_FORCE_INCLUDED"]
    for private in (".handoff", ".env", "tests", "docs", "examples", "reports", ".codex"):
        assert variant(lambda t, private=private: t["sdist"]["only-include"].append(private)) == [
            "SDIST_MEMBERS_NOT_EXACT"], private
    for required in (["/sql"], ["README.md"], ["LICENSE"], ["pyproject.toml"], ["src/ignis"], ["**"]):
        assert variant(lambda t, required=required: t["sdist"].update({"exclude": required})) == [
            "SDIST_EXCLUDE_UNSUPPORTED"], required
    assert variant(lambda t: t["sdist"].update({"include": ["docs"]})) == ["SDIST_INCLUDE_UNSUPPORTED"]
    assert variant(lambda t: t["sdist"].update({"force-include": {".handoff": ".handoff"}})) == [
        "SDIST_FORCE_INCLUDE_UNSUPPORTED"]


def test_the_migration_inventory_includes_partial_outcomes_and_both_backends_state_claim_tables():
    """Compose and a hand-applied chain need 025 in order; SQLite restates it, not reads it."""
    directory = sql_seed_dir()
    names = sorted(path.name for path in directory.glob("*.sql"))
    assert names[-1] == NEWEST_MIGRATION
    assert [int(name[:3]) for name in names] == list(range(1, len(names) + 1))

    migration = (directory / "025_evidence_grounded_claim_ledger.sql").read_text(encoding="utf-8")
    sqlite_source = (
        Path(__file__).resolve().parents[2]
        / "src/ignis/infrastructure/persistence/sqlite_repository.py"
    ).read_text(encoding="utf-8")
    for table in ("mission_manifests", "mission_claims", "mission_claim_evidence"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration, table
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sqlite_source, f"SQLite does not restate {table}"
    assert "ENABLE ROW LEVEL SECURITY" in migration
    for field in ("metric_denominator", "metric_timeframe"):
        assert field in migration
        assert field in sqlite_source
    assert "mission_claims_metric_basis_check" in migration

    quota_migration = (directory / "024_youtube_quota_ledger.sql").read_text(encoding="utf-8")
    assert "PRIMARY KEY (quota_day, bucket)" in quota_migration


def test_the_two_evidence_grounded_skills_ship_with_the_checkout():
    """A release missing either capability package exposes only half of the approved product."""
    root = Path(__file__).resolve().parents[2]

    assert (root / ".agents/skills/ignis-collect/SKILL.md").is_file()
    assert (root / ".agents/skills/ignis-analyze/SKILL.md").is_file()


def test_threads_seed_resolves_in_checkout_and_packaged_tactical_layout(tmp_path, monkeypatch):
    from ignis.application.use_cases.host_browser_search import AttributionVocabularyMissing, HostBrowserSearchService
    from ignis.infrastructure.config.vocabulary_loader import seeded_lexicon_terms

    seed = sql_seed_file("036_threads_attribution.sql")
    assert seed is not None, "Threads attribution seed must be shipped"
    packaged = tmp_path / "packaged"
    packaged.mkdir()
    (packaged / seed.name).write_bytes(seed.read_bytes())
    monkeypatch.setattr(resources, "PACKAGED_SQL_DIR", packaged)
    monkeypatch.setattr(resources, "REPOSITORY_SQL_DIR", tmp_path / "absent")
    assert seeded_lexicon_terms("036_threads_attribution.sql", "threads_attribution") == ["Photo by {author} on"]
    service = HostBrowserSearchService()
    try:
        assert service.attribution_templates_for("threads") == ("Photo by {author} on",)
    finally:
        service.close()
    (packaged / seed.name).unlink()
    assert seeded_lexicon_terms("036_threads_attribution.sql", "threads_attribution") == []
    service = HostBrowserSearchService()
    try:
        with pytest.raises(AttributionVocabularyMissing):
            service.attribution_templates_for("threads")
    finally:
        service.close()


@pytest.mark.parametrize("relative", [
    "infrastructure/connectors/host_browser/threads_search.js",
    "infrastructure/connectors/host_browser/threads_handoff.js",
    "infrastructure/connectors/host_browser/tiktok_search.js",
    "infrastructure/templates/html/host_browser_relay.html",
    "infrastructure/templates/html/host_browser_receiver.html",
])
def test_host_resources_are_readable_through_the_package(relative):
    from importlib.resources import files
    assert files("ignis").joinpath(relative).read_text(encoding="utf-8").strip()
