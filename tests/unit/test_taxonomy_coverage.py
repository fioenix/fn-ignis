"""Category classification is limited by taxonomy vocabulary, not by the matcher.

On the live corpus 378 clusters sat in `unclassified`. The matcher was not at fault: given the
seeded taxonomies it classifies "Khoa hoc AI cho nguoi moi bat dau" as education, "Review son
moi 3CE" as beauty and "Lai suat ngan hang" as finance, and correctly declines football and
gold prices, which are not market verticals. What it could not classify was "chatgpt va gpt-6"
or "meo phat am tieng anh" -- both squarely inside a vertical it tracks, both missing a keyword.

Six verticals held 44 keywords between them. These tests pin the coverage the classifier needs
and keep the two seed files from drifting apart, which is how the SQLite and Postgres backends
have diverged before.
"""

import re
from pathlib import Path

import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer

SQL = Path(__file__).resolve().parents[2] / "sql"
TAXONOMY_ROW = re.compile(r"\('([^']+)',\s*'([^']+)',\s*ARRAY\[([^\]]+)\]\)")


def _taxonomies_from(filename: str) -> dict:
    text = (SQL / filename).read_text(encoding="utf-8")
    return {
        code: sorted(re.findall(r"'([^']+)'", blob))
        for code, _name, blob in TAXONOMY_ROW.findall(text)
    }


def _clusterer() -> SemanticClusterer:
    clusterer = SemanticClusterer()
    clusterer.register_taxonomies(
        [
            {"industry_code": code, "keywords": keywords}
            for code, keywords in _taxonomies_from("003_market_lexicons.sql").items()
        ]
    )
    return clusterer


def _signal(title: str) -> TrendSignal:
    return TrendSignal(
        platform=PlatformType.THREADS,
        raw_title=title,
        metric_value=1.0,
        geo_code=GeoCode.VN,
        source_url=f"https://example.test/{abs(hash(title))}",
    )


@pytest.mark.parametrize(
    "title,expected",
    [
        # Titles the live corpus left unclassified while sitting inside a tracked vertical.
        ("chatgpt va gpt-6 khac nhau the nao", "tech"),
        ("meo phat am tieng anh cho nguoi moi", "education"),
        ("dung blender dung scene bang ai", "tech"),
        ("gia vang hom nay tang manh", "finance"),
        ("livestream chot don tren tiktok shop", "ecommerce"),
        ("phoi do di lam mua thu", "fashion"),
        ("routine duong da buoi toi", "beauty"),
        # Already working, kept so expansion cannot regress them.
        ("khoa hoc ai cho nguoi moi bat dau", "education"),
        ("lai suat ngan hang thang 9", "finance"),
    ],
)
def test_titles_inside_a_tracked_vertical_are_classified(title, expected):
    assert _clusterer()._classify_category([_signal(title)]) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        # Understanding a market means understanding the domains around it, so the taxonomy
        # covers general information verticals too, not only the commercial ones.
        ("truc tiep bong da viet nam thai lan", "sports"),
        ("lich thi dau vong bang cup chau a", "sports"),
        ("thoi su toi nay tin nong trong ngay", "news"),
        ("phim moi ra mat rap thang nay", "entertainment"),
        ("suc khoe tinh than va giac ngu", "health"),
        ("quan an ngon sai gon dang thu", "food"),
        ("du lich da nang tu tuc 3 ngay", "travel"),
        ("gia bat dong san phia nam", "realestate"),
        ("danh gia xe may dien moi", "auto"),
        # Both were unclassified while the scope was narrow; now they have a proper home.
        ("Google Search Trends tem nhan dan do an", "food"),
    ],
)
def test_general_information_verticals_are_tracked_too(title, expected):
    assert _clusterer()._classify_category([_signal(title)]) == expected


