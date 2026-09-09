from datetime import datetime, timezone, timedelta
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator


# The detector's phrase lists live in market_lexicons, so a bare instance rejects nothing on
# language grounds. Production registers them at bootstrap; these tests do the same. Whether the
# seed actually carries them is covered by test_vocabulary_loader.
FOREIGN_PHRASES = [
    "formation complete", "formation complète", "avec", "cours pour", "dans le",
    "tuto debutant", "tuto débutant", "como criar", "como funcionam",
    "agentes autonomos", "agentes autônomos", "para você", "para voce",
    "inteligencia artificial", "inteligência artificial", "todos os", "fazer curso",
    "de ia", "com ia", "para empresas", "cara membuat", "untuk pemula",
]

PORTUGUESE_WORDS = [
    "como", "para", "com", "por", "sobre", "este", "esta", "todos", "agora", "fazer",
    "curso", "gratis", "completo", "você", "voce", "seus", "suas", "criar", "criando",
    "ferramenta", "passo", "inteligencia", "artificial", "inteligência", "automatizar",
    "não", "nao", "em", "do", "da", "que", "uma", "um", "automação", "automacao",
    "negócios", "negocios", "agentes",
]


def _armed_detector() -> HeuristicLanguageDetector:
    detector = HeuristicLanguageDetector()
    detector.register_foreign_phrases(FOREIGN_PHRASES)
    detector.register_portuguese_words(PORTUGUESE_WORDS)
    return detector


def test_language_detector_two_column_matrix_guardrails():
    detector = _armed_detector()

    # ---------------------------------------------------------
    # 1. United States (geo=US / GLOBAL) — Real-world tech titles & brand names
    # ---------------------------------------------------------
    us_accepted = [
        "Building Autonomous AI Agents with LangChain",
        "How to setup n8n workflow for beginners",
        "Top 10 SaaS market trends in 2026",
        "AI Agent tutorial and full guide",
        "Complete enterprise automation strategy",
        # Real-world YouTube/TikTok tech brand titles (formerly false-negatives)
        "n8n Zapier Make Comparison",
        "SEO Backlinks Ahrefs Semrush",
        "Shopify Dropshipping 2026",
        "Figma to Webflow handoff",
        "Kubernetes Helm Terraform DevOps",
        "ChatGPT Automation Masterclass",
    ]
    us_rejected = [
        "Hướng dẫn cài đặt n8n cho người mới",           # Vietnamese
        "Como criar agentes de IA autônomos",            # Portuguese
        "Formation complète n8n pour débutant",          # French
        "如何在2026年构建人工智能代理",                    # Chinese
        "챗GPT AI 에이전트 활용법",                         # Korean
        "การสร้าง AI Agent สำหรับธุรกิจ",                   # Thai
        "asdfgh qwerty zxcvbn",                          # Pure consonant gibberish
        "!!! 12345 !!!",                                 # Pure punctuation / numbers
        "1234567890",                                    # Numbers only
    ]
    for text in us_accepted:
        assert detector.is_localized(text, geo=GeoCode.US), f"US falsely rejected: '{text}'"
    for text in us_rejected:
        assert not detector.is_localized(text, geo=GeoCode.US), f"US falsely accepted: '{text}'"

    # ---------------------------------------------------------
    # 2. Japan (geo=JP) — Must distinguish Japanese from Chinese
    # ---------------------------------------------------------
    jp_accepted = [
        "AIエージェントの業務自動化ガイド",
        "初心者向けn8n自動化チュートリアル",
        "2026年のAI市場トレンド解説",
    ]
    jp_rejected = [
        "如何在2026年构建人工智能代理",                    # Chinese CJK only (0 Kana)
        "Building Autonomous AI Agents",                 # English
        "Hướng dẫn cài đặt AI Agent",                    # Vietnamese
    ]
    for text in jp_accepted:
        assert detector.is_localized(text, geo=GeoCode.JP), f"JP falsely rejected: '{text}'"
    for text in jp_rejected:
        assert not detector.is_localized(text, geo=GeoCode.JP), f"JP falsely accepted: '{text}'"

    # ---------------------------------------------------------
    # 3. Brazil (geo=BR) — Must reject Vietnamese false positives
    # ---------------------------------------------------------
    br_accepted = [
        "Como criar agentes autônomos com inteligência artificial",
        "Curso de automação para empresas",
        "Ferramenta gratuita para criar agentes de IA",
    ]
    br_rejected = [
        "Trí tuệ nhân tạo cho doanh nghiệp",             # Vietnamese diacritics
        "Building Autonomous AI Agents",                 # English
        "챗GPT AI 에이전트 활용법",                         # Korean
    ]
    for text in br_accepted:
        assert detector.is_localized(text, geo=GeoCode.BR), f"BR falsely rejected: '{text}'"
    for text in br_rejected:
        assert not detector.is_localized(text, geo=GeoCode.BR), f"BR falsely accepted: '{text}'"

    # ---------------------------------------------------------
    # 4. Vietnam (geo=VN) — Must accept tech loan mixing
    # ---------------------------------------------------------
    vn_accepted = [
        "Khoá học n8n complete cho người mới",
        "Hướng dẫn setup AI Agent từ A đến Z",
        "Cài đặt bot chat cskh tự động hoá",
        "hoc lam ai agent tu dong hoa",
    ]
    vn_rejected = [
        "Como criar agentes autônomos grátis",           # Portuguese
        "Formation complete intelligence artificielle",   # French
        "챗GPT AI 에이전트 활용법",                         # Korean
        "如何在2026年构建人工智能代理",                    # Chinese
    ]
    for text in vn_accepted:
        assert detector.is_localized(text, geo=GeoCode.VN), f"VN falsely rejected: '{text}'"
    for text in vn_rejected:
        assert not detector.is_localized(text, geo=GeoCode.VN), f"VN falsely accepted: '{text}'"


