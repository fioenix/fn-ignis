"""What the persisted alias ledger reconciles, and what it must refuse to reconcile.

Threads and Instagram address one object by two values that are not translations of each other:
a numeric primary key and a permalink shortcode. The resolver keeps those namespaces apart, so
a sighting reached only by permalink files a second row for an object the corpus already holds.

Closing that gap needs evidence, and the only evidence this build accepts is one connector
record carrying both values. Every Threads and Reels emission path carries both, so the ledger
fills from ordinary ingress rather than from a backfill nobody can reproduce.

Both backends, because SQLite restates its schema in _ensure_schema while Postgres reads sql/.
A ledger that exists on one of them is not a reconciliation, it is a divergence.
"""

from datetime import datetime, timezone

import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType

THREADS_PK = "17912345678901234"
THREADS_SHORTCODE = "C2xYzAbCdEf"
THREADS_PERMALINK = f"https://www.threads.net/@author/post/{THREADS_SHORTCODE}"

REEL_PK = "17998877665544332"
REEL_SHORTCODE = "CzQwErTyUiO"
REEL_PERMALINK = f"https://www.instagram.com/reel/{REEL_SHORTCODE}/"


def signal(platform, source_url, metadata, metric=100.0, hour=1):
    return TrendSignal(
        platform=platform,
        raw_title="Alias ledger contract",
        metric_value=metric,
        source_url=source_url,
        geo_code=GeoCode.VN,
        captured_at=datetime(2026, 9, 15, hour, 0, tzinfo=timezone.utc),
        metadata=dict(metadata),
    )


# --- one record, one canonical object ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "permalink", "metadata", "canonical", "alias"),
    (
        (
            PlatformType.THREADS,
            THREADS_PERMALINK,
            {"post_id": THREADS_PK},
            "post:" + THREADS_PK,
            "post_shortcode:" + THREADS_SHORTCODE,
        ),
        (
            PlatformType.REELS,
            REEL_PERMALINK,
            {"reel_id": REEL_PK},
            "reel:" + REEL_PK,
            "reel_shortcode:" + REEL_SHORTCODE,
        ),
    ),
)
async def test_a_record_carrying_both_values_stores_one_object_and_records_the_alias(
    repository_case, platform, permalink, metadata, canonical, alias
):
    repository = repository_case.repository

    await repository.save_signals([signal(platform, permalink, metadata)])

    assert repository_case.source_external_ids() == [canonical], (
        "the record's own primary key is what the object is filed under"
    )
    aliases = repository_case.identity_aliases()
    assert len(aliases) == 1, f"{repository_case.name} recorded {len(aliases)} aliases for one record"
    recorded = aliases[0]
    assert recorded["platform"] == platform.value
    assert recorded["alias_external_id"] == alias
    assert recorded["canonical_external_id"] == canonical
    assert recorded["witnessed_by"] == "connector_record_co_witness"
    assert recorded["recorded_at"], "an alias with no provenance timestamp cannot be audited"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "permalink", "metadata", "canonical"),
    (
        (PlatformType.THREADS, THREADS_PERMALINK, {"post_id": THREADS_PK}, "post:" + THREADS_PK),
        (PlatformType.REELS, REEL_PERMALINK, {"reel_id": REEL_PK}, "reel:" + REEL_PK),
    ),
)
async def test_a_later_permalink_only_sighting_reads_back_to_the_canonical_object(
    repository_case, platform, permalink, metadata, canonical
):
    """The gap T010 closes. Before the ledger this second sighting filed a second row."""
    repository = repository_case.repository

    await repository.save_signals([signal(platform, permalink, metadata, hour=1)])
    await repository.save_signals([signal(platform, permalink, {}, metric=200.0, hour=2)])

    assert repository_case.source_external_ids() == [canonical], (
        "a permalink the ledger can resolve still produced a second canonical row"
    )
    assert repository_case.counts()["observations"] == 2, "a sighting was lost, not reconciled"


# --- what stays exactly as it was -------------------------------------------------------------


@pytest.mark.asyncio
async def test_without_a_ledger_entry_the_two_namespaces_are_still_two_objects(repository_case):
    """Metadata-only and URL-only, never co-witnessed: the pre-T010 behavior, unchanged.

    This is the invariant the ledger is built around rather than around it. Nothing may merge
    these two, because nothing has yet proved they are one object -- and on Threads a shortcode
    made only of digits would otherwise collide with somebody else's primary key.
    """
    repository = repository_case.repository

    await repository.save_signals([signal(PlatformType.THREADS, None, {"post_id": THREADS_PK})])
    await repository.save_signals([signal(PlatformType.THREADS, THREADS_PERMALINK, {}, hour=2)])

    assert sorted(repository_case.source_external_ids()) == sorted(
        ["post:" + THREADS_PK, "post_shortcode:" + THREADS_SHORTCODE]
    )
    assert repository_case.identity_aliases() == [], "an alias was invented without evidence"


