"""Spec 018: per-snapshot measurements, independent of publication-day coverage."""
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from ignis.domain import watchlist_period as domain
from ignis.domain.listening_period import LISTENING_TZ, PeriodKind, period_of
from ignis.domain.watchlist import ListeningPlan

PERIOD = period_of(PeriodKind.WEEK, date(2026, 10, 26))
TOPIC = {"name": "Drinks", "keywords": ["matcha latte"]}
NOW = datetime(2026, 11, 2, tzinfo=LISTENING_TZ)


def at(day, hour=22):
    return datetime.combine(day, datetime.min.time(), LISTENING_TZ).replace(hour=hour)


def plan(count=2, start=None, kind="week"):
    return ListeningPlan(at(start or PERIOD.previous().start, 0), "Track drinks.", kind, count)


def item(key, day, *, published=None, relevant=True, metric=10, metadata=None, first=None):
    return domain.PeriodItem(str(key), "tiktok", published, "matcha latte trà sữa", "", None,
                             relevant, ("matcha latte",),
                             ((at(day, 21), metric, metadata or {"metric_kind": "views", "likes": 2}),),
                             first_seen=at(first or day, 21))


def snapshot(day, items=(), *, hour=22, status="HEALTHY", keywords=("matcha latte",), judged=True):
    assert hasattr(domain, "SeenSnapshot"), "The seen axis needs one snapshot per run and channel"
    return domain.SeenSnapshot("tiktok", status, keywords, at(day, hour), judged, tuple(items))


def compare(snapshots, plans=None, topics=None):
    assert hasattr(domain, "compare_seen_periods"), "The seen-axis comparator is missing"
    return domain.compare_seen_periods(topics=topics or [TOPIC], snapshots=snapshots,
                                      plans=[plan()] if plans is None else plans,
                                      period=PERIOD, policy=domain.TermsPolicy())


def cell(snapshots, plans=None):
    return compare(snapshots, plans)[0][0]


def two_periods(current=(), previous=()):
    return [snapshot(PERIOD.previous().days[i], rows) for i, rows in enumerate(previous)] + [
        snapshot(PERIOD.days[i], rows) for i, rows in enumerate(current)]


def indicator(cell, kind):
    return next(row for row in cell["indicators"] if row["kind"] == kind)


def test_counts_all_shown_items_and_averages_40_and_30_to_35():
    current = [[item(f"{i}:{n}", PERIOD.days[i], published=at(date(2026, 4, 1)))
                for n in range(count)] for i, count in enumerate((40, 30))]
    result = cell(two_periods(current, [[], []]))
    assert result["axis"] == "seen" and result["status"] == "comparable"
    assert result["snapshots"] == {"current": 2, "previous": 2}
    assert indicator(result, "relevant_shown")["current"] == 35
    assert indicator(result, "views_visible")["current"] == 350
    assert indicator(result, "interactions_visible")["current"] == 70
    assert indicator(result, "created_in_period")["current"] == 0


def test_repeated_item_counts_in_both_snapshots_but_is_first_seen_only_once():
    old, new = PERIOD.previous().last_day, PERIOD.start
    result = cell([snapshot(old, [item("same", old)]), snapshot(new, [item("same", new, first=old)])],
                  [plan(1)])
    assert indicator(result, "relevant_shown")["current"] == 1
    assert indicator(result, "relevant_shown")["previous"] == 1
    assert indicator(result, "first_seen")["current"] == 0
    assert indicator(result, "first_seen")["previous"] == 1


@pytest.mark.parametrize("held,expected", [(3, "not_comparable"), (4, "comparable"), (6, "comparable")])
def test_missing_at_most_twenty_percent_is_comparable(held, expected):
    result = cell(two_periods([[]] * held, [[]] * 5), [plan(5)])
    assert result["status"] == expected
    assert result["snapshots"] == {"current": held, "previous": 5}
    assert result["snapshots_called_for"] == {"current": 5, "previous": 5}
    if expected == "not_comparable":
        assert result["reasons"] == ["seen_period_missing_snapshots"]
        assert "indicators" not in result


@pytest.mark.parametrize("status", ["FAILED", "DEGRADED", "CEILING_REACHED", "RATE_LIMITED"])
def test_failed_and_ceiling_limited_outcomes_are_not_snapshots(status):
    result = cell([snapshot(PERIOD.start, status=status), snapshot(PERIOD.previous().start)], [plan(1)])
    assert result["snapshots"]["current"] == 0
    assert result["status"] == "not_comparable"


def test_partial_queries_only_cover_the_topic_they_queried():
    snapshots = two_periods([[], []], [[], []])
    snapshots = [replace(s, queried_keywords=("other",)) for s in snapshots]
    rows = compare(snapshots, topics=[TOPIC, {"name": "Other", "keywords": ["other"]}])
    assert rows[0][0]["snapshots"] == {"current": 0, "previous": 0}
    assert rows[1][0]["status"] == "comparable"
    assert cell([replace(s, queried_keywords=()) for s in snapshots])["snapshots"]["current"] == 0


