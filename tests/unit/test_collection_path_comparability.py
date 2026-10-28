"""Spec 020: path identity is checked before source dedup on both period axes."""
from datetime import date, datetime, timedelta

import pytest

from ignis.domain import watchlist_period as d
from ignis.domain.listening_period import LISTENING_TZ, PeriodKind, period_of
from ignis.domain.watchlist import ListeningPlan

TOPIC = {"name": "Synthetic", "keywords": ["synthetic"]}
HOST = {"collection_path": "host_browser:threads-search-top-v1", "connector_revision": "threads-search-top-v1",
        "sampling": {"ordering": "top_visible_sample", "limit": 20}}
LEGACY = {"source": "threads_browser_session", "tier": "TIER_1_BROWSER_SESSION"}


def at(day, hour=12):
    return datetime.combine(day, datetime.min.time(), LISTENING_TZ).replace(hour=hour)


def probe(day, path, items=(), channel="threads"):
    result = d.SeenSnapshot(channel, "EMPTY_NO_DATA" if not items else "HEALTHY", ("synthetic",),
                            at(day, 22), True, tuple(items))
    # Attach the proposed internal field without requiring a new constructor before behavioral RED.
    object.__setattr__(result, "path_metadata", path)
    return result


def row(key, day, path, *, observed=None, channel="threads", counters=None):
    return d.PeriodItem(key, channel, at(day), "synthetic body", "", None, True, ("synthetic",),
                        ((observed or at(day, 21), 0, {**path, "views": 10, **(counters or {})}),))


def compare(axis, previous, current, *, kind="week", empty=False, extra=()):
    period = period_of(PeriodKind(kind), date(2026, 10, 19))
    items, probes = [], []
    for span, paths in ((period.previous(), previous), (period, current)):
        for i, day in enumerate(span.days):
            path = paths[i % len(paths)]
            rs = () if empty else (row("same" if i else str(day), day, path),)
            items.extend(rs)
            probes.append(probe(day, path, rs))
    if extra:
        items.extend(extra)
    if axis == "created":
        return d.compare_periods(topics=[TOPIC], items=items, coverage=probes, period=period,
            now=at(period.last_day + timedelta(days=2)), policy=d.TermsPolicy(), versions={})["topics"][0]["channels"][0]
    plans = [ListeningPlan(at(period.previous().start, 0), "Compare", kind, min(28, len(period.days)))]
    return d.compare_seen_periods(topics=[TOPIC], snapshots=probes, plans=plans, period=period,
                                  policy=d.TermsPolicy())[0][0]


@pytest.mark.parametrize("axis", ["seen", "created"])
@pytest.mark.parametrize("kind", ["day", "week", "month"])
@pytest.mark.parametrize("empty", [False, True])
def test_changed_path_suppresses_delta_even_for_empty_probes(axis, kind, empty):
    result = compare(axis, [LEGACY], [HOST], kind=kind, empty=empty)
    assert result["status"] == "not_comparable"
    assert "collection_path_changed" in result["reasons"]
    assert "indicators" not in result


@pytest.mark.parametrize("axis", ["seen", "created"])
@pytest.mark.parametrize("before,after,reason", [
    ([HOST], [{}], "collection_path_unknown"),
    ([{}], [HOST], "collection_path_unknown"),
    ([HOST, {}], [HOST], "collection_path_mixed"),
    ([HOST], [HOST, {}], "collection_path_mixed"),
    ([HOST, {}], [HOST, {}], "collection_path_mixed"),
    ([HOST, LEGACY], [HOST, LEGACY], "collection_path_mixed"),
    ([HOST], [{**HOST, "connector_revision": "v2"}], "collection_path_changed"),
    ([HOST], [{**HOST, "sampling": {"ordering": "top_visible_sample", "limit": 10}}], "collection_path_changed"),
    ([HOST], [{**HOST, **LEGACY}], "collection_path_unknown"),
])
def test_unknown_mixed_revision_sampling_and_conflicting_paths_refuse(axis, before, after, reason):
    result = compare(axis, before, after)
    assert result["status"] == "not_comparable"
    assert reason in result["reasons"]


