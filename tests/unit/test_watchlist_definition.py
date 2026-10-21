"""Watchlist definitions: limits, normalisation and a digest that ignores presentation (Spec 016)."""

import pytest

from ignis.domain.watchlist import (
    MAX_DISCOVERY_SHARE,
    MAX_KEYWORDS_PER_TOPIC,
    MAX_TOPICS,
    WatchlistDefinitionError,
    parse_watchlist_definition,
)


def topic(name="Low-sugar drinks", **overrides):
    value = {
        "name": name,
        "categories": ["bottled tea", "trà đóng chai"],
        "keywords": ["trà ít đường", "low sugar tea"],
        "brands": [{"platform": "tiktok", "account": "@BrandX", "declared_name": "Brand X"}],
        "discovery_share": 0.1,
    }
    value.update(overrides)
    return value


def refusal(definition):
    with pytest.raises(WatchlistDefinitionError) as caught:
        parse_watchlist_definition(definition)
    return caught.value.code


def test_valid_definition_normalises_brands_and_defaults_discovery():
    parsed = parse_watchlist_definition({"topics": [topic(discovery_share=None), topic("Matcha")]})
    first = parsed.topics[0]
    assert first.brands[0].platform == "tiktok"
    assert first.brands[0].account == "brandx"
    assert first.brands[0].declared_name == "Brand X"
    assert first.discovery_share == 0.0
    assert [t.name for t in parsed.topics] == ["Low-sugar drinks", "Matcha"]
    assert len(parsed.digest) == 64


def test_digest_ignores_whitespace_case_of_handles_and_key_order():
    a = parse_watchlist_definition({"topics": [topic()]})
    b = parse_watchlist_definition({"topics": [{
        "discovery_share": 0.1,
        "brands": [{"declared_name": " Brand X ", "account": "brandx", "platform": "TikTok"}],
        "keywords": [" trà ít đường", "low sugar tea "],
        "categories": ["bottled tea", "trà đóng chai"],
        "name": " Low-sugar drinks ",
    }]})
    assert a.digest == b.digest
    assert a.to_payload() == b.to_payload()


def test_digest_ignores_unicode_composition():
    import unicodedata
    composed = parse_watchlist_definition({"topics": [topic()]})
    decomposed = parse_watchlist_definition({"topics": [topic(
        keywords=[unicodedata.normalize("NFD", k) for k in topic()["keywords"]],
        categories=[unicodedata.normalize("NFD", c) for c in topic()["categories"]],
    )]})
    assert composed.digest == decomposed.digest


def test_digest_changes_with_meaning():
    a = parse_watchlist_definition({"topics": [topic()]})
    b = parse_watchlist_definition({"topics": [topic(keywords=["trà ít đường"])]})
    assert a.digest != b.digest


def test_payload_round_trips():
    parsed = parse_watchlist_definition({"topics": [topic()]})
    assert parse_watchlist_definition(parsed.to_payload()) == parsed


@pytest.mark.parametrize("definition,code", [
    ({"topics": []}, "NO_TOPICS"),
    ({"topics": [topic(f"t{i}") for i in range(MAX_TOPICS + 1)]}, "TOO_MANY_TOPICS"),
    ({"topics": [topic(keywords=[f"k{i}" for i in range(MAX_KEYWORDS_PER_TOPIC + 1)])]}, "TOO_MANY_KEYWORDS"),
    ({"topics": [topic(keywords=[])]}, "NO_KEYWORDS"),
    ({"topics": [topic(keywords=["matcha", " Matcha "])]}, "DUPLICATE_KEYWORD"),
    ({"topics": [topic(), topic(" low-sugar DRINKS")]}, "DUPLICATE_TOPIC"),
    ({"topics": [topic(discovery_share=MAX_DISCOVERY_SHARE + 0.01)]}, "DISCOVERY_SHARE_OUT_OF_RANGE"),
    ({"topics": [topic(discovery_share=-0.1)]}, "DISCOVERY_SHARE_OUT_OF_RANGE"),
    ({"topics": [topic(discovery_share=True)]}, "DISCOVERY_SHARE_OUT_OF_RANGE"),
    ({"topics": [topic(categories=[], discovery_share=0.1)]}, "DISCOVERY_NEEDS_CATEGORY"),
    ({"topics": [topic(brands=[{"platform": "myspace", "account": "x", "declared_name": "X"}])]}, "INVALID_BRAND"),
    ({"topics": [topic(brands=[{"platform": "tiktok", "account": "", "declared_name": "X"}])]}, "INVALID_BRAND"),
    ({"topics": [topic(brands=[{"platform": "tiktok", "account": "x", "declared_name": " "}])]}, "INVALID_BRAND"),
    ({"topics": [topic(brands=[{"platform": "tiktok", "account": "@x", "declared_name": "X"},
                               {"platform": "TikTok", "account": "X", "declared_name": "X2"}])]}, "DUPLICATE_BRAND"),
    ({"topics": [topic(name=" ")]}, "INVALID_DEFINITION"),
    ({"topics": [topic(keywords=["ok", 3])]}, "INVALID_DEFINITION"),
    ({"topics": [topic(extra="x")]}, "INVALID_DEFINITION"),
    ({"topics": [topic()], "extra": 1}, "INVALID_DEFINITION"),
    ([topic()], "INVALID_DEFINITION"),
])
def test_refusals(definition, code):
    assert refusal(definition) == code


def test_refusal_message_names_no_brand_account():
    with pytest.raises(WatchlistDefinitionError) as caught:
        parse_watchlist_definition({"topics": [topic(brands=[
            {"platform": "tiktok", "account": "@secrethandle", "declared_name": "S"},
            {"platform": "tiktok", "account": "SecretHandle", "declared_name": "S"},
        ])]})
    assert "secrethandle" not in str(caught.value).casefold()