@pytest.mark.parametrize(
    "title",
    [
        "khong co gi dac biet o day ca",
        "abcdef ghijkl mnopqr stuvwx",
    ],
)
def test_a_topic_matching_nothing_still_reads_unclassified(title):
    """`unclassified` stays meaningful: it says no vertical claimed the cluster."""
    assert _clusterer()._classify_category([_signal(title)]) == "unclassified"


def test_both_seed_files_describe_the_same_taxonomies():
    """SQLite seeds from 003 and Postgres upgrades through 010; a drift breaks one backend only."""
    base = _taxonomies_from("003_market_lexicons.sql")
    upgrade = _taxonomies_from("010_taxonomy_coverage.sql")
    assert upgrade, "010 must carry the taxonomy rows it upgrades"
    assert base == upgrade, (
        "sql/003 and sql/010 disagree; every keyword must be added to both. Differences: "
        + repr({k: (base.get(k), upgrade.get(k)) for k in set(base) | set(upgrade) if base.get(k) != upgrade.get(k)})
    )


@pytest.mark.asyncio
async def test_an_existing_sqlite_database_picks_up_widened_taxonomies(tmp_path, monkeypatch):
    """Taxonomies are system-seeded and no tool writes them, so a bootstrap may refresh them.

    `INSERT OR IGNORE` keyed on industry_code meant a database created before this expansion
    kept its 44 keywords forever, classifying differently from Postgres. That is the same shape
    as the topic_label column, which CREATE TABLE IF NOT EXISTS also left behind.
    """
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    db = tmp_path / "ignis.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    first = SqliteTrendRepository(db_path=str(db))
    await first._ensure_schema()

    # Roll the file back to the pre-expansion state.
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE industry_taxonomies SET keywords = ? WHERE industry_code = 'tech'",
            ('["ai", "software"]',),
        )

    # A second process opening the same file is what an operator actually does on upgrade.
    second = SqliteTrendRepository(db_path=str(db))
    await second._ensure_schema()

    taxonomies = {t["industry_code"]: t["keywords"] for t in await second.get_industry_taxonomies()}
    assert "chatgpt" in taxonomies["tech"], (
        "A database created before the expansion must pick up the widened keyword set"
    )


@pytest.mark.parametrize("source_category", ["27.6K", "1.2M", "12", "", "   "])
def test_a_connector_cannot_impose_a_meaningless_category(source_category):
    """`_classify_category` trusts connector metadata first; that trust needs a floor.

    Three live clusters were filed under "27.6k", "6.4k" and "28k". The Creative Center parser
    that produced them is fixed at source, but the domain must not depend on every connector,
    including third-party plugins, getting this right.
    """
    signal = _signal("khoa hoc ai cho nguoi moi bat dau")
    signal.metadata = {"category": source_category}

    assert _clusterer()._classify_category([signal]) == "education"


@pytest.mark.parametrize(
    "title",
    [
        # Every one of these was misclassified by a single accent-folded keyword.
        "Ca nhac tru tinh bolero khong quang cao vang bong mot thoi",   # vang != vàng (gold)
        "may bay khong nguoi lai toc do cao nhat hien nay",             # toc: hair vs speed
        "24h leo rank thach dau truc tiep tren kenh",                   # livestream is a format
        "Bo do hot o Dak Lak luc nay dam dong keo den",                 # dam != đầm (dress)
    ],
)
def test_an_accent_folded_short_word_does_not_classify_a_topic(title):
    """`_fold_accents` erases the distinction between different Vietnamese words.

    Taxonomy terms are stored unaccented and both sides are folded before matching, so the
    folded form "vang" covers both the word for gold and the unrelated word for resonant, and
    "toc" covers both hair and speed. A bare short Vietnamese token therefore cannot carry a
    vertical: it filed a bolero playlist under finance and an esports bracket under beauty.
    Compounds are safe, because "gia vang" and "nhuom toc" have no unaccented twin.
    """
    assert _clusterer()._classify_category([_signal(title)]) == "unclassified"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("gia vang hom nay tang manh", "finance"),
        ("nhuom toc tai nha khong can salon", "beauty"),
        ("phoi do di lam mua thu", "fashion"),
    ],
)
def test_compound_terms_still_classify(title, expected):
    """Removing the ambiguous single tokens must not cost the coverage they were added for."""
    assert _clusterer()._classify_category([_signal(title)]) == expected


