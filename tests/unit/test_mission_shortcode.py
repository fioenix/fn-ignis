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


def test_shortcode_fits_the_postgresql_column_and_keeps_its_suffix():
    """PostgreSQL stores shortcode as VARCHAR(50); a long title must not overflow it or lose the UUID suffix."""
    mission = ResearchMission(
        title="Internationalization Decentralization research",
        keywords=["k"],
        id=UUID("abcd1234-0000-4000-8000-000000000001"),
        timeframe="30d",
    )

    assert len(mission.shortcode) <= 50
    assert mission.shortcode.endswith("-ABCD1234")