@pytest.mark.parametrize("axis", ["seen", "created"])
def test_equal_proved_paths_preserve_measurements_and_report_basis(axis):
    result = compare(axis, [HOST], [HOST])
    assert result["status"] == "comparable"
    assert result["collection_paths"]["current"][0]["collection_path"] == HOST["collection_path"]
    assert result["collection_paths"]["current"][0]["basis"] == "explicit_metadata"


def test_created_counter_window_detects_a_later_path_before_selecting_counter():
    period = period_of(PeriodKind.WEEK, date(2026, 10, 19))
    extra = row(str(period.start), period.start, LEGACY, observed=at(period.last_day + timedelta(days=1)))
    result = compare("created", [HOST], [HOST], extra=[extra])
    assert "collection_path_mixed" in result["reasons"]


@pytest.mark.parametrize("axis", ["seen", "created"])
@pytest.mark.parametrize("precision", ["rounded", "unknown"])
def test_structured_incomplete_or_rounded_counters_never_look_exact(axis, precision):
    metadata = {**HOST, "like_count": 1400, "reply_count": 2, "reposts": 1, "quotes": 3,
                "counters": [{"kind": "likes", "value": 1400, "precision": precision, "raw_display": "1.4K"}]}
    period = period_of(PeriodKind.DAY, date(2026, 10, 19))
    items = [row(str(day), day, metadata) for day in [period.previous().start, period.start]]
    probes = [probe(i.published_at.date(), HOST, [i]) for i in items]
    if axis == "created":
        cell = d.compare_periods(topics=[TOPIC], items=items, coverage=probes, period=period,
             now=at(period.start + timedelta(days=2)), policy=d.TermsPolicy(), versions={})["topics"][0]["channels"][0]
        kind = "interactions"
    else:
        cell = d.compare_seen_periods(topics=[TOPIC], snapshots=probes,
             plans=[ListeningPlan(at(period.previous().start, 0), "Compare", "day", 1)], period=period,
             policy=d.TermsPolicy())[0][0]
        kind = "interactions_visible"
    assert cell["counter_components"]["current"][0][0]["raw_display"] == "1.4K"
    metric = next(i for i in cell["indicators"] if i["kind"] == kind)
    assert metric["current"] is None and metric["uncounted_items"]["current"] == 1


@pytest.mark.parametrize("axis", ["seen", "created"])
def test_random_transport_fields_do_not_change_path_identity(axis):
    result = compare(axis, [{**HOST, "request_id": "first", "captured_at": "old"}],
        [{**HOST, "request_id": "second", "sampling": {**HOST["sampling"], "session_id": "ignored"}}])
    assert result["status"] == "comparable"
    assert "request_id" not in str(result["collection_paths"])


@pytest.mark.parametrize("axis", ["seen", "created"])
def test_same_post_on_multiple_paths_does_not_hide_a_mixed_sample(axis):
    result = compare(axis, [HOST], [HOST, LEGACY])
    assert "collection_path_mixed" in result["reasons"]


def test_explicit_legacy_threads_requires_both_metadata_fields():
    assert d.collection_path_identity(LEGACY)["collection_path"] == "playwright:threads_session"
    assert d.collection_path_identity({"source": "threads_browser_session"})["collection_path"] is None
    assert d.collection_path_identity({"tier": "TIER_1_BROWSER_SESSION"})["collection_path"] is None


@pytest.mark.parametrize("axis", ["seen", "created"])
@pytest.mark.parametrize("matching_row_relevant", [True, False])
def test_duplicate_source_other_query_cannot_hide_counter_path(axis, matching_row_relevant):
    period = period_of(PeriodKind.DAY, date(2026, 10, 19))
    old = row("old", period.previous().start, HOST)
    current = row("same", period.start, HOST)
    other = row("same", period.start, LEGACY, observed=at(period.start, 22))
    from dataclasses import replace
    current = replace(current, relevant=matching_row_relevant)
    other = replace(other, query_keywords=("different topic",))
    snapshots = [probe(period.previous().start, HOST, [old]), probe(period.start, HOST, [current, other])]
    topics = [TOPIC, {"name": "Other", "keywords": ["different topic"]}]
    if axis == "created":
        result = d.compare_periods(topics=topics, items=[old, current, other], coverage=snapshots,
            period=period, now=at(period.start + timedelta(days=2)), policy=d.TermsPolicy(), versions={})["topics"][0]["channels"][0]
    else:
        result = d.compare_seen_periods(topics=topics, snapshots=snapshots,
            plans=[ListeningPlan(at(period.previous().start, 0), "Compare", "day", 1)], period=period,
            policy=d.TermsPolicy())[0][0]
    assert result["status"] == "not_comparable"
    assert "collection_path_mixed" in result["reasons"]