def test_extra_terms_whitelist_does_not_open_backdoor():
    detector = _armed_detector()
    common_term = {"ai"}

    # Common extra_terms must NOT bypass garbage or foreign scripts
    assert not detector.is_localized("!!! 12345 ai !!!", geo=GeoCode.US, extra_terms=common_term)
    assert not detector.is_localized("asdfgh ai zxcvbn", geo=GeoCode.US, extra_terms=common_term)
    assert not detector.is_localized("Como criar agentes de ai", geo=GeoCode.US, extra_terms=common_term)
    assert not detector.is_localized("如何在2026年构建ai代理", geo=GeoCode.JP, extra_terms=common_term)

    # Valid domain term in target market
    assert detector.is_localized("DeepSeek R1 architecture", geo=GeoCode.US, extra_terms={"deepseek r1"})
    assert detector.is_localized("Solução inovadora de finanças", geo=GeoCode.BR, extra_terms={"finanças"})


def test_noise_blacklist_rejection_across_regions():
    detector = _armed_detector()
    noise = {"troll", "#funny", "hai kich"}

    assert not detector.is_localized("Video troll ban than cực mạnh", geo=GeoCode.VN, extra_noise=noise)
    assert not detector.is_localized("Funny prank troll compilation", geo=GeoCode.US, extra_noise=noise)
    assert detector.is_localized("Enterprise AI agent workflow", geo=GeoCode.US, extra_noise=noise)


def test_view_skew_outlier_not_firing_on_single_video():
    evaluator = QualityEvaluator()
    single_video = [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Hướng dẫn làm AI Agent",
            metric_value=100000.0,
            geo_code=GeoCode.VN,
            metadata={"channel_title": "AI Master"}
        )
    ]
    scorecard = evaluator.evaluate_quality(single_video, geo=GeoCode.VN)
    # n=1 should not trigger "Severe view distribution skew"
    assert not any("Severe view distribution skew" in f for f in scorecard.flaws_detected)


def test_data_freshness_evaluation_with_published_at():
    evaluator = QualityEvaluator()
    now_utc = datetime.now(timezone.utc)
    old_date = (now_utc - timedelta(days=60)).isoformat()
    fresh_date = (now_utc - timedelta(days=5)).isoformat()

    signals = [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Video cũ hơn 30 ngày",
            metric_value=5000.0,
            geo_code=GeoCode.VN,
            metadata={"published_at": old_date}
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Video mới xuất bản 5 ngày",
            metric_value=8000.0,
            geo_code=GeoCode.VN,
            metadata={"published_at": fresh_date}
        ),
    ]

    # In a 30-day window, 1 of 2 is fresh -> 50%
    scorecard_30d = evaluator.evaluate_quality(signals, geo=GeoCode.VN, timeframe_days=30)
    assert scorecard_30d.data_freshness_score == 50.0

    # In a 90-day window, both are fresh -> 100%
    scorecard_90d = evaluator.evaluate_quality(signals, geo=GeoCode.VN, timeframe_days=90)
    assert scorecard_90d.data_freshness_score == 100.0


def test_a_detector_without_its_vocabulary_reads_portuguese_as_english():
    """Documents the permissive direction of failure, and that it is the registration that fixes it.

    Both lists drive rejection rules, so an empty one lets foreign text through rather than
    blocking real text. Failing closed here would empty the corpus instead, which is why the
    detector logs once and keeps going.
    """
    bare = HeuristicLanguageDetector()
    portuguese = "Como criar agentes autonomos para empresas"

    assert bare.is_localized(portuguese, geo=GeoCode.US) is True
    assert _armed_detector().is_localized(portuguese, geo=GeoCode.US) is False
