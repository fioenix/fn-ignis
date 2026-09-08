"""Locating the SQL seed files, which have to be found in two different layouts.

A checkout keeps them in `sql/` at the repository root, which is what the bootstrap script and
the Postgres migration flow read. A wheel cannot reach outside the package, so the same files are
shipped inside it as `ignis/sql/` (see the force-include in pyproject.toml). Resolving the
directory in one place keeps `pip install fn-ignis` seeding the same lexicons, taxonomies and
runtime configs a checkout does, instead of silently starting with an empty vocabulary.
"""

from pathlib import Path
from typing import Optional

# Inside an installed wheel: src/ignis/sql/
PACKAGED_SQL_DIR = Path(__file__).resolve().parent / "sql"
# Inside a checkout: <repo>/sql/
REPOSITORY_SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def sql_seed_dir() -> Optional[Path]:
    """Return the directory holding the SQL seeds, or None when neither layout has one."""
    for candidate in (PACKAGED_SQL_DIR, REPOSITORY_SQL_DIR):
        if candidate.is_dir():
            return candidate
    return None


def sql_seed_file(filename: str) -> Optional[Path]:
    """Return one SQL seed file by name, or None when it cannot be found."""
    directory = sql_seed_dir()
    if directory is None:
        return None
    candidate = directory / filename
    return candidate if candidate.is_file() else None
