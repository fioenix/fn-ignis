"""Print exact unscoped baseline targets without changing the database."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Mapping

from ignis.application.use_cases.inventory_legacy_baseline import InventoryLegacyBaselineUseCase
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


async def _inventory(dsn: str, retention_reasons: Mapping[str, str] | None) -> dict:
    if dsn.startswith("sqlite:///"):
        repository = SqliteTrendRepository(dsn)
    elif dsn.startswith(("postgresql://", "postgres://")):
        repository = PostgresTimescaleRepository(dsn)
    else:
        raise ValueError("Pass an explicit SQLite or PostgreSQL DSN.")
    try:
        return await InventoryLegacyBaselineUseCase(WorkspaceRepository(repository)).execute(
            retention_reasons=retention_reasons
        )
    finally:
        await repository.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="Existing database to inventory read-only")
    parser.add_argument(
        "--retention-file", type=Path,
        help="Read-only JSON map of legacy signal IDs to concrete retention reasons",
    )
    args = parser.parse_args()
    try:
        reasons = None
        if args.retention_file is not None:
            reasons = json.loads(args.retention_file.read_text(encoding="utf-8"))
            if not isinstance(reasons, dict):
                raise ValueError("Retention file must contain a JSON object.")
        payload = asyncio.run(_inventory(args.dsn, reasons))
    except Exception as exc:
        # Database exceptions may embed a connection string; never print it or its credentials.
        print(f"Inventory failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
