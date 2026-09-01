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

    VIETNAMESE_CHARS_PATTERN = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]",
        re.IGNORECASE
    )

    FRENCH_WORDS = {"formation", "complete", "complète", "avec", "cours", "pour", "dans", "tuto", "debutant", "débutant"}

    VI_COMMON_WORDS = {
        "va", "cua", "la", "trong", "cho", "voi", "ve", "tu", "dong", "hoa",
        "huong", "dan", "cach", "lam", "chu", "doanh", "nghiep", "ung", "dung",
        "giai", "phap", "phan", "mem", "tri", "tue", "nhan", "tao", "tro", "ly",
        "kiem", "tien", "nguoi", "viet", "nam", "danh", "bai", "hoc", "khoa",
        "thuc", "chien", "tong", "quan", "chi", "tiet"
    }

    def is_vietnamese(self, text: str) -> bool:
        """Strictly detect if text contains Vietnamese diacritics without French false positives."""
        if not text:
            return False
        
        text_lower = text.lower()
        words = set(re.findall(r"\b[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]+\b", text_lower))
        
        if any(fw in words for fw in self.FRENCH_WORDS):
            return False

        if self.VIETNAMESE_CHARS_PATTERN.search(text):
            return True

        vi_word_count = sum(1 for w in words if w in self.VI_COMMON_WORDS)
        return vi_word_count >= 2

    def evaluate_quality(
        self,
        signals: List[TrendSignal],
        geo: GeoCode = GeoCode.VN,
        timeframe_days: int = 90,
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

        # 2. Language Precision (evaluated on content signals)
        content_signals = [s for s in signals if s.platform != PlatformType.GOOGLE_TRENDS]
        eval_signals = content_signals if content_signals else signals

        target_lang_matches = 0
        channels: List[str] = []

        for s in eval_signals:
            title = s.raw_title
            channel = s.metadata.get("channel_title", "")
            if channel:
                channels.append(channel)

            if geo == GeoCode.VN:
                if self.is_vietnamese(title) or (channel and self.is_vietnamese(channel)):
                    target_lang_matches += 1
            else:
                target_lang_matches += 1

        language_precision = round((target_lang_matches / float(len(eval_signals))) * 100.0, 1)
        if language_precision >= 70.0:
            strengths.append(f"High language localization ({language_precision}% verified target market language).")
        else:
            flaws.append(f"{round(100.0 - language_precision, 1)}% of content signals are non-localized / foreign language.")

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

        # 6. Sample Size Guardrail & Penalty
        total_signals_count = len(signals)
        sample_penalty_factor = 1.0
        if total_signals_count < 10:
            flaws.append(f"Sample size below recommended production threshold ({total_signals_count} signals).")
            sample_penalty_factor = max(0.8, total_signals_count / 10.0)
        else:
            strengths.append(f"Sufficient dataset size ({total_signals_count} verified signals).")

        overall_confidence = round(base_confidence * sample_penalty_factor, 1)

        if overall_confidence >= settings.CONFIDENCE_HIGH_THRESHOLD:
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
