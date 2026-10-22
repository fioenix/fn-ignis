#!/usr/bin/env python3
"""Remove author identity stored before Spec 015 from a store (Spec 015 OG-3, FR-015).

The owner decided on 22/10/2026 to anonymise legacy rows. Each row is rewritten through the same
policy the collection pass applies (`strip_stored_identity`): author fields and account-naming
links leave metadata, a stored link that names an account becomes an identity-free link or none,
and @mentions become @[user]. A row that already complies comes back unchanged, so the script is
idempotent.

A dry run is the default and prints the manifest FR-015 requires before acting: target row ids
per table, how many rows each field changes, the missions whose evidence is affected and how many
claims are bound to it. Evidence frames that include a rewritten row get a new digest, so those
claims read as stale until the mission is requalified (research R10). --apply rewrites every target
in one transaction and then prints a readback. Source keys derived from an account link are only
counted: changing a key re-identifies the source. No identity value is ever printed, and a
PostgreSQL DSN is read from the environment variable named by --database-url-env and never echoed.

    python scripts/anonymise_author_identity.py --sqlite .fnignis/canonical.sqlite3
    python scripts/anonymise_author_identity.py --sqlite .fnignis/canonical.sqlite3 --apply
    python scripts/anonymise_author_identity.py --database-url-env DATABASE_URL [--apply]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ignis.application.author_policy import strip_stored_identity
from ignis.domain.author_identity import has_handle_segment
from ignis.infrastructure.security.pii_sanitizer import mask_author_identity_text

# table -> (title column, query). Each query returns (id, platform, link, title, metadata);
# topic clusters hold text only and are read separately.
_SIGNAL_TABLES = {
    "observations": ("observed_title", "SELECT o.id, s.platform, o.source_url, o.observed_title, o.metadata"
                     " FROM observations o JOIN sources s ON s.id = o.source_id"),
    "trend_signals": ("raw_title", "SELECT id, platform, source_url, raw_title, metadata FROM trend_signals"),
}
_CLUSTER_TEXT = ("canonical_name", "topic_label", "summary_text")

Change = Tuple[str, str, Dict[str, Any]]  # (table, row id, {column: new value})


def _metadata(value: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(value, (str, bytes)):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, Mapping) else None


def _changes(read: Callable[[str], Iterable[tuple]], tables: set) -> List[Change]:
    changes: List[Change] = []
    for table, (title_column, query) in _SIGNAL_TABLES.items():
        if table not in tables:
            continue
        for row_id, platform, link, title, raw in read(query):
            metadata = _metadata(raw)  # None when it is not a mapping: then it is left as it is.
            new_link, new_title, new_metadata = strip_stored_identity(str(platform), link, title, metadata or {})
            updates: Dict[str, Any] = {}
            if new_link != link:
                updates["source_url"] = new_link
            if new_title != title:
                updates[title_column] = new_title
            if metadata is not None and new_metadata != dict(metadata):
                updates["metadata"] = new_metadata
            if updates:
                changes.append((table, str(row_id), updates))
    if "topic_clusters" in tables:
        for row in read(f"SELECT id, {', '.join(_CLUSTER_TEXT)} FROM topic_clusters"):
            updates = {
                column: mask_author_identity_text(value)
                for column, value in zip(_CLUSTER_TEXT, row[1:])
                if mask_author_identity_text(value) != value
            }
            if updates:
                changes.append(("topic_clusters", str(row[0]), updates))
    return changes


def _manifest(changes: Sequence[Change], read: Callable[[str], Iterable[tuple]], tables: set) -> Dict[str, Any]:
    targets: Dict[str, Any] = {}
    for table, row_id, updates in changes:
        entry = targets.setdefault(table, {"ids": [], "fields": Counter()})
        entry["ids"].append(row_id)
        entry["fields"].update(updates.keys())
    observations = {row_id for table, row_id, _ in changes if table == "observations"}
    signals = {row_id for table, row_id, _ in changes if table == "trend_signals"}
    missions, claims = set(), set()
    if "mission_evidence" in tables:
        missions |= {str(m) for m, o in read("SELECT mission_id, observation_id FROM mission_evidence") if str(o) in observations}
    if "trend_signals" in tables:
        missions |= {str(m) for s, m in read("SELECT id, mission_id FROM trend_signals") if m and str(s) in signals}
    if "mission_claim_evidence" in tables:
        claims = {str(c) for c, o in read("SELECT claim_id, observation_id FROM mission_claim_evidence") if str(o) in observations}
    keys = 0
    if "sources" in tables:
        keys = sum(
            1 for (key,) in read("SELECT external_id FROM sources")
            if str(key).startswith("url:") and has_handle_segment(str(key)[len("url:"):])
        )
    return {
        "targets": {
            table: {"rows": len(entry["ids"]), "ids": sorted(entry["ids"]), "fields": dict(sorted(entry["fields"].items()))}
            for table, entry in sorted(targets.items())
        },
        "missions": sorted(missions),
        "bound_claims": len(claims),
        "source_keys_not_rewritten": keys,
    }


def _run(
    store: str,
    tables: set,
    read: Callable[[str], Iterable[tuple]],
    write: Callable[[Sequence[Change]], None],
    apply: bool,
) -> Dict[str, Any]:
    changes = _changes(read, tables)
    report = {"store": store, "mode": "apply" if apply else "dry-run", **_manifest(changes, read, tables)}
    if apply:
        # The manifest goes out before anything is written (FR-015).
        print(json.dumps({"manifest": report}, sort_keys=True), file=sys.stderr, flush=True)
        write(changes)
        report["readback"] = {"remaining_targets": len(_changes(read, tables)), "rows_changed": len(changes)}
    return report


def _sqlite(path: Path, apply: bool) -> Dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"No SQLite store at {path}; nothing was created.")
    mode = "rw" if apply else "ro"
    conn = sqlite3.connect(f"file:{path.resolve()}?mode={mode}", uri=True)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

        def write(changes: Sequence[Change]) -> None:
            with conn:
                for table, row_id, updates in changes:
                    values = [
                        json.dumps(value, ensure_ascii=False) if column == "metadata" else value
                        for column, value in updates.items()
                    ]
                    assignments = ", ".join(f'"{column}" = ?' for column in updates)
                    conn.execute(f'UPDATE "{table}" SET {assignments} WHERE id = ?', (*values, row_id))

        return _run("sqlite", tables, lambda query: conn.execute(query).fetchall(), write, apply)
    finally:
        conn.close()


def _postgres(variable: str, apply: bool) -> Dict[str, Any]:
    dsn = os.environ.get(variable)
    if not dsn:
        raise SystemExit(f"The environment variable {variable} is not set.")
    try:
        import psycopg
        from psycopg import sql
        from psycopg.types.json import Jsonb

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

            def write(changes: Sequence[Change]) -> None:
                for table, row_id, updates in changes:
                    assignments = sql.SQL(", ").join(
                        sql.SQL("{} = %s").format(sql.Identifier(column)) for column in updates
                    )
                    values = [Jsonb(value) if column == "metadata" else value for column, value in updates.items()]
                    conn.execute(
                        sql.SQL("UPDATE public.{} SET {} WHERE id = %s").format(sql.Identifier(table), assignments),
                        (*values, row_id),
                    )

            report = _run("postgres", tables, lambda query: conn.execute(query).fetchall(), write, apply)
            if apply:
                conn.commit()
            else:
                conn.rollback()
            return report
    except SystemExit:
        raise
    except Exception as error:  # The message can carry connection details or values; only its type is shown.
        raise SystemExit(f"Could not anonymise the store named by {variable}: {type(error).__name__}.") from None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sqlite", type=Path, help="Path to an Ignis SQLite store.")
    source.add_argument("--database-url-env", help="Name of the environment variable holding a PostgreSQL DSN.")
    parser.add_argument("--apply", action="store_true", help="Rewrite the targets; without it nothing is written.")
    args = parser.parse_args(argv)
    if args.sqlite:
        report = _sqlite(args.sqlite, args.apply)
    else:
        report = _postgres(args.database_url_env, args.apply)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