def test_google_dated_appearances_keep_each_placement_path_anchor():
    period = period_of(PeriodKind.DAY, date(2026, 10, 19))
    rows = [row("same-term", day, path, channel="google") for day, path in [
        (period.previous().start, HOST), (period.start, LEGACY), (period.start + timedelta(days=1), HOST)]]
    probes = [probe(day, HOST, channel="google") for day in [period.previous().start, period.start]]
    result = d.compare_periods(topics=[TOPIC], items=rows, coverage=probes, period=period,
        now=at(period.start + timedelta(days=2)), policy=d.TermsPolicy(), versions={})["topics"][0]["channels"][0]
    assert result["status"] == "not_comparable"
    assert "collection_path_mixed" in result["reasons"]


def test_path_basis_is_a_classification_not_arbitrary_stored_text():
    path = d.collection_path_identity({**HOST, "collection_path_basis": "Synthetic Private Name"})
    assert path["basis"] == "explicit_metadata"
    assert "Synthetic Private Name" not in str(path)


@pytest.mark.parametrize("axis", ["seen", "created"])
@pytest.mark.parametrize("empty", [False, True])
def test_two_unknown_periods_preserve_legacy_comparison_without_path_fields(axis, empty):
    result = compare(axis, [{}], [{}], empty=empty)
    assert result["status"] == "comparable"
    assert "reasons" not in result and "collection_paths" not in result


@pytest.mark.parametrize("axis", ["seen", "created"])
@pytest.mark.parametrize("channel,views,interactions", [("youtube", 10, 3), ("reels", 20, 3), ("google", None, None)])
def test_unchanged_native_channels_without_provenance_keep_exact_indicators(axis, channel, views, interactions):
    period = period_of(PeriodKind.DAY, date(2026, 10, 19))
    rows = [d.PeriodItem(str(day), channel, at(day), "synthetic", "", None, True, ("synthetic",),
             ((at(day, 21), 10, {"views": 10, "likes": 1, "comments": 2,
                 "play_count": 20, "like_count": 2, "comment_count": 1}),))
            for day in [period.previous().start, period.start]]
    snapshots = [probe(r.published_at.date(), {}, [r], channel) for r in rows]
    if axis == "created":
        result = d.compare_periods(topics=[TOPIC], items=rows, coverage=snapshots, period=period,
            now=at(period.start + timedelta(days=2)), policy=d.TermsPolicy(), versions={})["topics"][0]["channels"][0]
        expected = {"youtube": {"new_uploads": 1}, "reels": {"views": 20, "interactions": 3},
                    "google": {"interest": 10}}[channel]
    else:
        result = d.compare_seen_periods(topics=[TOPIC], snapshots=snapshots,
            plans=[ListeningPlan(at(period.previous().start, 0), "Compare", "day", 1)], period=period,
            policy=d.TermsPolicy())[0][0]
        expected = {"relevant_shown": 1, "views_visible": views, "interactions_visible": interactions,
                    "first_seen": 1, "created_in_period": 1}
    assert result["status"] == "comparable"
    assert "reasons" not in result and "collection_paths" not in result
    assert {i["kind"] for i in result["indicators"]} == set(expected)
    for indicator in result["indicators"]:
        value = expected[indicator["kind"]]
        assert indicator["current"] == indicator["previous"] == value
        assert indicator["change"] == (None if value is None else {"absolute": 0, "relative": 0.0})
        missing = int(value is None)
        assert indicator["uncounted_items"] == {"current": missing, "previous": missing}


@pytest.mark.parametrize("axis", ["seen", "created"])
def test_threads_v1_and_language_independent_v2_periods_are_not_comparable(axis):
    current = {**HOST, "collection_path": "host_browser:threads-search-top-v2", "connector_revision": "threads-search-top-v2"}
    result = compare(axis, [HOST], [current])
    assert result["status"] == "not_comparable"
    assert "collection_path_changed" in result["reasons"]
