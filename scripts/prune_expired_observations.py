#!/usr/bin/env python3
"""Remove observations collected more than 13 months ago (Spec 016 US4, FR-014).

An explicit retention action: Ignis never runs it on a schedule of its own. An observation is
expired when it was collected (`observed_at`, the ingestion clock) before the cutoff: the same
calendar day, --older-than-months earlier, at midnight in Asia/Ho_Chi_Minh. An expired observation
is kept while a stored claim cites it or recorded research work binds it; every other expired
observation is removed, and its mission evidence and qualification rows go with it through the
schema's cascades (owner decision, 22/10/2026). Sources are kept. A store that still holds legacy
trend_signals rows keeps its most recently collected observation, because a store with those rows
and no observation fails the readiness check on its next open.

With --apply, nothing can write a new reference while the run decides and deletes: SQLite holds
its write lock from the first read, and PostgreSQL locks the referencing tables in SHARE mode, so a
claim cannot be bound to an observation in the middle of a run and then lose it to the cascade.

A dry run is the default and lists what would be removed; --apply removes it in one transaction
and reads back. A PostgreSQL DSN is read from the environment variable named by
--database-url-env and never echoed.

    python scripts/prune_expired_observations.py --sqlite .fnignis/canonical.sqlite3
    python scripts/prune_expired_observations.py --database-url-env DATABASE_URL --apply
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ignis.domain.listening_period import LISTENING_TZ

# Tables whose reference keeps an expired observation: claims, and research work (PostgreSQL only).
KEEPING_REFERENCES = (
    ("mission_claim_evidence", "claim"),
    ("research_input_observations", "research_work"),
    ("research_handoff_observations", "research_work"),
    ("research_finding_observations", "research_work"),
)
_BATCH = 500


def cutoff(now: datetime, months: int) -> datetime:
    """Midnight in Asia/Ho_Chi_Minh on the same calendar day `months` earlier, as a UTC instant."""
    today = now.astimezone(LISTENING_TZ).date()
    index = today.year * 12 + today.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return datetime.combine(date(year, month, day), time(0), LISTENING_TZ).astimezone(timezone.utc)


def _instant(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _plan(read: Callable[[str], Iterable[tuple]], tables: set, limit: datetime) -> Dict[str, Any]:
    collected = {str(row_id): _instant(observed) for row_id, observed in read("SELECT id, observed_at FROM observations")}
    expired = {row_id for row_id, instant in collected.items() if instant is not None and instant < limit}
    kept: Counter = Counter()
    keep = set()
    for table, reason in KEEPING_REFERENCES:
        if table not in tables:
            continue
        cited = {str(row[0]) for row in read(f"SELECT observation_id FROM {table}") if row[0] is not None}
        held = (expired & cited) - keep
        kept[reason] += len(held)
        keep |= held
    removable = expired - keep
    legacy = "trend_signals" in tables and bool(read("SELECT EXISTS (SELECT 1 FROM trend_signals)")[0][0])
    if legacy and removable and len(removable) == len(collected):
        newest = max(removable, key=lambda row_id: (collected[row_id], row_id))
        kept["readiness"] += 1
        removable = removable - {newest}
    removed = sorted(removable)
    missions: Counter = Counter()
    if "mission_evidence" in tables:
        doomed = set(removed)
        missions.update(str(m) for m, o in read("SELECT mission_id, observation_id FROM mission_evidence") if str(o) in doomed)
    return {
        "expired": len(expired),
        "kept": {reason: kept[reason] for reason in ("claim", "research_work", "readiness")},
        "to_remove": len(removed),
        "ids": removed,
        "mission_evidence_by_mission": dict(sorted(missions.items())),
    }


def _run(store, tables, read, delete, months, now, apply) -> Dict[str, Any]:
    limit = cutoff(now, months)
    report = {
        "store": store,
        "mode": "apply" if apply else "dry-run",
        "older_than_months": months,
        "cutoff": limit.isoformat(),
        **_plan(read, tables, limit),
    }
    if apply:
        ids = report["ids"]
        for start in range(0, len(ids), _BATCH):
            delete(ids[start:start + _BATCH])
        after = _plan(read, tables, limit)
        report["readback"] = {"removed": len(ids), "remaining_to_remove": after["to_remove"]}
    return report


def _sqlite(path: Path, months: int, now: datetime, apply: bool) -> Dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"No SQLite store at {path}; nothing was created.")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode={'rw' if apply else 'ro'}", uri=True)
    conn.execute("PRAGMA foreign_keys = ON")  # The evidence cascades run only with this on.
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

        def delete(ids: Sequence[str]) -> None:
            conn.execute(f"DELETE FROM observations WHERE id IN ({', '.join('?' for _ in ids)})", tuple(ids))

        with conn:
            if apply:
                conn.execute("BEGIN IMMEDIATE")
            return _run("sqlite", tables, lambda q: conn.execute(q).fetchall(), delete, months, now, apply)
    finally:
        conn.close()


def _postgres(variable: str, months: int, now: datetime, apply: bool) -> Dict[str, Any]:
    dsn = os.environ.get(variable)
    if not dsn:
        raise SystemExit(f"The environment variable {variable} is not set.")
    try:
        import psycopg
        from psycopg import sql

        with psycopg.connect(dsn) as conn:
            if not apply:
                conn.execute("SET TRANSACTION READ ONLY")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            }

            def delete(ids: Sequence[str]) -> None:
                conn.execute("DELETE FROM public.observations WHERE id = ANY(%s::uuid[])", (list(ids),))

            if apply:
                referencing = [table for table, _ in KEEPING_REFERENCES if table in tables]
                if referencing:
                    conn.execute(
                        sql.SQL("LOCK TABLE {} IN SHARE MODE").format(
                            sql.SQL(", ").join(sql.Identifier("public", table) for table in referencing)
                        )
                    )

            report = _run("postgres", tables, lambda q: conn.execute(q).fetchall(), delete, months, now, apply)
            conn.commit() if apply else conn.rollback()
            return report
    except SystemExit:
        raise
    except Exception as error:  # The message can carry connection details; only its type is shown.
        raise SystemExit(f"Could not prune the store named by {variable}: {type(error).__name__}.") from None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sqlite", type=Path, help="Path to an Ignis SQLite store.")
    source.add_argument("--database-url-env", help="Name of the environment variable holding a PostgreSQL DSN.")
    parser.add_argument("--older-than-months", type=int, default=13, help="Retention in months (default 13).")
    parser.add_argument("--apply", action="store_true", help="Remove the listed observations; without it nothing is written.")
    args = parser.parse_args(argv)
    if args.older_than_months < 1:
        parser.error("--older-than-months must be at least 1.")
    now = datetime.now(timezone.utc)
    if args.sqlite:
        report = _sqlite(args.sqlite, args.older_than_months, now, args.apply)
    else:
        report = _postgres(args.database_url_env, args.older_than_months, now, args.apply)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
