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


@pytest.mark.parametrize("name", ["reels", "", "THREADS", "INSTAGRAM"])
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


def test_instagram_descriptor_routes_the_keyword_grid_without_the_retired_reels_surface():
    source = get_source("instagram")
    assert source.origin == "https://www.instagram.com"
    assert source.search_url("áo khoác") == "https://www.instagram.com/explore/search/keyword/?q=%C3%A1o%20kho%C3%A1c"
    assert source.transport == "fragment_receive"
    assert source.platform == "reels"
    assert source.extractor_version == _version_for_source("instagram") == "instagram-keyword-grid-v1"
    assert source.sampling_ordering == "visible_grid"
    for path in ("/p/DQx_1-a/", "/reel/DQx_1-a/", "/p/DQx_1-a"):
        assert re.fullmatch(source.record_path, path) and re.fullmatch(source.accepted_record_path, path)
        assert _content_url("instagram", source.origin + path) == "https://www.instagram.com/p/DQx_1-a"
    for raw in ("https://www.instagram.com/fixture.account/p/DQx_1-a/", "https://www.instagram.com/fixture.account/",
                "https://www.instagram.com/p/DQx_1-a/?igsh=1", "https://www.threads.com/t/DQx_1-a",
                "https://www.tiktok.com/share/video/123"):
        with pytest.raises(ValueError):
            _content_url("instagram", raw)


def test_each_source_names_the_mission_surface_that_admits_it():
    from ignis.domain.host_browser_sources import host_source_names
    assert host_source_names() == ("tiktok", "threads", "instagram")
    assert {name: get_source(name).connector_surface for name in host_source_names()} == {
        "tiktok": "tiktok_video", "threads": "threads", "instagram": "instagram_host_browser"}
