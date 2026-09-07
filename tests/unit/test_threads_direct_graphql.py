from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.connectors.meta_browser_ingress import (
    GraphQLDocIdCache,
    build_cookie_header,
    extract_search_suggestions,
    extract_token_from_storage,
    extract_trending_topics,
    fetch_graphql_direct,
)
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


# --- Fixtures & Mocks ---

SAMPLE_STORAGE_STATE = {
    "cookies": [
        {"name": "sessionid", "value": "test_session_123", "domain": ".threads.net"},
        {"name": "csrftoken", "value": "test_csrf_token_abc", "domain": ".threads.net"},
        {"name": "ds_user_id", "value": "999888777", "domain": ".threads.net"},
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
    header = build_cookie_header(SAMPLE_STORAGE_STATE)
    assert "sessionid=test_session_123" in header
    assert "csrftoken=test_csrf_token_abc" in header

    csrf = extract_token_from_storage(SAMPLE_STORAGE_STATE, "csrftoken")
    assert csrf == "test_csrf_token_abc"

    missing = extract_token_from_storage(SAMPLE_STORAGE_STATE, "non_existent")
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


# --- Tests for Direct GraphQL HTTP Fetch ---


@pytest.mark.asyncio
async def test_fetch_graphql_direct_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_TRENDING_TOPICS_PAYLOAD

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        payload = await fetch_graphql_direct(
            doc_id="doc_trending_001",
            variables={},
            storage_state=SAMPLE_STORAGE_STATE,
            lsd="AVq0",
            geo=GeoCode.VN,
        )

        assert payload is not None
        assert "data" in payload
        # Ensure correct headers were sent
        sent_headers = mock_post.call_args.kwargs["headers"]
        assert sent_headers["X-IG-App-ID"] == "238260118693652"
        assert "sessionid=test_session_123" in sent_headers["Cookie"]


@pytest.mark.asyncio
async def test_fetch_graphql_direct_error_returns_none_for_fallback():
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"errors": [{"message": "Invalid doc_id"}]}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        payload = await fetch_graphql_direct(
            doc_id="doc_invalid",
            variables={},
            storage_state=SAMPLE_STORAGE_STATE,
        )
        assert payload is None


# --- Tests for ThreadsPlugin with Direct GraphQL & Fallback ---


@pytest.mark.asyncio
async def test_threads_plugin_fetch_trending_topics_fast_path():
    plugin = ThreadsPlugin()
    plugin._browser_storage_state = AsyncMock(return_value=SAMPLE_STORAGE_STATE)

    # Set cached doc_id to test fast path
    GraphQLDocIdCache.set("trending_topics", "doc_trending_fast", "lsd_fast")

    with patch(
        "ignis.infrastructure.connectors.threads.threads_plugin.fetch_graphql_direct",
        new_callable=AsyncMock,
    ) as mock_direct:
        mock_direct.return_value = SAMPLE_TRENDING_TOPICS_PAYLOAD

        topics = await plugin.fetch_trending_topics(geo=GeoCode.VN, limit=5)
        assert len(topics) == 3
        assert topics[0]["topic"] == "AI Coding Assistant"
        mock_direct.assert_awaited_once()


@pytest.mark.asyncio
async def test_threads_plugin_fetch_search_suggestions_fast_path():
    plugin = ThreadsPlugin()
    plugin._browser_storage_state = AsyncMock(return_value=SAMPLE_STORAGE_STATE)

    GraphQLDocIdCache.set("search_suggestions", "doc_suggest_fast", "lsd_fast")

    with patch(
        "ignis.infrastructure.connectors.threads.threads_plugin.fetch_graphql_direct",
        new_callable=AsyncMock,
    ) as mock_direct:
        mock_direct.return_value = SAMPLE_SEARCH_SUGGESTIONS_PAYLOAD

        suggestions = await plugin.fetch_search_suggestions("ai coding", geo=GeoCode.VN, limit=5)
        assert len(suggestions) == 3
        assert "ai coding agent" in suggestions


@pytest.mark.asyncio
async def test_threads_plugin_search_signals_uses_fast_path():
    plugin = ThreadsPlugin()
    plugin._browser_storage_state = AsyncMock(return_value=SAMPLE_STORAGE_STATE)

    GraphQLDocIdCache.set("search_posts", "doc_search_fast", "lsd_fast")

    with patch(
        "ignis.infrastructure.connectors.threads.threads_plugin.fetch_graphql_direct",
        new_callable=AsyncMock,
    ) as mock_direct:
        mock_direct.return_value = SAMPLE_GRAPHQL_SEARCH_POSTS_PAYLOAD

        signals = await plugin.search_signals(["AI Agent"], geo=GeoCode.VN, limit=5)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.platform == PlatformType.THREADS
        assert "Chia sẻ kinh nghiệm tự động hóa quy trình" in sig.raw_title
        assert sig.metric_value == 890.0
        assert sig.metadata["username"] == "tech_lead_vn"
