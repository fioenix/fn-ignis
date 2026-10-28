"""Caller-local action vocabulary snapshots; labels never become market evidence."""

import re
import sqlite3
from contextlib import closing

from ignis.resources import sql_seed_file


def action_labels_from_rows(rows):
    """Group unambiguous locale/kind labels, failing closed on malformed vocabulary."""
    labels = {}
    for row in rows:
        domain = str(row.get("domain", ""))
        if not domain.startswith("threads_action_labels_"):
            continue
        match = re.fullmatch(r"threads_action_labels_([a-z]{2,8})", domain)
        kind = row.get("category")
        label = row.get("term")
        if not match or kind not in {"likes", "replies", "reposts", "shares"} or not isinstance(label, str) or not label.strip():
            raise ValueError("Invalid Threads action vocabulary")
        locale = match.group(1)
        current = labels.setdefault(locale, {})
        if kind in current or label.casefold() in {value.casefold() for value in current.values()}:
            raise ValueError("Ambiguous Threads action vocabulary")
        current[kind] = label
    return labels


def seeded_action_labels():
    """Read the shipped seed through an isolated table; tactical opens no caller store.

    Mission preparation instead reads the caller repository, including added locale rows.
    The ephemeral table shares the seed's unique key and does not transform persisted data.
    """
    seed = sql_seed_file("037_threads_action_labels.sql")
    if seed is None:
        return {}
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE market_lexicons (domain TEXT, term TEXT, category TEXT, "
                           "created_by TEXT, UNIQUE(domain, term))")
        connection.executescript(seed.read_text(encoding="utf-8"))
        return action_labels_from_rows([dict(row) for row in connection.execute("SELECT * FROM market_lexicons")])
