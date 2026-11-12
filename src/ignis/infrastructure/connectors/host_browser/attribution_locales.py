"""Locale-qualified attribution snapshots for host sources' accessible image labels."""

import re
import sqlite3
from contextlib import closing

from ignis.domain.host_browser_sources import get_source
from ignis.resources import sql_seed_file


def attribution_locales_from_rows(rows, source="tiktok"):
    """Read caller vocabulary, refusing malformed attribution domains or templates."""
    get_source(source)
    prefix = source + "_attribution_"
    locales = {}
    for row in rows:
        domain = str(row.get("domain", ""))
        if not domain.startswith(prefix):
            continue
        match = re.fullmatch(re.escape(prefix) + r"([a-z]{2,8})", domain)
        term = row.get("term")
        if (not match or row.get("category") != "ui_attribution" or not isinstance(term, str)
                or term.count("{author}") != 1 or not all(part.strip() for part in term.split("{author}"))):
            raise ValueError("Invalid host attribution vocabulary")
        locales.setdefault(match.group(1), []).append(term)
    return {locale: tuple(terms) for locale, terms in locales.items()}


def seeded_attribution_locales(source="tiktok"):
    """Tactical uses the packaged seed in memory without opening a caller store."""
    seed = sql_seed_file(get_source(source).attribution_locale_seed)
    if seed is None:
        return {}
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE market_lexicons (domain TEXT, term TEXT, category TEXT, "
                           "created_by TEXT, UNIQUE(domain, term))")
        connection.executescript(seed.read_text(encoding="utf-8"))
        return attribution_locales_from_rows([dict(row) for row in connection.execute("SELECT * FROM market_lexicons")],
                                             source)
