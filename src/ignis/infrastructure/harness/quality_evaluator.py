import re
import math
from datetime import datetime, timezone
from typing import List, Dict, Set, Optional

from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import QualityScorecard, ConfidenceLevel
from ignis.domain.value_objects import GeoCode, PlatformType


class QualityEvaluator:
    """
    Evaluates dataset quality and integrity across multi-platform signals.
    Provides transparent scorecards (Coverage, Language Precision, Freshness, Creator Diversity).
    """

    VIETNAMESE_CHARS_PATTERN = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]",
        re.IGNORECASE
    )

    VI_COMMON_WORDS = {
        "va", "cua", "la", "trong", "cho", "voi", "ve", "tu", "dong", "hoa",
        "huong", "dan", "cach", "lam", "chu", "doanh", "nghiep", "ung", "dung",
        "giai", "phap", "phan", "mem", "tri", "tue", "nhan", "tao", "tro", "ly",
        "kiem", "tien", "nguoi", "viet", "viet", "nam", "danh", "cho", "bai",
        "hoc", "khoa", "hoc", "thuc", "chien", "tong", "quan", "chi", "tiet"
    }

    def is_vietnamese(self, text: str) -> bool:
        """Strictly detect if text contains Vietnamese diacritics or core vocabulary."""
        if not text:
            return False
        
        if self.VIETNAMESE_CHARS_PATTERN.search(text):
            return True

        words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
        vi_word_count = sum(1 for w in words if w in self.VI_COMMON_WORDS)
        if vi_word_count >= 2:
            return True

        return False

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
        coverage_score = (len(platforms_present) / 5.0) * 100.0
        
        if has_core:
            strengths.append(f"Collected from core pillars ({', '.join(core_platforms)}).")
        else:
            missing_core = core_platforms - platforms_present
            flaws.append(f"Missing core platforms: {', '.join(missing_core)}.")

        # 2. Language Precision (% matching target geo language)
        target_lang_matches = 0
        channels: List[str] = []

        for s in signals:
            title = s.raw_title
            channel = s.metadata.get("channel_title", "")
            if channel:
                channels.append(channel)

            if geo == GeoCode.VN:
                if s.platform == PlatformType.GOOGLE_TRENDS:
                    target_lang_matches += 1
                elif self.is_vietnamese(title) or self.is_vietnamese(channel):
                    target_lang_matches += 1
            else:
                target_lang_matches += 1

        language_precision = round((target_lang_matches / float(len(signals))) * 100.0, 1)
        if language_precision >= 70.0:
            strengths.append(f"High language localization ({language_precision}% verified target language).")
        else:
            flaws.append(f"{round(100.0 - language_precision, 1)}% of signals are in foreign/non-localized languages.")

        # 3. Creator Diversity Score
        if channels:
            unique_channels = len(set(channels))
            creator_diversity = round(min(100.0, (unique_channels / float(len(channels))) * 100.0), 1)
            if creator_diversity >= 60.0:
                strengths.append(f"Diverse creator sources ({unique_channels} independent channels).")
            else:
                flaws.append("Signals concentrated among few creators (risk of viewpoint bias).")
        else:
            creator_diversity = 70.0

        # 4. Data Freshness Score
        now_utc = datetime.now(timezone.utc)
        freshness_samples = []
        for s in signals:
            if s.captured_at:
                days_old = (now_utc - s.captured_at).total_seconds() / 86400.0
                if days_old <= timeframe_days:
                    score = 100.0 - ((days_old / max(1.0, float(timeframe_days))) * 25.0)
                else:
                    score = max(0.0, 75.0 - ((days_old - timeframe_days) * 2.0))
                freshness_samples.append(score)
            else:
                freshness_samples.append(85.0)

        data_freshness_score = round(sum(freshness_samples) / float(len(freshness_samples)), 1)
        if data_freshness_score >= 80.0:
            strengths.append(f"High freshness ({data_freshness_score}% matching {timeframe_days}-day window).")
        else:
            flaws.append(f"Low freshness score ({data_freshness_score}%), contains outdated signals.")

        # 5. Overall Confidence Score
        overall_confidence = round(
            (coverage_score * 0.25) +
            (language_precision * 0.25) +
            (data_freshness_score * 0.30) +
            (creator_diversity * 0.20),
            1
        )

        if overall_confidence >= 80.0:
            confidence_level = ConfidenceLevel.HIGH
        elif overall_confidence >= 60.0:
            confidence_level = ConfidenceLevel.MEDIUM
        elif overall_confidence >= 40.0:
            confidence_level = ConfidenceLevel.LOW
        else:
            confidence_level = ConfidenceLevel.UNRELIABLE

        return QualityScorecard(
            coverage_score=round(coverage_score, 1),
            language_precision=language_precision,
            data_freshness_score=data_freshness_score,
            creator_diversity_score=creator_diversity,
            overall_confidence=overall_confidence,
            confidence_level=confidence_level,
            flaws_detected=flaws,
            strengths_detected=strengths,
        )
