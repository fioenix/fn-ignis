"""Spec 025 FR-007: a TikTok video id carries its publish second in the upper 32 bits."""

from datetime import datetime, timedelta, timezone

import pytest

from ignis.domain.tiktok_video_id import published_at_from_video_id

CAPTURED = datetime(2026, 11, 12, 7, 47, 57, tzinfo=timezone.utc)


@pytest.mark.parametrize(("video_id", "expected"), [
    # Checked against the rendered date on 2026-11-12 (research.md, T016).
    ("7643765792374361362", datetime(2026, 5, 25, 9, 55, 9, tzinfo=timezone.utc)),
    ("7555873331275222280", datetime(2025, 9, 30, 13, 27, 31, tzinfo=timezone.utc)),
    ("7381292723459869969", datetime(2024, 6, 17, 2, 25, 35, tzinfo=timezone.utc)),
])
def test_a_valid_id_decodes_to_its_publish_second(video_id, expected):
    assert published_at_from_video_id(video_id, captured_at=CAPTURED) == expected


@pytest.mark.parametrize("video_id", ["", "abc", "12a4", "-7643765792374361362", "7643765792374361362 ", None])
def test_a_non_numeric_id_leaves_the_date_unknown(video_id):
    assert published_at_from_video_id(video_id, captured_at=CAPTURED) is None


def test_an_id_before_september_2016_leaves_the_date_unknown():
    before = int(datetime(2016, 8, 31, tzinfo=timezone.utc).timestamp()) << 32
    assert published_at_from_video_id(str(before), captured_at=CAPTURED) is None


def test_an_id_more_than_one_day_after_capture_leaves_the_date_unknown():
    later = int((CAPTURED + timedelta(days=1, seconds=1)).timestamp()) << 32
    assert published_at_from_video_id(str(later), captured_at=CAPTURED) is None


def test_an_id_within_one_day_after_capture_is_clamped_to_the_capture_time():
    """Clock skew between TikTok and the host must not put publication after capture."""
    skewed = int((CAPTURED + timedelta(hours=2)).timestamp()) << 32
    assert published_at_from_video_id(str(skewed), captured_at=CAPTURED) == CAPTURED


def test_an_id_too_large_for_64_bits_leaves_the_date_unknown():
    assert published_at_from_video_id(str(1 << 64), captured_at=CAPTURED) is None
