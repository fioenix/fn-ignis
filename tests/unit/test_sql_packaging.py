"""The SQL seeds must be reachable from an installed wheel, not only from a checkout.

`pip install fn-ignis` used to start with an empty vocabulary: the loader looked for `sql/` at the
repository root, which does not exist next to an installed package, so no lexicon, taxonomy or
runtime config was ever seeded and the failure was silent.
"""

from pathlib import Path

import ignis.resources as resources
from ignis.resources import sql_seed_dir, sql_seed_file

SEED_FILES = (
    "003_market_lexicons.sql",
    "004_global_lexicons.sql",
    "007_runtime_configs.sql",
    # Run by the SQLite bootstrap after the vocabulary replay; missing from a wheel, the retired
    # UI-noise terms would silently come back on every installed SQLite database.
    "020_retire_ambiguous_tiktok_ui_noise.sql",
)


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
