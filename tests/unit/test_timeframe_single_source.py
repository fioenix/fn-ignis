"""Every Timeframe member must have a day count, and an unknown one must be refused.

The behavioural containment is covered in tests/integration/test_timeframe_windows.py, on both
backends. What this module adds is the exhaustiveness the integration test cannot express: it
enumerates Timeframe itself, so adding a sixth member without a span fails here rather than
silently picking up whatever a default would have given it.
"""

import pytest

from ignis.domain.value_objects import Timeframe, timeframe_to_days


@pytest.mark.parametrize("timeframe", tuple(Timeframe), ids=[t.value for t in Timeframe])
def test_every_member_has_a_span(timeframe):
    assert timeframe_to_days(timeframe) > 0


def test_the_spans_are_strictly_increasing():
    """Ordering is the property the windows nest on; a flat or inverted pair breaks containment."""
    spans = [timeframe_to_days(t) for t in Timeframe]
    assert spans == sorted(spans)
    assert len(set(spans)) == len(spans)


def test_an_unknown_timeframe_is_refused_rather_than_defaulted():
    """It used to return 90 for anything unrecognised, reachable from plain user input."""
    with pytest.raises(ValueError) as refusal:
        timeframe_to_days("banana")
    assert "banana" in str(refusal.value)
    for member in Timeframe:
        assert member.value in str(refusal.value)
