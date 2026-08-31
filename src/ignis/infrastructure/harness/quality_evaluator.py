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

    # Từ vựng tiếng Pháp dễ gây nhầm lẫn do có chung ký tự dấu
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
        
        # Nếu có từ tiếng Pháp rõ ràng -> loại trừ
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
            strengths.append(f"Thu thập đầy đủ 2 kênh trụ cột ({', '.join(core_platforms)}).")
        else:
            missing_core = core_platforms - platforms_present
            flaws.append(f"Thiếu kênh trụ cột: {', '.join(missing_core)}.")

        # 2. Language Precision (Đo chính xác trên tập tín hiệu nội dung thực tế, không cộng Google Trends vào tử số)
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
            strengths.append(f"Độ chính xác bản địa hóa cao ({language_precision}% nội dung tiếng Việt).")
        else:
            flaws.append(f"Có {round(100.0 - language_precision, 1)}% tín hiệu nội dung là ngoại ngữ (chưa hoàn toàn bản địa hóa).")

        # 3. Creator Diversity Score (Tỉ lệ kênh độc lập)
        if channels:
            unique_channels = len(set(channels))
            creator_diversity = round(min(100.0, (unique_channels / float(len(channels))) * 100.0), 1)
            if creator_diversity >= 60.0:
                strengths.append(f"Nguồn phát tán đa dạng ({unique_channels} kênh độc lập).")
            else:
                flaws.append("Tập trung vào một số ít kênh (dễ bị thiên lệch quan điểm).")
        else:
            creator_diversity = 70.0

        # 4. Data Freshness Score (% tín hiệu nằm trong khung thời gian timeframe)
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
            strengths.append(f"Dữ liệu tươi mới ({data_freshness_score}% khớp timeframe {timeframe_days} ngày).")
        else:
            flaws.append(f"Độ tươi mới thấp ({data_freshness_score}%), có tín hiệu quá hạn.")

        # 5. Overall Confidence Score (Bình quân trọng số 4 trục)
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
            coverage_score=coverage_score,
            language_precision=language_precision,
            data_freshness_score=data_freshness_score,
            creator_diversity_score=creator_diversity,
            overall_confidence=overall_confidence,
            confidence_level=confidence_level,
            flaws_detected=flaws,
            strengths_detected=strengths,
        )