@pytest.mark.parametrize(
    "title,keyword_note",
    [
        # Every one of these was classified off a single short token, verified on the live corpus.
        ("JISOO - CLICK Official MV", "ai: Vietnamese for who/anyone, also the English acronym"),
        ("co ai o gan day cho minh xin mot vi khach", "ai"),
        ("Zoey Vs Mira Vs Rumi o tap nay", "hoc"),
        ("alcaraz is just a magician blows the set", "fashion"),
        ("tai sao can nha cha me toi de lai rat nho", "son"),
    ],
)
def test_one_short_token_is_not_enough_evidence_for_a_vertical(title, keyword_note):
    """A single unambiguous-looking token still collides with ordinary words.

    Measured on the live corpus: of 342 classified clusters, 239 rested on exactly one keyword,
    and 179 of those on a single token. Sampling them showed the token was usually a collision --
    "ai" alone filed a 278-signal K-pop cluster under tech, because "ai" is Vietnamese for
    who/anyone as well as the English acronym.
    """
    assert _clusterer()._classify_category([_signal(title)]) == "unclassified", keyword_note


@pytest.mark.parametrize(
    "title,expected",
    [
        # A compound cannot collide by accident, so one is enough. All verified on live clusters.
        ("DUNG MUA DIEN THOAI MOI hay mua nhung may nay", "tech"),
        ("Cung try on collection moi tu local brand", "fashion"),
        ("Quan ly don hang cuoi ngay", "ecommerce"),
        ("Livestream ban hang can chu y nhung gi", "ecommerce"),
        ("gia vang hom nay tang manh", "finance"),
        ("phoi do di lam mua thu", "fashion"),
    ],
)
def test_one_compound_keyword_is_enough_evidence(title, expected):
    """60 clusters rested on a single compound and were right; a flat two-hit rule would lose them."""
    assert _clusterer()._classify_category([_signal(title)]) == expected


def test_two_short_tokens_together_do_classify():
    """Corroboration is what a single token lacks, not relevance."""
    assert _clusterer()._classify_category([_signal("khoa hoc ai cho nguoi moi bat dau")]) == "education"
    assert _clusterer()._classify_category([_signal("chatgpt va gpt khac nhau the nao")]) == "tech"


def _cluster(*titles):
    return [_signal(t) for t in titles]


def test_one_hit_in_a_large_mixed_cluster_does_not_decide_its_category():
    """A cluster groups by probe keyword, so a minority signal must not speak for the whole.

    Measured on the live corpus: of the clusters resting on a single hitting signal, every one up
    to five signals was a fair call, while the two larger ones were wrong -- an esports bracket
    filed under fashion off 1 signal in 15, and a divorce post under beauty off 1 in 9.
    """
    clusterer = _clusterer()
    beauty_signal = "nhuom toc tai nha khong can salon"
    filler = [f"khong co gi dac biet o day so {i}" for i in range(14)]

    assert clusterer._classify_category(_cluster(beauty_signal, *filler)) == "unclassified"


def test_one_hit_still_decides_a_small_cluster():
    """At a fifth of the cluster or more the evidence is a fair share, not a stray signal."""
    clusterer = _clusterer()
    beauty_signal = "nhuom toc tai nha khong can salon"

    assert clusterer._classify_category(_cluster(beauty_signal)) == "beauty"
    assert clusterer._classify_category(_cluster(beauty_signal, "chuyen khac han")) == "beauty"
    assert (
        clusterer._classify_category(
            _cluster(beauty_signal, *[f"khong co gi dac biet so {i}" for i in range(4)])
        )
        == "beauty"
    )


