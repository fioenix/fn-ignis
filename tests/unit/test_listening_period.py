"""T003 part B: calendar periods in Asia/Ho_Chi_Minh, placement, coverage and counted values (Spec 016)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from ignis.domain.listening_period import (
    MAX_MISSING_SHARE,
    Period,
    PeriodKind,
    comparable,
    counted_value,
    latest_complete_period,
    local_date,
    missing_days,
    period_of,
    place_observation,
)

UTC = timezone.utc


def utc(*args):
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize("kind,day,start,end", [
    (PeriodKind.DAY, date(2026, 10, 21), date(2026, 10, 21), date(2026, 10, 21)),
    # 21/10/2026 is a Wednesday; weeks run Monday to Sunday.
    (PeriodKind.WEEK, date(2026, 10, 21), date(2026, 10, 19), date(2026, 10, 25)),
    (PeriodKind.WEEK, date(2026, 10, 19), date(2026, 10, 19), date(2026, 10, 25)),
    (PeriodKind.WEEK, date(2026, 10, 25), date(2026, 10, 19), date(2026, 10, 25)),
    (PeriodKind.MONTH, date(2026, 2, 14), date(2026, 2, 1), date(2026, 2, 28)),
    (PeriodKind.MONTH, date(2028, 2, 29), date(2028, 2, 1), date(2028, 2, 29)),
    (PeriodKind.MONTH, date(2026, 12, 31), date(2026, 12, 1), date(2026, 12, 31)),
])
def test_period_bounds(kind, day, start, end):
    period = period_of(kind, day)
    assert (period.start, period.last_day) == (start, end)
    assert period.days[0] == start and period.days[-1] == end
    assert len(period.days) == (end - start).days + 1


def test_previous_period_crosses_month_and_year():
    assert period_of(PeriodKind.MONTH, date(2026, 1, 5)).previous() == Period(PeriodKind.MONTH, date(2025, 12, 1))
    assert period_of(PeriodKind.WEEK, date(2026, 1, 1)).previous().start == date(2025, 12, 22)
    assert period_of(PeriodKind.DAY, date(2026, 3, 1)).previous().start == date(2026, 2, 28)


def test_local_date_uses_ho_chi_minh_time():
    # 17:30 UTC on the 20th is 00:30 on the 21st in Vietnam (UTC+7).
    assert local_date(utc(2026, 10, 20, 17, 30)) == date(2026, 10, 21)
    assert local_date(utc(2026, 10, 20, 16, 59)) == date(2026, 10, 20)


def test_completion_is_the_end_of_the_last_local_day():
    week = period_of(PeriodKind.WEEK, date(2026, 10, 21))
    assert week.completes_at == datetime(2026, 10, 26, 0, 0, tzinfo=week.completes_at.tzinfo)
    assert not week.is_complete(utc(2026, 10, 25, 16, 59))
    assert week.is_complete(utc(2026, 10, 25, 17, 0))


def test_latest_complete_period():
    now = utc(2026, 10, 21, 3, 0)  # Wednesday 10:00 in Vietnam
    assert latest_complete_period(PeriodKind.DAY, now).start == date(2026, 10, 20)
    assert latest_complete_period(PeriodKind.WEEK, now).start == date(2026, 10, 12)
    assert latest_complete_period(PeriodKind.MONTH, now).start == date(2026, 9, 1)


@pytest.mark.parametrize("published,observed,expected", [
    (utc(2026, 10, 20, 18), utc(2026, 10, 22), (date(2026, 10, 21), "published")),
    (None, utc(2026, 10, 22, 1), (date(2026, 10, 22), "collection_date")),
    # After collection, or before 2005: implausible, so the collection date places it.
    (utc(2026, 10, 23), utc(2026, 10, 22, 1), (date(2026, 10, 22), "collection_date")),
    (utc(2004, 12, 31), utc(2026, 10, 22, 1), (date(2026, 10, 22), "collection_date")),
    (utc(2026, 10, 20), None, None),
    (None, None, None),
])
def test_placement(published, observed, expected):
    assert place_observation(published, observed) == expected


def test_missing_days_and_the_twenty_percent_rule():
    week = period_of(PeriodKind.WEEK, date(2026, 10, 21))
    complete = {date(2026, 10, 19) + timedelta(days=i) for i in range(7)} - {date(2026, 10, 21)}
    assert missing_days(week, complete) == [date(2026, 10, 21)]
    assert comparable(week, [date(2026, 10, 21)])  # 1/7 is under 20 percent
    assert not comparable(week, [date(2026, 10, 21), date(2026, 10, 22)])  # 2/7 is over
    month = period_of(PeriodKind.MONTH, date(2026, 9, 1))
    assert comparable(month, month.days[:6]) and not comparable(month, month.days[:7])
    assert MAX_MISSING_SHARE == 0.2


def test_counted_value_is_the_latest_within_the_window():
    published = utc(2026, 10, 1)
    observations = [
        (utc(2026, 10, 2), 100.0),
        (utc(2026, 10, 7, 23), 300.0),
        (utc(2026, 10, 8, 0, 1), 900.0),  # after 7 days: ignored, so the figure never grows later
    ]
    assert counted_value(published, observations, window_days=7) == 300.0
    assert counted_value(published, observations[2:], window_days=7) is None
    assert counted_value(None, observations, window_days=7) is None


def test_counted_value_ignores_observations_before_publication():
    published = utc(2026, 10, 5)
    observations = [(utc(2026, 10, 4), 500.0), (utc(2026, 10, 6), 40.0)]
    assert counted_value(published, observations, window_days=7) == 40.0
    assert counted_value(published, observations[:1], window_days=7) is None


def test_naive_timestamps_are_refused():
    naive = datetime(2026, 10, 21, 23, 30)
    aware = utc(2026, 10, 21, 12)
    with pytest.raises(ValueError, match="timezone-aware"):
        local_date(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        place_observation(naive, aware)
    with pytest.raises(ValueError, match="timezone-aware"):
        place_observation(aware, naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        counted_value(naive, [(aware, 1.0)], window_days=7)
    with pytest.raises(ValueError, match="timezone-aware"):
        counted_value(aware, [(naive, 1.0)], window_days=7)
    with pytest.raises(ValueError, match="timezone-aware"):
        period_of(PeriodKind.DAY, date(2026, 10, 21)).is_complete(naive)
