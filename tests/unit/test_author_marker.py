"""T004: per-mission author markers count voices without keeping who they are."""

import os
import re

from ignis.domain.author_identity import (
    AuthorConcentration,
    AuthorState,
    assign_author,
    author_marker,
)
from tests.fixtures import author_identity_sentinels as s

MISSION_A_KEY = os.urandom(32)
MISSION_B_KEY = os.urandom(32)


def test_a_marker_is_sixteen_hexadecimal_characters():
    marker = author_marker(MISSION_A_KEY, "tiktok:someone")

    assert re.fullmatch(r"[0-9a-f]{16}", marker)


def test_a_marker_is_stable_within_one_mission():
    first = assign_author("tiktok", s.tiktok_metadata(), s.TIKTOK_HANDLE_URL, MISSION_A_KEY)
    second = assign_author("tiktok", s.tiktok_metadata(), s.TIKTOK_HANDLE_URL, MISSION_A_KEY)

    assert first.state is AuthorState.KNOWN
    assert first.marker == second.marker


def test_the_same_author_gets_unrelated_markers_in_two_missions():
    in_a = assign_author("threads", s.threads_metadata(), s.THREADS_HANDLE_URL, MISSION_A_KEY)
    in_b = assign_author("threads", s.threads_metadata(), s.THREADS_HANDLE_URL, MISSION_B_KEY)

    assert in_a.marker != in_b.marker


def test_the_marker_never_contains_the_handle_or_id():
    assignment = assign_author("threads", s.threads_metadata(), s.THREADS_HANDLE_URL, MISSION_A_KEY)

    assert s.SENTINEL_THREADS_HANDLE not in assignment.marker
    assert s.SENTINEL_THREADS_USER_ID not in assignment.marker


def test_an_account_id_and_a_handle_of_one_author_are_one_reference():
    by_id = assign_author("threads", {"user_id": s.SENTINEL_THREADS_USER_ID}, None, MISSION_A_KEY)
    both = assign_author("threads", s.threads_metadata(), None, MISSION_A_KEY)

    assert by_id.marker == both.marker


def test_a_handle_only_in_the_url_still_identifies_the_author():
    from_url = assign_author("tiktok", {"item_id": s.TIKTOK_ITEM_ID}, s.TIKTOK_HANDLE_URL, MISSION_A_KEY)
    from_metadata = assign_author("tiktok", {"author": s.SENTINEL_TIKTOK_HANDLE}, None, MISSION_A_KEY)

    assert from_url.state is AuthorState.KNOWN
    assert from_url.marker == from_metadata.marker


def test_handles_are_matched_without_case_or_at_sign():
    upper = assign_author("tiktok", {"author": "@Sentinel.TikTok.Author"}, None, MISSION_A_KEY)
    lower = assign_author("tiktok", {"author": s.SENTINEL_TIKTOK_HANDLE}, None, MISSION_A_KEY)

    assert upper.marker == lower.marker


def test_ten_thousand_distinct_authors_are_counted_exactly():
    markers = [
        assign_author("tiktok", {"author": f"author{i}"}, None, MISSION_A_KEY).marker
        for i in range(10_000)
    ]

    assert len(set(markers)) == 10_000
    assert AuthorConcentration.from_assignments(
        [assign_author("tiktok", {"author": f"author{i}"}, None, MISSION_A_KEY) for i in range(10_000)]
    ).distinct_authors == 10_000


def test_a_missing_author_is_unknown_and_has_no_marker():
    assignment = assign_author("google", s.google_trends_metadata(), None, MISSION_A_KEY)

    assert assignment.state is AuthorState.UNKNOWN
    assert assignment.marker is None


def test_a_missing_encryption_key_makes_a_known_author_unavailable():
    assignment = assign_author("tiktok", s.tiktok_metadata(), s.TIKTOK_HANDLE_URL, None)

    assert assignment.state is AuthorState.UNAVAILABLE
    assert assignment.marker is None


def test_a_missing_author_stays_unknown_without_a_key():
    assignment = assign_author("google", s.google_trends_metadata(), None, None)

    assert assignment.state is AuthorState.UNKNOWN


def test_a_declared_account_is_declared_and_carries_no_marker():
    declared = {("tiktok", s.DECLARED_BRAND_HANDLE): "declared-1"}
    assignment = assign_author(
        "tiktok", {"author": "@" + s.DECLARED_BRAND_HANDLE.upper()}, None, MISSION_A_KEY, declared=declared
    )

    assert assignment.state is AuthorState.DECLARED
    assert assignment.declared_account_id == "declared-1"
    assert assignment.marker is None


def test_concentration_counts_unknown_and_unavailable_apart_from_authors():
    assignments = [
        assign_author("tiktok", {"author": "a"}, None, MISSION_A_KEY),
        assign_author("tiktok", {"author": "a"}, None, MISSION_A_KEY),
        assign_author("tiktok", {"author": "a"}, None, MISSION_A_KEY),
        assign_author("tiktok", {"author": "b"}, None, MISSION_A_KEY),
        assign_author("google", {}, None, MISSION_A_KEY),
        assign_author("tiktok", {"author": "c"}, None, None),
    ]

    concentration = AuthorConcentration.from_assignments(assignments)

    assert concentration.distinct_authors == 2
    assert concentration.unknown == 1
    assert concentration.unavailable == 1
    assert concentration.top_share == 0.75


def test_concentration_of_no_known_author_has_no_top_share():
    concentration = AuthorConcentration.from_assignments([assign_author("google", {}, None, MISSION_A_KEY)])

    assert concentration.distinct_authors == 0
    assert concentration.top_share is None