def test_many_hits_carry_a_large_cluster():
    """Real coverage of a big cluster is exactly what the share rule is meant to let through."""
    clusterer = _clusterer()
    hits = ["nhuom toc mau khoi", "nhuom toc tai nha", "nhuom toc gia bao nhieu"]
    filler = [f"khong co gi dac biet so {i}" for i in range(9)]

    assert clusterer._classify_category(_cluster(*hits, *filler)) == "beauty"


@pytest.mark.parametrize(
    "title,colliding_keyword",
    [
        ("restream thu thach chinh phuc bo quiz the last of us", "chinh phu"),
        ("anh cho toi hoi cai nay la gi", "o to"),
        ("giai doan nay minh hoi met", "giai dau"),
    ],
)
def test_a_compound_keyword_matches_whole_words_only(title, colliding_keyword):
    """Multi-word keywords were matched as raw substrings, with no word boundary.

    That is the anti-pattern already recorded on 03/09, when "Abundance" was rejected for
    containing "dance". It stayed invisible while six verticals held 44 keywords and became
    severe at 250: "chinh phu" fired 279 times by sitting inside "chinh phuc", "o to" 97 times
    inside words like "cho toi", and "ca si" 117 times inside unrelated syllable runs. A Roblox
    cluster ended up filed under automotive.
    """
    assert _clusterer()._classify_category([_signal(title)]) == "unclassified", colliding_keyword


def test_a_compound_keyword_still_matches_when_it_is_really_there():
    clusterer = _clusterer()
    assert clusterer._classify_category([_signal("chinh phu ban hanh nghi dinh moi")]) == "news"
    assert clusterer._classify_category([_signal("gia o to nhap khau thang nay")]) == "auto"
    assert clusterer._classify_category([_signal("giai dau bong da sinh vien")]) == "sports"


@pytest.mark.parametrize(
    "title,expected",
    [
        # Pairs that differ only by tone. Folding made each pair one string.
        ("Giá vàng hôm nay tăng mạnh", "finance"),
        ("Ca nhạc trữ tình bolero vang bóng một thời", "unclassified"),
        ("Nhuộm tóc tại nhà không cần salon", "beauty"),
        ("Máy bay không người lái tốc độ cao nhất", "unclassified"),
        ("Chính phủ ban hành nghị định mới", "news"),
        ("Thử thách chinh phục bộ quiz the last of us", "unclassified"),
        ("Giá ô tô nhập khẩu tháng này", "auto"),
        ("Anh cho tôi hỏi cái này là gì", "unclassified"),
        ("Giải đấu bóng đá sinh viên", "sports"),
        ("Giai đoạn này mình hơi mệt", "unclassified"),
    ],
)
def test_an_accented_title_is_judged_with_its_accents(title, expected):
    """Vietnamese tones carry the word, so they are compared rather than discarded.

    Folding first and guessing afterwards produced a run of wrong categories, each patched
    separately -- ambiguous terms removed, a corroboration rule, a signal-share rule, word
    boundaries -- before the cause was accepted: stripping tones destroys the word. "vang" is
    both gold and resonant, "toc" both hair and speed, "chinh phu" both the government and a
    prefix of "chinh phuc". Comparing tones to tones is exact and needs no guessing.
    """
    assert _clusterer()._classify_category([_signal(title)]) == expected


def test_a_title_written_without_tones_is_still_matched():
    """Vietnamese is often typed without tones; folding is then the only option available."""
    clusterer = _clusterer()
    assert clusterer._classify_category([_signal("gia vang hom nay tang manh")]) == "finance"
    assert clusterer._classify_category([_signal("khoa hoc ai cho nguoi moi bat dau")]) == "education"


def test_a_term_seeded_without_tones_still_matches_an_accented_title():
    """Third-party lexicons seed unaccented terms, and that must keep working."""
    clusterer = SemanticClusterer()
    clusterer.register_taxonomies([{"industry_code": "education", "keywords": ["khoa hoc", "dao tao"]}])
    assert clusterer._classify_category([_signal("Khóa học đào tạo marketing 2026")]) == "education"
