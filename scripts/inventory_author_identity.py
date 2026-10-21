#!/usr/bin/env python3
"""Count the author identity a store already holds, without showing any of it (Spec 015, US4).

Read-only by construction: SQLite opens with `mode=ro`, PostgreSQL runs in a READ ONLY
transaction. The output is JSON counts per table and field -- rows whose metadata holds an author
field (and which keys), links that name an account, source keys derived from such links, and
@mentions in stored text. No value is ever printed, and a PostgreSQL DSN is read from the
environment variable named by --database-url-env and never echoed.

What to do with what it finds is the owner's decision (Spec 015 FR-015, OG-3); this script only
measures.

    python scripts/inventory_author_identity.py --sqlite .fnignis/canonical.sqlite3
    python scripts/inventory_author_identity.py --database-url-env DATABASE_URL
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from ignis.domain.author_identity import AUTHOR_FIELD_KEYS, has_handle_segment, strip_author_identity
from ignis.infrastructure.security.pii_sanitizer import MENTION_PATTERN

# (table, column, kind). "metadata" fields are JSON, "link" fields URLs, "key" a source key and
# "text" stored prose that may carry @mentions.
FIELDS: Tuple[Tuple[str, str, str], ...] = (
    ("observations", "metadata", "metadata"),
    ("observations", "source_url", "link"),
    ("observations", "observed_title", "text"),
    ("sources", "external_id", "key"),
    ("trend_signals", "metadata", "metadata"),
    ("trend_signals", "source_url", "link"),
    ("trend_signals", "raw_title", "text"),
    ("topic_clusters", "canonical_name", "text"),
    ("topic_clusters", "topic_label", "text"),
    ("topic_clusters", "summary_text", "text"),
)


def _keys_present(value: Any, found: set) -> set:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in AUTHOR_FIELD_KEYS and item not in (None, "", [], {}):
                found.add(key)
            _keys_present(item, found)
    elif isinstance(value, list):
        for item in value:
            _keys_present(item, found)
    return found


class _FieldCount:
    def __init__(self, kind: str):
        self.kind = kind
        self.matching = 0
        self.by_key: Counter = Counter()

    def add(self, value: Any) -> None:
        if value is None:
            return
        if self.kind == "metadata":
            data = value
            if isinstance(value, (str, bytes)):
                try:
                    data = json.loads(value)
                except ValueError:
                    return
            if not isinstance(data, Mapping):
                return
            if strip_author_identity(data) != dict(data):
                self.matching += 1
            self.by_key.update(_keys_present(data, set()))
        elif self.kind == "link":
            self.matching += has_handle_segment(str(value))
        elif self.kind == "key":
            text = str(value)
            self.matching += text.startswith("url:") and has_handle_segment(text[len("url:"):])
        else:
            self.matching += bool(MENTION_PATTERN.search(str(value)))

    def payload(self) -> Dict[str, Any]:
        if self.kind == "metadata":
            return {"rows_with_author_identity": self.matching, "by_key": dict(sorted(self.by_key.items()))}
        name = {"link": "handle_links", "key": "handle_keys", "text": "mentions"}[self.kind]
        return {name: self.matching}


def _inventory(tables: Iterable[str], rows_of: Callable[[str, List[str]], Iterable[tuple]]) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    present = set(tables)
    for table in dict.fromkeys(table for table, _, _ in FIELDS):
        if table not in present:
            report[table] = {"absent": True}
            continue
        fields = [(column, kind) for name, column, kind in FIELDS if name == table]
        counts = {column: _FieldCount(kind) for column, kind in fields}
        total = 0
        for row in rows_of(table, [column for column, _ in fields]):
            total += 1
            for (column, _), value in zip(fields, row):
                counts[column].add(value)
        report[table] = {"rows": total, "fields": {column: count.payload() for column, count in counts.items()}}
    return report


def _sqlite(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"No SQLite store at {path}; nothing was created.")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]

        def rows_of(table: str, columns: List[str]) -> Iterable[tuple]:
            existing = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            selected = ", ".join(f'"{c}"' if c in existing else "NULL" for c in columns)
            yield from conn.execute(f'SELECT {selected} FROM "{table}"')

        return {"store": "sqlite", "read_only": True, "tables": _inventory(tables, rows_of)}
    finally:
        conn.close()


def _postgres(variable: str) -> Dict[str, Any]:
    dsn = os.environ.get(variable)
    if not dsn:
        raise SystemExit(f"The environment variable {variable} is not set.")
    try:
        import psycopg
        from psycopg import sql

        with psycopg.connect(dsn) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables"
                    " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            ]

            def rows_of(table: str, columns: List[str]) -> Iterable[tuple]:
                existing = {
                    row[0]
                    for row in conn.execute(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema = 'public' AND table_name = %s",
                        (table,),
                    )
                }
                selected = sql.SQL(", ").join(
                    sql.Identifier(c) if c in existing else sql.SQL("NULL") for c in columns
                )
                with conn.cursor(name=f"inventory_{table}") as cursor:
                    cursor.execute(sql.SQL("SELECT {} FROM public.{}").format(selected, sql.Identifier(table)))
                    yield from cursor

            report = {"store": "postgres", "read_only": True, "tables": _inventory(tables, rows_of)}
            conn.rollback()
            return report
    except SystemExit:
        raise
    except Exception as error:  # The message can carry connection details; only its type is shown.
        raise SystemExit(f"Could not read the store named by {variable}: {type(error).__name__}.") from None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sqlite", type=Path, help="Path to an Ignis SQLite store, opened read-only.")
    source.add_argument("--database-url-env", help="Name of the environment variable holding a PostgreSQL DSN.")
    args = parser.parse_args(argv)
    report = _sqlite(args.sqlite) if args.sqlite else _postgres(args.database_url_env)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
