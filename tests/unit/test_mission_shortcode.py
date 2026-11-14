from uuid import UUID

from ignis.domain.entities import ResearchMission


def test_missions_sharing_a_uuid_prefix_get_distinct_shortcodes():
    """Same title, geo and timeframe must not collide when the UUIDs share their first four hex digits."""
    first = ResearchMission(
        title="Same title", keywords=["k"], id=UUID("abcd0000-0000-4000-8000-000000000001")
    )
    second = ResearchMission(
        title="Same title", keywords=["k"], id=UUID("abcd1111-0000-4000-8000-000000000002")
    )

    assert first.shortcode != second.shortcode
