"""Spec 018: validation and exact-time selection of a user's listening plan."""
from datetime import datetime, timedelta, timezone

import pytest

from ignis.domain import watchlist
from ignis.domain.listening_period import LISTENING_TZ

NOW = datetime(2026, 10, 26, tzinfo=LISTENING_TZ)


@pytest.mark.parametrize('kind,count', [('day', 1), ('week', 7), ('month', 28)])
def test_plan_trims_the_goal_and_accepts_the_daily_ceiling(kind, count):
    plan = watchlist.ListeningPlan(NOW, '  Track demand.  ', kind, count)
    assert plan.goal == 'Track demand.'
    assert plan.to_payload() == {'effective_from': NOW.isoformat(), 'goal': 'Track demand.',
                                 'period_kind': kind, 'snapshots_per_period': count}
    assert watchlist.ListeningPlan(NOW, 'x' * 300, kind, 1).goal == 'x' * 300


@pytest.mark.parametrize('goal,kind,count', [
    ('', 'day', 1), ('  ', 'week', 1), ('x' * 301, 'month', 1), (None, 'day', 1),
    ('Track.', 'year', 1), ('Track.', 'day', 0), ('Track.', 'day', 2),
    ('Track.', 'week', 8), ('Track.', 'month', 29), ('Track.', 'week', -1),
    ('Track.', 'week', True), ('Track.', 'week', 1.5), ('Track.', 'week', '3'),
    ('Track.\x00', 'day', 1),
])
def test_invalid_plan_has_a_stable_reason(goal, kind, count):
    with pytest.raises(ValueError) as caught:
        watchlist.ListeningPlan(NOW, goal, kind, count)
    assert caught.value.code == 'INVALID_LISTENING_PLAN'


def test_plan_in_effect_uses_the_latest_eligible_instant_in_any_offset():
    first = watchlist.ListeningPlan(NOW, 'First.', 'week', 3)
    later = watchlist.ListeningPlan(NOW + timedelta(days=1), 'Later.', 'month', 4)
    assert watchlist.plan_in_effect([later, first], NOW.astimezone(timezone.utc)) == first
    assert watchlist.plan_in_effect([first, later], later.effective_from) == later
    assert watchlist.plan_in_effect([first], NOW - timedelta(microseconds=1)) is None
    assert watchlist.plan_in_effect([], NOW) is None
