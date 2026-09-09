"""Ingress rejects a script the region does not use, and judges nothing else.

Relevance belongs downstream. `QualityEvaluator` already holds the domain vocabulary, the
foreign stopwords and the noise blacklist, and it runs on the analysis path. Judging relevance
again at ingress meant the radar could only ever store topics somebody had already seeded into
`market_lexicons`, which is the opposite of what a trend radar is for. Measured on the live
corpus, the vocabulary-driven gate rejected 67.8% of rows -- including "Khoa hoc AI cho nguoi
moi bat dau", a Vietnamese title squarely on target.

What survives at ingress is the one judgement that is about the data being wrong rather than
uninteresting: a Korean or Cyrillic title in a Vietnam pass.
"""

import pytest

from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector


@pytest.fixture
def detector():
    return HeuristicLanguageDetector()


@pytest.mark.parametrize(
    "title",
    [
        "Khoa hoc AI cho nguoi moi bat dau",
        "Khóa học AI cho người mới bắt đầu",
        "KHÓC THẦM - Thúy Phương Bolero (Official MV 4K)",
        "n8n vs Zapier vs Make Comparison 2026",
        "Best AI Agent Frameworks for E-commerce",
    ],
)
def test_latin_script_titles_reach_the_corpus_in_a_vn_pass(detector, title):
    """On-topic, off-topic and English alike: ingress is not where that gets decided."""
    assert detector.uses_regional_script(title, geo=GeoCode.VN)


@pytest.mark.parametrize(
    "title",
    [
        "Чи впливала погода на колір волосся?",
        "غيرو لون شعره واصبح لا يصدق",
        "워터밤 안가도 흠뻑 젖는 한강런",
        "看著鏡子裡的自己每一天都在變好",
        "สุดหัวใข่นิเดรร เทรนด์วันนี้",
        "エルバフ編 最新情報を発表",
    ],
)
def test_a_script_vietnam_does_not_use_is_rejected(detector, title):
    assert not detector.uses_regional_script(title, geo=GeoCode.VN)


def test_a_region_keeps_its_own_script():
    """The gate is per-region: Hangul is wrong for VN and right for KR."""
    detector = HeuristicLanguageDetector()
    assert detector.uses_regional_script("워터밤 안가도 흠뻑 젖는 한강런", geo=GeoCode.KR)
    assert detector.uses_regional_script("エルバフ編 最新情報を発表", geo=GeoCode.JP)
    assert detector.uses_regional_script("เทรนด์วันนี้ หาดใหญ่สงขลา", geo=GeoCode.TH)
    assert not detector.uses_regional_script("워터밤 안가도 흠뻑 젖는", geo=GeoCode.JP)


def test_a_stray_foreign_character_does_not_condemn_a_local_title(detector):
    """Vietnamese posts quote a brand or a name in another script without changing language."""
    assert detector.uses_regional_script("Review son môi 3CE 韓 chinh hang", geo=GeoCode.VN)


def test_global_and_unknown_regions_accept_everything(detector):
    assert detector.uses_regional_script("看著鏡子裡的自己", geo=GeoCode.GLOBAL)


def test_text_with_no_letters_is_rejected(detector):
    assert not detector.uses_regional_script("###  !!! 123 ---", geo=GeoCode.VN)
    assert not detector.uses_regional_script("", geo=GeoCode.VN)


@pytest.mark.parametrize(
    "title",
    [
        "नमस्ते यह एक परीक्षण है",          # Devanagari
        "ສະບາຍດີ ນີ້ແມ່ນການທົດສອບ",              # Lao
        "မင်္ဂလာပါ ဒါက စမ်းသပ်မှုပါ",            # Myanmar
    ],
)
def test_scripts_the_older_pattern_missed_are_still_rejected(detector, title):
    """Devanagari, Lao and Myanmar rows did reach the stored corpus and had to be deleted."""
    assert not detector.uses_regional_script(title, geo=GeoCode.VN)


