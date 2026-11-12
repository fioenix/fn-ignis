"""Pin the two existing host-browser sources before routing their consumers."""

from dataclasses import FrozenInstanceError
import re

import pytest

from ignis.domain.host_browser_sources import get_source
from ignis.infrastructure.connectors.host_browser.validator import _content_url, collection_path
from ignis.domain.host_browser_search import _version_for_source


@pytest.mark.parametrize(
    "name, origin, path, transport, record_path, content_path, canonical, version, ordering",
    [
        ("tiktok", "https://www.tiktok.com", "/search/video", "opener_post_message",
         r"^/@[A-Za-z0-9_.]+/video/[0-9]+$", "/@fixture/video/123456789",
         "https://www.tiktok.com/share/video/123456789", "tiktok-public-grid-v4", "visible_grid"),
        ("threads", "https://www.threads.com", "/search", "fragment_receive",
         r"^/(?:@[A-Za-z0-9_.]+/post/|t/)[A-Za-z0-9_-]+(?:/media)?/?$", "/@fixture/post/Ab_12/media",
         "https://www.threads.com/t/Ab_12", "threads-search-top-v2", "top_visible_sample"),
    ],
)
def test_existing_source_values(name, origin, path, transport, record_path, content_path, canonical, version, ordering):
    source = get_source(name)
    assert source.origin == origin
    assert source.search_path == path
    assert source.search_url("áo /?&") == origin + path + "?q=%C3%A1o%20%2F%3F%26"
    assert source.transport == transport
    assert source.record_path == record_path
    assert re.fullmatch(source.record_path, content_path)
    assert re.fullmatch(source.accepted_record_path, content_path)
    assert source.canonical_url(content_path) == canonical
    assert _content_url(name, origin + content_path) == canonical
    assert source.extractor_version == _version_for_source(name) == version
    assert source.platform == name
    assert source.sampling_ordering == ordering
    assert collection_path(name, version, 7) == {
        "collection_path": "host_browser:" + version,
        "connector_revision": version,
        "sampling": {"limit": 7, "ordering": ordering},
    }
    with pytest.raises(FrozenInstanceError):
        source.origin = "https://invalid.example"


@pytest.mark.parametrize("name", ["instagram", "reels", "", "THREADS"])
def test_unknown_source_is_refused(name):
    with pytest.raises(ValueError, match="Unsupported host search source"):
        get_source(name)


@pytest.mark.parametrize("name, path", [
    ("tiktok", "/share/video/00123"),
    ("threads", "/t/Ab_12/"),
    ("threads", "/@fixture/post/Ab_12/media/"),
])
def test_existing_canonical_inputs_remain_accepted(name, path):
    source = get_source(name)
    assert re.fullmatch(source.accepted_record_path, path)
    assert source.canonical_url(path) == _content_url(name, source.origin + path)