def test_two_runs_on_one_day_are_two_snapshots():
    result = cell([snapshot(PERIOD.start, hour=20), snapshot(PERIOD.start, hour=22),
                   snapshot(PERIOD.previous().start, hour=20), snapshot(PERIOD.previous().start, hour=22)])
    assert result["snapshots"] == {"current": 2, "previous": 2}
    assert result["status"] == "comparable"


def test_three_snapshots_make_a_week_comparable_without_daily_coverage():
    result = cell(two_periods([[]] * 3, [[]] * 3), [plan(3)])
    assert result["status"] == "comparable"
    assert indicator(result, "relevant_shown")["current"] == 0


def test_unjudged_snapshots_never_read_as_measured_zero():
    snapshots = two_periods([[], []], [[], []])
    snapshots[-1] = replace(snapshots[-1], judged=False)
    result = cell(snapshots)
    assert result["status"] == "not_comparable"
    assert result["reasons"] == ["seen_period_unjudged_snapshots"]
    assert "indicators" not in result


def test_no_plan_in_effect_means_no_cadence():
    result = cell(two_periods([[], []], [[], []]), [])
    assert result["status"] == "not_comparable"
    assert result["reasons"] == ["seen_period_without_cadence"]
    assert result["snapshots_called_for"] == {"current": None, "previous": None}


def test_each_period_uses_the_plan_at_its_start_not_a_midperiod_change():
    plans = [plan(1), plan(2, PERIOD.start), plan(7, PERIOD.days[2])]
    result = cell(two_periods([[], []], [[]]), plans)
    assert result["status"] == "comparable"
    assert result["snapshots_called_for"] == {"current": 2, "previous": 1}


def test_cadence_for_another_period_kind_is_not_silently_converted():
    result = cell(two_periods([[], []], [[], []]), [plan(2, kind="month")])
    assert result["reasons"] == ["seen_period_without_cadence"]


def test_created_in_period_requires_a_plausible_publication_date():
    day = PERIOD.start
    rows = [item("created", day, published=at(day, 10)), item("undated", day),
            item("future", day, published=at(day + timedelta(days=1))),
            item("old", day, published=at(date(2026, 4, 1))),
            item("excluded", day, relevant=False, published=at(day, 10))]
    result = cell(two_periods([rows], [[]]), [plan(1)])
    assert indicator(result, "created_in_period")["current"] == 1
    assert indicator(result, "relevant_shown")["current"] == 4


def test_unknown_counters_are_null_and_report_uncounted_items():
    rows = [item("unknown", PERIOD.start, metadata={"metric_known": False})]
    result = cell(two_periods([rows], [[]]), [plan(1)])
    views = indicator(result, "views_visible")
    assert views["current"] is None and views["previous"] == 0
    assert views["uncounted_items"] == {"current": 1, "previous": 0}


def test_terms_are_averaged_per_snapshot_instead_of_growing_with_cadence():
    current = [[item(f"{i}:{j}", PERIOD.days[i]) for j in range(3)] for i in range(3)]
    previous = [[item(f"before:{j}", PERIOD.previous().start) for j in range(3)]]
    result = cell(two_periods(current, previous), [plan(1), plan(3, PERIOD.start)])
    assert result["rising_terms"] == []
    assert result["new_terms"] == []


def test_snapshot_time_uses_vietnam_boundary_even_when_stored_in_utc():
    from datetime import timezone
    snapshots = [snapshot(PERIOD.start, hour=0), snapshot(PERIOD.previous().start, hour=0)]
    result = cell([replace(s, completed_at=s.completed_at.astimezone(timezone.utc)) for s in snapshots], [plan(1)])
    assert result["snapshots"] == {"current": 1, "previous": 1}


@pytest.mark.parametrize("channel", ["google", "tiktok"])
def test_first_seen_uses_first_completed_snapshot_when_observations_are_reused(channel):
    old = PERIOD.previous().start
    observed = replace(item("same", old), channel=channel)
    snapshots = [replace(snapshot(old, [observed]), channel=channel),
                 replace(snapshot(PERIOD.start, [observed]), channel=channel)]
    result = cell(snapshots, [plan(1)])
    assert indicator(result, "first_seen")["previous"] == 1
    assert indicator(result, "first_seen")["current"] == 0


def test_first_seen_tracks_completion_order_for_overlapping_runs():
    day = PERIOD.previous().last_day
    early_capture = item("same", day)
    late_capture = replace(early_capture, observations=((at(day, 22), 10, {"metric_kind": "views"}),))
    snapshots = [snapshot(PERIOD.start, [early_capture], hour=1),
                 snapshot(day, [late_capture], hour=23)]
    result = cell(snapshots, [plan(1)])
    assert indicator(result, "first_seen")["previous"] == 1
    assert indicator(result, "first_seen")["current"] == 0
