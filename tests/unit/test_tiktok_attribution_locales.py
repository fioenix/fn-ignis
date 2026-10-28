"""Locale snapshots isolate tactical seeds and caller-local mission vocabulary."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
from ignis.infrastructure.connectors.host_browser.attribution_locales import (
    attribution_locales_from_rows, seeded_attribution_locales,
)
from ignis.infrastructure.config.vocabulary_loader import load_market_vocabulary
from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer


def test_seed_is_additive_idempotent_and_excluded_from_market_terms():
    root = Path(__file__).resolve().parents[2]
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE market_lexicons (domain TEXT, term TEXT, category TEXT, created_by TEXT, UNIQUE(domain,term))")
        db.executescript((root / "sql/034_tiktok_attribution.sql").read_text())
        old = [tuple(row) for row in db.execute("SELECT * FROM market_lexicons")]
        db.execute("CREATE TABLE observations (excerpt TEXT)")
        db.execute("INSERT INTO observations VALUES ('unchanged')")
        seed = (root / "sql/038_tiktok_attribution_locales.sql").read_text()
        db.executescript(seed)
        db.executescript(seed)
        assert [tuple(row) for row in db.execute("SELECT * FROM market_lexicons WHERE domain='tiktok_attribution'")] == old
        assert db.execute("SELECT excerpt FROM observations").fetchone()[0] == "unchanged"
        rows = [dict(row) for row in db.execute("SELECT * FROM market_lexicons")]
        assert attribution_locales_from_rows(rows) == seeded_attribution_locales() == {"vi": ("do {author} tạo với",)}


@pytest.mark.asyncio
async def test_locale_rows_never_enter_positive_vocabulary():
    repo = AsyncMock()
    repo.get_domain_lexicons.return_value = [dict(domain="tiktok_attribution_vi", category="ui_attribution", term="do {author} tạo với")]
    assert (await load_market_vocabulary(repo)).positive_terms == []


@pytest.mark.parametrize("domain,term", [("tiktok_attribution_vi_VN", "do {author} tạo với"), ("tiktok_attribution_en", "no slot")])
def test_invalid_locale_vocabulary_fails_closed(domain, term):
    with pytest.raises(ValueError, match="Invalid"):
        attribution_locales_from_rows([dict(domain=domain, term=term, category="ui_attribution")])


def test_tactical_uses_packaged_seed_and_ticket_freezes_locale_templates(monkeypatch):
    from ignis.application.use_cases import host_browser_search as module
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    service = HostBrowserSearchService()
    try:
        mapping = {"en": ["created by {author} with"]}
        request = service.prepare("task", "session", ["test"], 3, 60, True, attribution_locales=mapping)
        mapping["en"].clear()
        payload = host_answer(request)
        payload["answers"][0]["locale"] = "en"
        payload["answers"][0]["records"][0]["excerpt"] = "Caption created by Fixture Poster with music"
        service.stage(request["request_id"], payload)
        assert service.submit(request["request_id"], "task", "session")["observations"][0]["excerpt"] == "Caption"
        tactical = service.prepare("task", "session", ["test"], 3, 60, True)
        payload = host_answer(tactical)
        payload["answers"][0]["locale"] = "en"
        service.stage(tactical["request_id"], payload)
        assert service.submit(tactical["request_id"], "task", "session")["observations"] == []
        assert "Fixture Poster" not in json.dumps(service._tickets[tactical["request_id"]]["receipt"])
    finally:
        service.close()
