"""T009: comparing two complete listening periods of a watchlist (Spec 016, US2).

Fixture: one watchlist topic, weeks 12-18 and 19-25 October 2026 (Monday to Sunday) in
Asia/Ho_Chi_Minh. YouTube and TikTok complete a collection every day; Reels misses three days of
the earlier week, which is more than 20 percent of seven.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from ignis.domain.listening_period import LISTENING_TZ, PeriodKind, period_of
from ignis.domain.watchlist_period import (
    PeriodCoverage,
    PeriodItem,
    TermsPolicy,
    channel_values,
    compare_periods,
)

UTC = timezone.utc
TOPIC = {"name": "Matcha drinks", "categories": ["đồ uống"], "keywords": ["matcha latte", "matcha muối"]}
CURRENT = period_of(PeriodKind.WEEK, date(2026, 10, 19))
NOW = datetime(2026, 10, 27, 9, tzinfo=LISTENING_TZ)
POLICY = TermsPolicy(rising_min_count=2, rising_min_growth=0.5, noise=frozenset({"xuhuong"}))


def at(day, hour=12):
    return datetime(day.year, day.month, day.day, hour, tzinfo=LISTENING_TZ)


def coverage(channel, days, keywords=("matcha latte",)):
    return [PeriodCoverage(channel=channel, status="HEALTHY", queried_keywords=tuple(keywords),
                           completed_at=at(day, 22)) for day in days]


def item(source, channel, published, observations, *, title="matcha latte ngon", relevant=True,
         metadata=None, keywords=("matcha latte",), link="https://example.test/v/1"):
    """observations: [(observed_at, metric_value, metadata overrides)]"""
    return PeriodItem(
        source_id=source, channel=channel, published_at=published, title=title, excerpt="",
        link=link, relevant=relevant, query_keywords=tuple(keywords),
        observations=tuple((observed, value, {**(metadata or {}), **extra})
                           for observed, value, extra in observations),
    )


ALL_DAYS = CURRENT.previous().days + CURRENT.days
REELS_DAYS = [d for d in ALL_DAYS if d not in CURRENT.previous().days[:3]]
COVERAGE = coverage("youtube", ALL_DAYS) + coverage("tiktok", ALL_DAYS) + coverage("reels", REELS_DAYS)
TIKTOK = {"metric_kind": "views", "metric_known": True}


def items():
    previous_day, current_day = CURRENT.previous().start, CURRENT.start
    return [
        # YouTube: one upload last week, two this week; an irrelevant one never counts.
        item("yt:1", "youtube", at(previous_day), [(at(previous_day, 20), 50, {})]),
        item("yt:2", "youtube", at(current_day), [(at(current_day, 20), 10, {})]),
        item("yt:3", "youtube", at(current_day + timedelta(days=2)), [(at(current_day + timedelta(days=2), 20), 10, {})]),
        item("yt:4", "youtube", at(current_day), [(at(current_day, 20), 999, {})], relevant=False),
        # TikTok: the same post collected twice; the observation after 7 days must not count.
        item("tt:1", "tiktok", at(previous_day), [
            (at(previous_day, 20), 100, {"likes": 5, "comments": 1, "shares": 0}),
            (at(previous_day + timedelta(days=6)), 400, {"likes": 9, "comments": 2, "shares": 1}),
            (at(previous_day + timedelta(days=9)), 9000, {"likes": 90, "comments": 20, "shares": 10}),
        ], metadata=TIKTOK),
        item("tt:2", "tiktok", at(current_day + timedelta(days=1)), [
            (at(current_day + timedelta(days=1), 20), 600, {"likes": 30, "comments": 3, "shares": 2}),
        ], metadata=TIKTOK, title="matcha latte trà sữa matcha muối"),
        # A TikTok post with unknown plays: listed, but its views are not counted.
        item("tt:3", "tiktok", at(current_day + timedelta(days=1)), [
            (at(current_day + timedelta(days=1), 21), 0, {"likes": 4, "comments": 0, "shares": 0}),
        ], metadata={"metric_kind": None, "metric_known": False}),
        # No publication date: placed by its collection day and flagged.
        item("tt:4", "tiktok", None, [(at(current_day + timedelta(days=3), 21), 70, {"likes": 1})],
             metadata=TIKTOK),
        item("rl:1", "reels", at(current_day), [(at(current_day, 20), 0, {"play_count": 80, "like_count": 8})]),
    ]


def compare(observations=None, outcomes=COVERAGE, period=CURRENT, now=NOW):
    return compare_periods(topics=[TOPIC], items=items() if observations is None else observations,
                           coverage=outcomes, period=period, now=now, policy=POLICY,
                           versions={CURRENT.start: [1], CURRENT.previous().start: [1]})


def cell(snapshot, channel):
    (topic,) = snapshot["topics"]
    return next(c for c in topic["channels"] if c["channel"] == channel)


def indicator(channel_cell, kind):
    return next(i for i in channel_cell["indicators"] if i["kind"] == kind)


def test_an_incomplete_period_is_refused_with_its_completion_time():
    snapshot = compare(now=datetime(2026, 10, 25, 23, 59, tzinfo=LISTENING_TZ))
    assert snapshot["status"] == "REFUSED"
    assert snapshot["reason_code"] == "PERIOD_INCOMPLETE"
    assert snapshot["completes_at"] == "2026-10-26T00:00:00+07:00"
    assert "topics" not in snapshot


def test_both_periods_carry_their_bounds_and_versions():
    snapshot = compare()
    assert snapshot["status"] == "OK"
    assert snapshot["periods"]["current"] == {"kind": "week", "start": "2026-10-19", "end": "2026-10-25",
                                              "timezone": "Asia/Ho_Chi_Minh", "versions": [1]}
    assert snapshot["periods"]["previous"]["start"] == "2026-10-12"


def test_youtube_counts_new_relevant_uploads():
    youtube = cell(compare(), "youtube")
    assert youtube["status"] == "comparable"
    uploads = indicator(youtube, "new_uploads")
    assert (uploads["current"], uploads["previous"]) == (2, 1)
    assert uploads["change"] == {"absolute": 1, "relative": 1.0}
    assert youtube["measured_on_sample"] is False


def test_a_counter_counts_the_latest_observation_within_seven_days():
    tiktok = cell(compare(), "tiktok")
    views = indicator(tiktok, "views")
    # tt:1 counts 400 (day 6), never 9000 (day 9); tt:3 has no known plays.
    assert views["previous"] == 400
    assert views["current"] == 600 + 70
    interactions = indicator(tiktok, "interactions")
    assert interactions["previous"] == 9 + 2 + 1
    assert interactions["current"] == (30 + 3 + 2) + 4 + 1
    assert views["uncounted_items"]["current"] == 1
    assert tiktok["measured_on_sample"] is True


def test_a_later_collection_never_changes_an_earlier_period():
    before = indicator(cell(compare(), "tiktok"), "views")["previous"]
    later = items()
    later.append(item("tt:1", "tiktok", at(CURRENT.previous().start), [
        (at(CURRENT.start + timedelta(days=5)), 50000, {"likes": 500})], metadata=TIKTOK))
    assert indicator(cell(compare(later), "tiktok"), "views")["previous"] == before


def test_a_channel_missing_more_than_a_fifth_of_its_days_is_not_comparable():
    reels = cell(compare(), "reels")
    assert reels["status"] == "not_comparable"
    assert reels["missing_days"]["previous"] == ["2026-10-12", "2026-10-13", "2026-10-14"]
    assert reels["reasons"] == ["previous_period_missing_days"]
    for key in ("indicators", "rising_terms", "new_terms"):
        assert key not in reels


def test_a_failed_or_degraded_collection_does_not_complete_a_day():
    degraded = [PeriodCoverage(c.channel, "DEGRADED", c.queried_keywords, c.completed_at)
                if c.channel == "youtube" else c for c in COVERAGE]
    assert cell(compare(outcomes=degraded), "youtube")["status"] == "not_comparable"


def test_a_day_whose_evidence_is_not_judged_is_not_a_measured_zero():
    """FR-010 counts only judged evidence, so a day collected but never judged would read as a
    measured zero (G3 period views, 25/10/2026). It is shown as unjudged and not compared."""
    unjudged_day = CURRENT.days[2]
    outcomes = [PeriodCoverage(c.channel, c.status, c.queried_keywords, c.completed_at,
                               judged=not (c.channel == "youtube" and c.completed_at.date() == unjudged_day))
                for c in COVERAGE]
    youtube = cell(compare(outcomes=outcomes), "youtube")
    assert youtube["status"] == "not_comparable"
    assert youtube["reasons"] == ["current_period_unjudged_days"]
    assert youtube["unjudged_days"] == {"current": [unjudged_day.isoformat()], "previous": []}
    assert youtube["missing_days"] == {"current": [], "previous": []}
    assert "indicators" not in youtube
    assert "unjudged_days" not in cell(compare(), "youtube")


def test_one_unjudged_run_beside_a_judged_one_still_marks_the_day_unjudged():
    """Two runs on one day, one judged and one not: counting only the judged one would silently
    undercount the day, so the day stays unjudged until every run is judged."""
    day = CURRENT.days[2]
    extra = PeriodCoverage("youtube", "HEALTHY", ("matcha latte",), at(day, 23), judged=False)
    youtube = cell(compare(outcomes=COVERAGE + [extra]), "youtube")
    assert youtube["status"] == "not_comparable"
    assert youtube["unjudged_days"] == {"current": [day.isoformat()], "previous": []}


def test_a_collection_for_another_topic_does_not_cover_this_one():
    other = [PeriodCoverage(c.channel, c.status, ("áo khoác",), c.completed_at)
             if c.channel == "youtube" else c for c in COVERAGE]
    assert cell(compare(outcomes=other), "youtube")["status"] == "not_comparable"


def test_no_value_is_summed_across_channels():
    snapshot = compare()
    (topic,) = snapshot["topics"]
    assert set(topic) == {"name", "channels", "items"}
    for channel_cell in topic["channels"]:
        assert set(channel_cell) <= {"channel", "status", "measured_on_sample", "indicators", "basis",
                                     "rising_terms", "new_terms", "missing_days", "reasons"}


def test_basis_counts_publication_and_collection_dates():
    tiktok = cell(compare(), "tiktok")
    assert tiktok["basis"] == {"current": {"published": 2, "collection_date": 1},
                               "previous": {"published": 1, "collection_date": 0}}


def test_an_implausible_publication_date_falls_back_to_collection():
    observed = at(CURRENT.start + timedelta(days=2), 20)
    future = item("tt:9", "tiktok", observed + timedelta(days=30), [(observed, 5, {"likes": 1})], metadata=TIKTOK)
    tiktok = cell(compare(items() + [future]), "tiktok")
    assert tiktok["basis"]["current"]["collection_date"] == 2


def test_an_undated_item_first_seen_before_both_periods_is_in_neither():
    """Its period is fixed by its first sighting, not by which runs a comparison reads (T018)."""
    import dataclasses

    seen_again = at(CURRENT.start + timedelta(days=2), 20)
    first_seen = at(CURRENT.previous().start - timedelta(days=5), 20)
    undated = item("tt:old", "tiktok", None, [(seen_again, 300, {"likes": 3})], metadata=TIKTOK)
    without = cell(compare(items() + [undated]), "tiktok")
    with_first = cell(compare(items() + [dataclasses.replace(undated, first_seen=first_seen)]), "tiktok")

    assert without["basis"]["current"]["collection_date"] == 2
    assert with_first["basis"]["current"]["collection_date"] == 1
    assert with_first["basis"]["previous"]["collection_date"] == 0


def test_a_google_appearance_keeps_its_own_date_whatever_the_first_sighting():
    """A Google Trends term is measured per dated appearance; an older sighting never moves it."""
    import dataclasses

    day = CURRENT.start + timedelta(days=1)
    appearance = item("g:term", "google", at(day, 8), [(at(day, 20), 70, {})], keywords=("matcha latte",))
    google_coverage = coverage("google", ALL_DAYS)
    plain = cell(compare([appearance], outcomes=google_coverage), "google")
    seen_earlier = dataclasses.replace(appearance, first_seen=at(CURRENT.previous().start - timedelta(days=9)))
    with_first = cell(compare([seen_earlier], outcomes=google_coverage), "google")

    assert with_first["basis"] == plain["basis"]
    assert with_first["basis"]["current"]["published"] == 1


def test_new_and_rising_terms_exclude_the_query_and_noise():
    tiktok = cell(compare(), "tiktok")
    terms = {t["term"] for t in tiktok["new_terms"]}
    assert "trà sữa" in terms
    assert not any(t in ("matcha latte", "matcha muối") for t in terms)
    for term in tiktok["new_terms"] + tiktok["rising_terms"]:
        assert set(term) == {"term", "current_items", "previous_items", "basis"}


def test_up_to_three_items_carry_content_only():
    (topic,) = compare()["topics"]
    assert 0 < len(topic["items"]) <= 3
    for shown in topic["items"]:
        assert set(shown) == {"excerpt", "link", "channel", "published_on", "basis"}
    assert {i["channel"] for i in topic["items"]} <= {"youtube", "tiktok", "reels"}


def test_a_link_naming_an_account_is_withheld():
    risky = item("tt:7", "tiktok", at(CURRENT.start), [(at(CURRENT.start, 20), 10**9, {"likes": 1})],
                 metadata=TIKTOK, link=None)
    (topic,) = compare(items() + [risky])["topics"]
    tiktok = [shown for shown in topic["items"] if shown["channel"] == "tiktok"]
    assert tiktok[0]["link"] is None


def test_items_take_channels_in_turn():
    (topic,) = compare()["topics"]
    assert [shown["channel"] for shown in topic["items"]] == ["youtube", "tiktok", "reels"]


def test_a_measured_period_with_no_items_is_zero_not_unknown():
    only_current = [i for i in items() if i.channel != "tiktok" or i.source_id != "tt:1"]
    views = indicator(cell(compare(only_current), "tiktok"), "views")
    assert views["previous"] == 0 and views["change"] == {"absolute": 670, "relative": None}


def test_mentions_links_and_tokens_never_become_terms():
    noisy = item("tt:8", "tiktok", at(CURRENT.start), [(at(CURRENT.start, 20), 5, {"likes": 1})], metadata=TIKTOK,
                 title="@[user] matcha @[declared:3f2a1b4c] @someone ghé https://shopee.vn/x [link] matcha latte")
    terms = {t["term"] for t in cell(compare(items() + [noisy]), "tiktok")["new_terms"]}
    assert not any(word in term for term in terms for word in ("user", "declared", "3f2a1b4c", "someone", "shopee", "https", "link"))


SECOND = {"name": "Jackets", "keywords": ["áo khoác"], "brands": [{"platform": "tiktok", "account": "bx", "declared_name": "Brand X"}]}


def multi(observations, outcomes=COVERAGE):
    jackets = [PeriodCoverage(c.channel, c.status, ("áo khoác",), c.completed_at) for c in outcomes]
    return compare_periods(topics=[TOPIC, SECOND], items=observations, coverage=list(outcomes) + jackets,
                           period=CURRENT, now=NOW, policy=POLICY, versions={})


def test_with_several_topics_the_query_decides_and_text_matches_whole_words():
    day = CURRENT.start
    found = [
        item("m:1", "youtube", at(day), [(at(day, 20), 1, {})], title="áo khoác đi mưa", keywords=("matcha latte",)),
        item("b:1", "youtube", at(day), [(at(day, 20), 1, {})], title="review mới", keywords=("Brand X",)),
        item("t:1", "youtube", at(day), [(at(day, 20), 1, {})], title="báo áo khoác", keywords=()),
        item("t:2", "youtube", at(day), [(at(day, 20), 1, {})], title="báo khoác ngoài", keywords=()),
    ]
    matcha, jackets = multi(found)["topics"]
    count = lambda topic: indicator(next(c for c in topic["channels"] if c["channel"] == "youtube"), "new_uploads")["current"]  # noqa: E731
    assert count(matcha) == 1   # m:1 only: its query was a matcha keyword
    assert count(jackets) == 2  # b:1 by its brand query, t:1 by the whole words "áo khoác"


def test_a_month_compares_with_the_month_before():
    october = period_of(PeriodKind.MONTH, date(2026, 10, 5))
    snapshot = compare(period=october, now=datetime(2026, 11, 1, 0, 1, tzinfo=LISTENING_TZ))
    assert snapshot["periods"]["current"]["start"] == "2026-10-01"
    assert snapshot["periods"]["previous"] == {"kind": "month", "start": "2026-09-01", "end": "2026-09-30",
                                               "timezone": "Asia/Ho_Chi_Minh", "versions": []}


@pytest.mark.parametrize("metadata,expected", [
    ({"source": "threads_trending_topics"}, {}),
    ({"views": 120, "like_count": 4, "reply_count": 1, "reposts": 0, "quotes": 0}, {"views": 120, "interactions": 5}),
    ({"like_count": 4, "reply_count": 1}, {"interactions": 5}),
    ({"views": 0, "like_count": 0, "reply_count": 0, "reposts": 0, "quotes": 0}, {}),
])
def test_threads_values_read_the_field_that_means_them(metadata, expected):
    assert channel_values("threads", 1000.0, metadata) == expected


@pytest.mark.parametrize("channel,metric,metadata,expected", [
    ("reels", 55.0, {"play_count": 80, "like_count": 8, "comment_count": 2}, {"views": 80, "interactions": 10}),
    ("reels", 8.0, {"like_count": 8}, {"interactions": 8}),
    ("tiktok", 300.0, {"metric_kind": "views", "likes": 2, "comments": 1, "shares": 0}, {"views": 300, "interactions": 3}),
    ("tiktok", 0.0, {"metric_kind": None, "metric_known": False}, {}),
    ("google", 2000.0, {"raw_traffic": "2K+"}, {"interest": 2000}),
    ("youtube", 900.0, {"views": 900}, {}),
])
def test_channel_values_never_mix_units(channel, metric, metadata, expected):
    assert channel_values(channel, metric, metadata) == expected


def test_only_a_relevant_observation_is_counted():
    day = CURRENT.start
    judged = item("tt:5", "tiktok", at(day), [(at(day, 20), 10, {"likes": 1})], metadata=TIKTOK)
    unjudged = item("tt:5", "tiktok", at(day), [(at(day + timedelta(days=2)), 9000, {"likes": 90})],
                    metadata=TIKTOK, relevant=False)
    only = [i for i in items() if i.channel != "tiktok"] + [judged, unjudged]
    assert indicator(cell(compare(only), "tiktok"), "views")["current"] == 10


def test_each_google_appearance_is_measured_in_its_own_period():
    trends = [PeriodCoverage("google", "HEALTHY", ("matcha latte",), at(day, 22)) for day in ALL_DAYS]
    previous_day, current_day = CURRENT.previous().start, CURRENT.start
    google = [item("g:matcha latte", "google", at(day), [(at(day, 20), value, {})])
              for day, value in ((previous_day, 100), (current_day, 300))]
    interest = indicator(cell(compare(google, outcomes=trends), "google"), "interest")
    assert (interest["previous"], interest["current"]) == (100, 300)


def test_a_recorded_query_from_a_removed_topic_keeps_the_item_out():
    day = CURRENT.start
    jacket = item("j:1", "youtube", at(day), [(at(day, 20), 1, {})], title="áo khoác", keywords=("áo khoác",))
    assert indicator(cell(compare(items() + [jacket]), "youtube"), "new_uploads")["current"] == 2


def test_terms_never_span_the_title_and_the_excerpt():
    day = CURRENT.start
    post = PeriodItem(source_id="th:1", channel="tiktok", published_at=at(day), title="matcha latte trà",
                      excerpt="sữa ngon", link=None, relevant=True, query_keywords=("matcha latte",),
                      observations=((at(day, 20), 5, {**TIKTOK, "likes": 1}),))
    terms = {t["term"] for t in cell(compare(items() + [post]), "tiktok")["new_terms"]}
    assert "trà sữa" in terms  # from tt:2's title, where it really occurs
    assert not any(term.startswith("trà ") and term.endswith("sữa") for term in terms if term != "trà sữa")
    assert "latte trà" in terms and "sữa ngon" in terms
    boundary = {t["term"]: t["current_items"] for t in cell(compare(items() + [post]), "tiktok")["new_terms"]}
    assert boundary["trà sữa"] == 1  # th:1 must not add a second "trà sữa" across its fields


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["inf", "-3", "nan", "many"])
async def test_a_non_finite_or_invalid_counting_window_falls_back_to_the_default(raw):
    """T018: the configured window cannot overflow the date arithmetic."""
    from ignis.application.use_cases.watchlist_period import MAX_COUNTER_DAYS, GetWatchlistPeriodSnapshotUseCase

    class _Config:
        async def get_runtime_config(self, key):
            return raw

    use_case = GetWatchlistPeriodSnapshotUseCase(_Config(), None, lambda: NOW)
    assert await use_case._config("listening.counter_observation_days", 7) == 7
    assert MAX_COUNTER_DAYS == 31
