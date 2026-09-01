import re
import math
from datetime import datetime, timezone
from typing import List, Dict, Set, Optional

from ignis.config import settings
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import QualityScorecard, ConfidenceLevel
from ignis.domain.value_objects import GeoCode, PlatformType


class QualityEvaluator:
    """
    Evaluates dataset quality and integrity across multi-platform signals.
    Weights and confidence thresholds are fully configurable via environment variables.
    """

    # Characters strictly unique to Vietnamese (cannot appear in Portuguese, French, Spanish, etc.)
    VI_EXCLUSIVE_CHARS_PATTERN = re.compile(
        r"[ơớờởỡợưứừửữựđĐắằẳẵặấầẩẫậếềểễệốồổỗộớờởỡợứừửữựỳỹỷỵảẻỉỏủãẽĩõũạẹịọụ]",
        re.IGNORECASE
    )

    # Ambiguous shared Latin diacritics (may appear in Portuguese, Spanish, French, etc.)
    SHARED_LATIN_DIACRITICS = re.compile(r"[ôéèáàâóíúç]", re.IGNORECASE)

    FOREIGN_STOPWORDS = {
        # French
        "formation", "complete", "complète", "avec", "cours", "pour", "dans", "tuto", "debutant", "débutant",
        # Portuguese / Spanish
        "como", "funcionam", "chegou", "novos", "veja", "agentes", "autonomos", "autônomos",
        "para", "com", "por", "sobre", "este", "esta", "todos", "agora", "fazer", "curso",
        "gratis", "completo", "tutorial", "você", "voce", "seus", "suas", "criar", "criando",
        "ferramenta", "passo", "inteligencia", "artificial", "automatizar",
        # Indonesian / Malay
        "cara", "yang", "untuk", "ini", "bisa", "dan", "dari"
    }

    TECH_LOAN_WORDS = {
        "ai", "bot", "chat", "agent", "app", "tool", "n8n", "dify", "make", "rpa",
        "token", "workflow", "api", "prompt", "code", "coding", "software", "tech",
        "saas", "plugin", "gpt", "llm", "claude", "gemini", "tutorial", "guide", "free"
    }

    VI_CORE_WORDS = {
        "va", "cua", "la", "trong", "cho", "voi", "ve", "tu", "dong", "hoa",
        "huong", "dan", "cach", "lam", "chu", "doanh", "nghiep", "ung", "dung",
        "giai", "phap", "phan", "mem", "tri", "tue", "nhan", "tao", "tro", "ly",
        "kiem", "tien", "nguoi", "viet", "nam", "danh", "bai", "hoc", "khoa",
        "thuc", "chien", "tong", "quan", "chi", "tiet", "zalo", "acc", "clone",
        "shop", "gia", "ban", "mua", "setup", "chot", "don", "kho", "hang",
        "sao", "gi", "tai", "bao", "nhieu", "cskh", "dai", "phi", "khong",
        "duoc", "nay", "moi", "tot", "nhat", "hay", "chia", "se", "kinh",
        "nghiem", "tai", "lieu", "phan", "tich", "xay", "dung", "tu", "van",
        "khach", "hang", "dich", "vu", "cong", "nghe", "nen", "tang"
    }

    def __init__(
        self,
        custom_lexicon: Optional[Set[str]] = None,
        custom_stopwords: Optional[Set[str]] = None,
    ):
        self._custom_lexicon: Set[str] = set(custom_lexicon or [])
        self._custom_stopwords: Set[str] = set(custom_stopwords or [])

    def register_terms(self, terms: List[str]) -> None:
        """Dynamically register new domain vocabulary terms in memory."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_lexicon.add(clean)

    def register_foreign_stopwords(self, terms: List[str]) -> None:
        """Dynamically register new foreign stop words into filter."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_stopwords.add(clean)

    GARBAGE_EXCLUSIONS = {
        "#funny", "#hai", "#namthầnkinh", "#giadinh", "#haihuoc", "#troll", "#vlog",
        "nhà thông minh", "sitcom", "tiểu phẩm", "phim ngắn", "nồi đất", "tráng men",
        "cnc machining", "máy cnc", "phay cnc", "tiện cnc", "hàn xì", "đúc kim loại"
    }

    # Reject foreign scripts (Hangul, Kanji/Hanzi, Kana, Thai, Cyrillic, Arabic)
    FOREIGN_SCRIPTS_PATTERN = re.compile(r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff\u0e00-\u0e7f\u0400-\u04ff]")

    def _is_garbage(self, text: str) -> bool:
        if not text:
            return True
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return True
        t_low = text.lower()
        return any(g in t_low for g in self.GARBAGE_EXCLUSIONS)

    def is_vietnamese(
        self,
        text: str,
        extra_terms: Optional[Set[str]] = None,
        extra_stopwords: Optional[Set[str]] = None,
    ) -> bool:
        """
        Multi-layer Vietnamese localization detector:
        1. Instantly rejects foreign non-Latin scripts (Korean, Chinese, Japanese, Thai, Cyrillic).
        2. Instantly rejects comedy/garbage/unrelated industrial outlier terms.
        3. Instantly rejects Romance / Foreign stopwords (static baseline + DB dynamic).
        4. Detects unique Vietnamese characters (đ, ơ, ư, hook/dot tones, accented vowels).
        5. For unaccented text, ignores borrowed tech words (ai, bot, chat, tool, etc.)
           and requires at least 2 genuine Vietnamese core vocabulary words.
        """
        if not text:
            return False

        if self._is_garbage(text):
            return False
        
        text_lower = text.lower()
        words = set(re.findall(r"\b[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]+\b", text_lower))
        
        # Layer 1: Reject explicit foreign stopwords (Static + Dynamic Database)
        all_stopwords = self.FOREIGN_STOPWORDS | self._custom_stopwords | (extra_stopwords or set())
        if any(fw in words for fw in all_stopwords):
            return False

        # Layer 2: Exclusive Vietnamese characters with diacritics
        if self.VI_EXCLUSIVE_CHARS_PATTERN.search(text):
            return True

        # Layer 3: Unaccented text verification
        # Exclude international tech loan words from proof of Vietnamese localization
        pure_words = words - self.TECH_LOAN_WORDS
        active_core = self.VI_CORE_WORDS | self._custom_lexicon | (extra_terms or set())
        vi_core_count = sum(1 for w in pure_words if w in active_core)
        
        # Requires at least 2 genuine core Vietnamese words for unaccented titles
        return vi_core_count >= 2

    def evaluate_quality(
        self,
        signals: List[TrendSignal],
        geo: GeoCode = GeoCode.VN,
        timeframe_days: int = 90,
        extra_lexicon: Optional[Set[str]] = None,
    ) -> QualityScorecard:
        if not signals:
            return QualityScorecard(
                coverage_score=0.0,
                language_precision=0.0,
                data_freshness_score=0.0,
                creator_diversity_score=0.0,
                overall_confidence=0.0,
                confidence_level=ConfidenceLevel.UNRELIABLE,
                flaws_detected=["Dataset is empty (0 signals collected)."],
                strengths_detected=[],
            )

        flaws: List[str] = []
        strengths: List[str] = []

        # 1. Coverage Score (% active platforms)
        platforms_present: Set[str] = {
            s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            for s in signals
        }
        core_platforms = {"google", "youtube"}
        has_core = core_platforms.issubset(platforms_present)
        coverage_score = round((len(platforms_present) / 5.0) * 100.0, 1)
        
        if has_core:
            strengths.append(f"Successfully collected from core pillars ({', '.join(core_platforms)}).")
        else:
            missing_core = core_platforms - platforms_present
            flaws.append(f"Missing core pillars: {', '.join(missing_core)}.")

        # 2. Language Precision & Localization Check
        target_lang_matches = 0
        channels: List[str] = []

        for s in signals:
            title = s.raw_title
            channel = s.metadata.get("channel_title", "")
            if channel:
                channels.append(channel)

            is_loc = self.is_vietnamese(title) if geo == GeoCode.VN else True
            s.metadata["is_localized"] = is_loc
            if is_loc:
                target_lang_matches += 1

        language_precision = round((target_lang_matches / float(len(signals))) * 100.0, 1) if signals else 0.0
        if language_precision >= 70.0:
            strengths.append(f"High language localization ({language_precision}% verified target market language).")
        else:
            flaws.append(f"{round(100.0 - language_precision, 1)}% of signals are non-localized or entertainment outliers ({target_lang_matches}/{len(signals)} verified).")

        # 3. View Outlier Concentration Rule
        content_signals = [
            s for s in signals 
            if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) in ("youtube", "tiktok", "reels")
        ]
        total_views = sum(float(s.metric_value) for s in content_signals if float(s.metric_value) > 0)
        if total_views > 0 and content_signals:
            max_signal = max(content_signals, key=lambda s: float(s.metric_value))
            max_views = float(max_signal.metric_value)
            view_ratio = max_views / total_views
            if view_ratio >= 0.5:
                flaws.append(
                    f"Severe view distribution skew: Single viral video ('{max_signal.raw_title[:45]}...') accounts for {round(view_ratio * 100, 1)}% of all video views ({int(max_views):,} / {int(total_views):,})."
                )




        # 3. Creator Diversity Score
        if channels:
            unique_channels = len(set(channels))
            creator_diversity = round(min(100.0, (unique_channels / float(len(channels))) * 100.0), 1)
            if creator_diversity >= 60.0:
                strengths.append(f"Diverse creator distribution ({unique_channels} independent channels).")
            else:
                flaws.append("Signals concentrated among very few creators (viewpoint bias risk).")
        else:
            creator_diversity = 70.0

        # 4. Data Freshness Score
        now_utc = datetime.now(timezone.utc)
        in_timeframe_count = 0
        for s in signals:
            if s.captured_at:
                days_old = (now_utc - s.captured_at).total_seconds() / 86400.0
                if days_old <= timeframe_days:
                    in_timeframe_count += 1
            else:
                in_timeframe_count += 1

        data_freshness_score = round((in_timeframe_count / float(len(signals))) * 100.0, 1)
        if data_freshness_score >= 80.0:
            strengths.append(f"High data freshness ({data_freshness_score}% matching {timeframe_days}-day window).")
        else:
            flaws.append(f"Low freshness score ({data_freshness_score}%), contains outdated signals.")

        # 5. Overall Confidence Score (Weighted average from configurable settings)
        base_confidence = (
            (coverage_score * settings.SCORECARD_WEIGHT_COVERAGE) +
            (language_precision * settings.SCORECARD_WEIGHT_LANGUAGE) +
            (data_freshness_score * settings.SCORECARD_WEIGHT_FRESHNESS) +
            (creator_diversity * settings.SCORECARD_WEIGHT_DIVERSITY)
        )

        # 6. Strict Localized Sample Size Guardrail & Penalty
        sample_penalty_factor = 1.0
        if target_lang_matches < 15:
            flaws.append(f"Low localized dataset size ({target_lang_matches} verified signals in target language). Confidence score penalized.")
            sample_penalty_factor = max(0.5, target_lang_matches / 15.0)
        else:
            strengths.append(f"Sufficient localized dataset size ({target_lang_matches} verified signals).")

        overall_confidence = round(base_confidence * sample_penalty_factor, 1)

        if overall_confidence >= settings.CONFIDENCE_HIGH_THRESHOLD and target_lang_matches >= 15:
            confidence_level = ConfidenceLevel.HIGH
        elif overall_confidence >= settings.CONFIDENCE_MEDIUM_THRESHOLD:
            confidence_level = ConfidenceLevel.MEDIUM
        elif overall_confidence >= settings.CONFIDENCE_LOW_THRESHOLD:
            confidence_level = ConfidenceLevel.LOW
        else:
            confidence_level = ConfidenceLevel.UNRELIABLE


        return QualityScorecard(
            coverage_score=coverage_score,
            language_precision=language_precision,
            data_freshness_score=data_freshness_score,
            creator_diversity_score=creator_diversity,
            overall_confidence=overall_confidence,
            confidence_level=confidence_level,
            flaws_detected=flaws,
            strengths_detected=strengths,
        )