@pytest.mark.asyncio
async def test_a_platform_that_declares_no_alias_pair_records_nothing(repository_case):
    """A YouTube record carries an id and a URL into one namespace; there is nothing to alias."""
    repository = repository_case.repository

    await repository.save_signals(
        [
            signal(
                PlatformType.YOUTUBE,
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                {"video_id": "dQw4w9WgXcQ"},
            )
        ]
    )

    assert repository_case.identity_aliases() == []
    assert repository_case.source_external_ids() == ["video:dQw4w9WgXcQ"]


# --- conflict, idempotence, and the boundaries an alias may not cross -------------------------


@pytest.mark.asyncio
async def test_registering_the_same_alias_again_changes_nothing(repository_case):
    """Ingress re-reads the same post every pass. Three passes, one ledger row."""
    repository = repository_case.repository

    for hour in (1, 2, 3):
        await repository.save_signals(
            [signal(PlatformType.THREADS, THREADS_PERMALINK, {"post_id": THREADS_PK}, hour=hour)]
        )

    aliases = repository_case.identity_aliases()
    assert len(aliases) == 1, f"repeated registration produced {len(aliases)} rows"
    assert aliases[0]["canonical_external_id"] == "post:" + THREADS_PK
    assert repository_case.counts()["observations"] == 3


@pytest.mark.asyncio
async def test_a_conflicting_claim_on_one_shortcode_never_merges_two_objects(repository_case):
    """Two records claim the same shortcode for different primary keys. One of them is wrong.

    The ledger cannot tell which, so it keeps the claim it already holds, files the second
    record under its own primary key, and leaves two rows where two objects were asserted. Two
    rows are a gap the audit can measure; a merge would be silent and unrecoverable.
    """
    repository = repository_case.repository
    other_pk = "17900000000000000"

    await repository.save_signals(
        [signal(PlatformType.THREADS, THREADS_PERMALINK, {"post_id": THREADS_PK})]
    )
    await repository.save_signals(
        [signal(PlatformType.THREADS, THREADS_PERMALINK, {"post_id": other_pk}, hour=2)]
    )

    aliases = repository_case.identity_aliases()
    assert len(aliases) == 1, "a conflicting claim was stored beside the one it contradicts"
    assert aliases[0]["canonical_external_id"] == "post:" + THREADS_PK, (
        "a later claim overwrote a recorded alias"
    )
    assert sorted(repository_case.source_external_ids()) == sorted(
        ["post:" + THREADS_PK, "post:" + other_pk]
    ), "two primary keys were fused by a shortcode they both claimed"


@pytest.mark.asyncio
async def test_the_ledger_refuses_a_second_canonical_for_one_alias_at_the_schema_level(
    repository_case,
):
    """The application guard is not the only thing holding this. The constraint is."""
    repository_case.insert_identity_alias("threads", "post_shortcode:DUP", "post:111")

    with pytest.raises(Exception):
        repository_case.insert_identity_alias("threads", "post_shortcode:DUP", "post:222")

    assert len(repository_case.identity_aliases()) == 1


@pytest.mark.asyncio
async def test_an_alias_does_not_cross_platforms(repository_case):
    """One shortcode value on Threads says nothing about the same value on Instagram."""
    repository = repository_case.repository

    await repository.save_signals(
        [
            signal(
                PlatformType.THREADS,
                f"https://www.threads.net/@a/post/{REEL_SHORTCODE}",
                {"post_id": THREADS_PK},
            )
        ]
    )
    await repository.save_signals(
        [signal(PlatformType.REELS, REEL_PERMALINK, {}, hour=2)]
    )

    assert sorted(repository_case.source_external_ids()) == sorted(
        ["post:" + THREADS_PK, "reel_shortcode:" + REEL_SHORTCODE]
    ), "a Threads alias resolved an Instagram permalink"


@pytest.mark.asyncio
async def test_an_alias_does_not_redirect_a_primary_key(repository_case):
    """Only the shortcode namespace is aliasable. A pk is canonical and stays canonical.

    Written against a ledger row that points one primary key at another -- which the write path
    must never produce and must never honour, or two canonical objects would collapse into one.
    """
    repository = repository_case.repository
    repository_case.insert_identity_alias("threads", "post:" + THREADS_PK, "post:17900000000000000")

    await repository.save_signals([signal(PlatformType.THREADS, None, {"post_id": THREADS_PK})])

    assert repository_case.source_external_ids() == ["post:" + THREADS_PK], (
        "a ledger row redirected an object that was already canonical"
    )


# --- rollback ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_batch_that_fails_leaves_no_alias_behind(repository_case):
    """The alias is registered inside the same transaction as the observation it came from.

    A batch that dies halfway must leave neither. An alias that survived the failure of the
    record that witnessed it would be a permanent merge instruction with no evidence behind it.
    """
    repository = repository_case.repository
    unserializable = signal(
        PlatformType.THREADS,
        THREADS_PERMALINK,
        {"post_id": THREADS_PK, "payload": object()},
    )

    with pytest.raises(Exception):
        await repository.save_signals([unserializable])

    assert repository_case.identity_aliases() == [], "an alias outlived the batch that wrote it"
    assert repository_case.counts()["sources"] == 0
