"""Derive a TikTok video's publication time from its id (Spec 025 FR-007).

The upper 32 bits of a TikTok video id are the Unix second the video was published. This was checked
against rendered dates before use (specs/025-host-browser-skill-pack/research.md, T016). The derivation is
deterministic and returns None whenever the id cannot be trusted, so an unknown date stays unknown.
"""

import re
from datetime import datetime, timedelta, timezone

# Ids before this date did not carry a timestamp in this layout; refuse rather than guess.
_EARLIEST = datetime(2016, 9, 1, tzinfo=timezone.utc)
_FUTURE_TOLERANCE = timedelta(days=1)
_MAX_ID = (1 << 64) - 1


def published_at_from_video_id(video_id, *, captured_at: datetime) -> datetime | None:
    """Return the publish time encoded in ``video_id``, or None when it does not parse or is implausible.

    A time up to one day after ``captured_at`` is clamped to ``captured_at`` (clock skew); later than that
    the id is not trusted.
    """
    if not isinstance(video_id, str) or not re.fullmatch(r"[0-9]{1,20}", video_id):
        return None
    value = int(video_id)
    if value > _MAX_ID:
        return None
    published = datetime.fromtimestamp(value >> 32, tz=timezone.utc)
    if published < _EARLIEST or published > captured_at + _FUTURE_TOLERANCE:
        return None
    return min(published, captured_at)
