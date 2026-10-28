from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ignis.infrastructure.connectors.meta_browser_ingress import (
    GraphQLDocIdCache,
    build_cookie_header,
    extract_search_suggestions,
    extract_token_from_storage,
    extract_trending_topics,
    fetch_graphql_direct,
)


# --- Fixtures & Mocks ---

SAMPLE_STORAGE_STATE = {
    "cookies": [
        {"name": name, "value": value, "domain": ".threads.net", "path": "/",
         "secure": True, "expires": -1, "httpOnly": True, "sameSite": "Lax"}
        for name, value in [("sessionid", "test_session_123"),
                            ("csrftoken", "test_csrf_token_abc"), ("ds_user_id", "999888777")]
    ]
}

SAMPLE_TRENDING_TOPICS_PAYLOAD = {
    "data": {
        "viewer": {
            "trending_topics": [
                {
                    "topic": "AI Coding Assistant",
                    "id": "tt_101",
                    "post_count_label": "45.2K bài viết",
                },
                {
                    "topic": {
                        "name": "Thị trường Bán lẻ 2026",
                        "title": "Thị trường Bán lẻ 2026",
                        "subtitle": "12.8K posts",
                    },
                    "id": "tt_102",
                },
                {
                    "trend": {
                        "name": "Chi phí SaaS cho Doanh nghiệp",
                    },
                    "subtitle": "8.5K posts",
                },
            ]
        }
    }
}

SAMPLE_SEARCH_SUGGESTIONS_PAYLOAD = {
    "data": {
        "search_suggestions": {
            "edges": [
                {"node": {"keyword": "ai coding agent"}},
                {"node": {"query": "ai coding assistant review"}},
                {"node": {"suggestion": "tự động hóa marketing threads"}},
            ]
        }
    }
}

SAMPLE_GRAPHQL_SEARCH_POSTS_PAYLOAD = {
    "data": {
        "searchResults": {
            "edges": [
                {
                    "node": {
                        "pk": "3399887766",
                        "code": "C9xSearch1",
                        "caption": {"text": "Chia sẻ kinh nghiệm tự động hóa quy trình với AI Agent"},
                        "like_count": 890,
                        "user": {"username": "tech_lead_vn"},
                        "text_post_app_info": {"direct_reply_count": 45, "repost_count": 12, "quote_count": 3},
                        "taken_at": 1725700000,
                    }
                }
            ]
        }
    }
}


# --- Tests for Ingress Helpers ---


@pytest.fixture(autouse=True)
def reset_runtime_config_defaults():
    from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager

    mgr = RuntimeConfigManager.get_instance()
    mgr._cache = dict(mgr._DEFAULTS)
    yield
    mgr._cache = dict(mgr._DEFAULTS)


def test_build_cookie_header_and_extract_token():
    header = build_cookie_header(SAMPLE_STORAGE_STATE, "https://www.threads.net/")
    assert "sessionid=test_session_123" in header
    assert "csrftoken=test_csrf_token_abc" in header

    csrf = extract_token_from_storage(SAMPLE_STORAGE_STATE, "csrftoken", "https://www.threads.net/")
    assert csrf == "test_csrf_token_abc"

    missing = extract_token_from_storage(SAMPLE_STORAGE_STATE, "non_existent", "https://www.threads.net/")
    assert missing is None


def test_graphql_doc_id_cache():
    GraphQLDocIdCache.set("test_query", "doc_12345", "lsd_abc")
    doc_id, lsd = GraphQLDocIdCache.get("test_query")
    assert doc_id == "doc_12345"
    assert lsd == "lsd_abc"

    GraphQLDocIdCache.record_signature_from_payload(
        "doc_search_99", "lsd_xyz", json.dumps({"query": "AI"})
    )
    search_doc, search_lsd = GraphQLDocIdCache.get("search_posts")
    assert search_doc == "doc_search_99"
    assert search_lsd == "lsd_xyz"


def test_extract_trending_topics():
    topics = extract_trending_topics([SAMPLE_TRENDING_TOPICS_PAYLOAD], limit=10)
    assert len(topics) == 3

    assert topics[0]["topic"] == "AI Coding Assistant"
    assert topics[0]["post_count"] == 45200
    assert "https://www.threads.net/search?q=" in topics[0]["search_url"]

    assert topics[1]["topic"] == "Thị trường Bán lẻ 2026"
    assert topics[1]["post_count"] == 12800

    assert topics[2]["topic"] == "Chi phí SaaS cho Doanh nghiệp"
    assert topics[2]["post_count"] == 8500


def test_extract_search_suggestions():
    suggestions = extract_search_suggestions([SAMPLE_SEARCH_SUGGESTIONS_PAYLOAD], limit=5)
    assert len(suggestions) == 3
    assert "ai coding agent" in suggestions
    assert "ai coding assistant review" in suggestions
    assert "tự động hóa marketing threads" in suggestions

    modern_payload = {
        "data": {
            "xdt_api__v1__text_feed__keyword_search": {
                "keywords": [
                    {"id": "1", "name": "thờitrang", "tag_community_info": None},
                    {"id": "2", "name": "thời trang nữ", "tag_community_info": None},
                    {"id": "3", "name": "thời trang công sở", "tag_community_info": None},
                ]
            }
        }
    }
    modern_suggestions = extract_search_suggestions([modern_payload], limit=5)
    assert len(modern_suggestions) == 3
    assert modern_suggestions == ["thờitrang", "thời trang nữ", "thời trang công sở"]


# --- Tests for Direct GraphQL HTTP Fetch ---


# --- Tests for ThreadsPlugin with Direct GraphQL & Fallback ---


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [None, "https://www.threads.com/api/graphql", "https://www.threads.net/api/graphql"])
async def test_retired_cookie_graphql_refuses_even_with_cached_doc_id_and_cookies(url):
    from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
    with patch("httpx.AsyncClient", side_effect=AssertionError("Retired cookie request")):
        with pytest.raises(ConnectorCapabilityUnavailableException, match="HOST_BROWSER_REQUIRED"):
            await fetch_graphql_direct("cached-doc", {"query": "synthetic"}, SAMPLE_STORAGE_STATE, url=url)
