import pytest

from ignis.infrastructure.connectors.meta_browser_ingress import (
    caption_text,
    coerce_int,
    extract_records,
    walk_dicts,
)

# Shaped like Meta's private GraphQL envelope: the post sits several wrappers deep.
THREADS_PAYLOAD = {
    "data": {
        "searchResults": {
            "edges": [
                {
                    "node": {
                        "thread": {
                            "thread_items": [
                                {
                                    "post": {
                                        "pk": "17900000000009",
                                        "code": "C9xYzAbc",
                                        "caption": {"text": "Shop mình đang tìm phần mềm quản lý kho cho 3 kênh bán"},
                                        "like_count": 412,
                                        "taken_at": 1788400000,
                                        "user": {"username": "fashion_ops_vn"},
                                        "text_post_app_info": {
                                            "direct_reply_count": 57,
                                            "repost_count": 9,
                                            "quote_count": 3,
                                        },
                                    }
                                }
                            ]
                        }
                    }
                }
            ]
        }
    }
}

REELS_PAYLOAD = {
    "data": {
        "recent": {
            "sections": [
                {
                    "layout_content": {
                        "medias": [
                            {
                                "media": {
                                    "pk": "18000000000009",
                                    "code": "C9abcDEF",
                                    "media_type": 2,
                                    "caption": {"text": "Review máy in tem đơn hàng cho shop online"},
                                    "like_count": 1820,
                                    "comment_count": 140,
                                    "play_count": 96400,
                                    "taken_at": 1788410000,
                                    "user": {"username": "ecom_tools"},
                                    "clips_metadata": {
                                        "music_info": {"music_asset_info": {"title": "Trending Audio 01"}}
                                    },
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }
}


# --- Shared extraction helpers ---


def test_walk_dicts_reaches_nodes_nested_inside_lists():
    found = [d for d in walk_dicts({"a": [{"b": {"c": 1}}]}) if "c" in d]
    assert found == [{"c": 1}]


def test_walk_dicts_is_depth_limited_so_a_hostile_payload_cannot_blow_the_stack():
    node = {"leaf": True}
    for _ in range(40):
        node = {"wrap": node}

    assert not any(d.get("leaf") for d in walk_dicts(node, max_depth=5))


def test_extract_records_deduplicates_and_respects_the_limit():
    payloads = [{"items": [{"pk": "1"}, {"pk": "1"}, {"pk": "2"}, {"pk": "3"}]}]

    records = extract_records(
        payloads,
        is_record=lambda n: "pk" in n,
        identity=lambda n: n.get("pk"),
        limit=2,
    )

    assert [r["pk"] for r in records] == ["1", "2"]


@pytest.mark.parametrize(
    "raw,expected",
    [("42", 42), (7.9, 7), (None, 0), ("", 0), ("abc", 0)],
)
def test_coerce_int_never_raises_on_meta_payload_noise(raw, expected):
    assert coerce_int(raw) == expected


def test_caption_text_handles_both_dict_and_plain_string_shapes():
    assert caption_text({"caption": {"text": " hi "}}) == "hi"
    assert caption_text({"caption": "hello"}) == "hello"
    assert caption_text({"text": "fallback"}) == "fallback"
    assert caption_text({}) == ""