@pytest.mark.asyncio
async def test_an_agent_probe_fetches_foreign_language_content_freely():
    """The script gate belongs to the unattended radar, not to a probe an agent asked for.

    Track 1 accumulates a corpus nobody is watching, so a Korean title in a Vietnam pass is
    noise it would carry forever. Track 2 runs because an agent asked a specific question, and
    the answer may well be in another language: Vietnamese social content mixes English
    constantly, and a market question can legitimately reach Korean or Chinese sources.

    `search_across_all` therefore applies only the self-content scope guard. This test exists so
    that stays deliberate rather than becoming an oversight someone later "fixes".
    """
    from unittest.mock import AsyncMock

    from ignis.application.ports.connector_port import IConnectorPlugin
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType, Timeframe
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

    class MultilingualPlugin(IConnectorPlugin):
        @property
        def platform(self):
            return PlatformType.YOUTUBE

        @property
        def name(self):
            return "Multilingual Probe"

        async def is_healthy(self):
            return True

        async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=None):
            return []

        async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
            return [
                TrendSignal(
                    platform=self.platform,
                    raw_title=title,
                    metric_value=100.0,
                    geo_code=GeoCode.VN,
                    source_url=f"https://example.test/{i}",
                    metadata={"keyword": keywords[0] if keywords else None},
                )
                for i, title in enumerate(
                    [
                        "Best AI agent frameworks for e-commerce",   # English, always fine
                        "K-beauty 스킨케어 루틴 추천",                   # Korean
                        "跨境电商 选品 技巧",                            # Chinese
                    ]
                )
            ]

    repo = AsyncMock()
    repo.log_event = AsyncMock()
    repo.get_self_accounts = AsyncMock(return_value=[])
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(MultilingualPlugin())

    signals = await registry.search_across_all(keywords=["skincare"], geo=GeoCode.VN)

    assert len(signals) == 3, (
        "An agent probe must return what it found, whatever language it is in: "
        f"{[s.raw_title for s in signals]}"
    )


@pytest.mark.asyncio
async def test_an_explicitly_requested_pass_is_not_script_gated():
    """The gate keys on who asked for the pass, not on which code path served it.

    `trigger_ingress_refresh` runs `fetch_from_all`, the same function the unattended worker
    uses, but somebody typed it. An explicit request is the operator asking a question, and the
    answer may legitimately be in another language -- the same reasoning that leaves agent probes
    ungated. Only a scheduled sweep, whose corpus nobody is watching, is filtered.
    """
    from unittest.mock import AsyncMock

    from ignis.application.ports.connector_port import IConnectorPlugin
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import IngressScope, IngressTrigger, PlatformType, Timeframe
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

    class MixedLanguageFeed(IConnectorPlugin):
        @property
        def platform(self):
            return PlatformType.GOOGLE_TRENDS

        @property
        def name(self):
            return "Mixed Language Feed"

        async def is_healthy(self):
            return True

        async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=None):
            return [
                TrendSignal(
                    platform=self.platform,
                    raw_title=title,
                    metric_value=100.0,
                    geo_code=GeoCode.VN,
                    source_url=f"https://example.test/{i}",
                )
                for i, title in enumerate(["giá vàng hôm nay", "K-beauty 스킨케어 루틴"])
            ]

    def _registry():
        repo = AsyncMock()
        repo.log_event = AsyncMock()
        repo.get_self_accounts = AsyncMock(return_value=[])
        registry = ConnectorPluginRegistry(repository=repo)
        registry.register(MixedLanguageFeed())
        return registry

    scheduled = await _registry().fetch_from_all(
        geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET
    )
    assert [s.raw_title for s in scheduled] == ["giá vàng hôm nay"], (
        "An unattended sweep still drops a script the region does not use"
    )

    requested = await _registry().fetch_from_all(
        geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET, trigger=IngressTrigger.REQUESTED
    )
    assert len(requested) == 2, (
        f"An explicitly requested pass keeps what it found: {[s.raw_title for s in requested]}"
    )
