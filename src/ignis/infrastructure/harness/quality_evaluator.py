import re
from datetime import datetime, timezone
from typing import List, Dict, Set, Optional
from uuid import UUID

from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import QualityScorecard, ConfidenceLevel
from ignis.domain.value_objects import GeoCode, PlatformType


class QualityEvaluator:
    """
    Module đánh giá chất lượng và độ tin cậy của tập dữ liệu tín hiệu thu thập được.
    Đảm bảo Agent có scorecard minh bạch trước khi đưa ra kết luận kinh doanh.
    """

    VIETNAMESE_CHARS_PATTERN = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE)

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
                flaws_detected=["Tập dữ liệu rỗng (0 signals thu thập được)."],
                strengths_detected=[],
            )

        flaws: List[str] = []
        strengths: List[str] = []

        # 1. Coverage Score (% nền tảng có tín hiệu)
        platforms_present: Set[str] = {
            s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            for s in signals
        }
        core_platforms = {"google", "youtube"}
        has_core = core_platforms.issubset(platforms_present)
        coverage_score = (len(platforms_present) / 5.0) * 100.0
        
        if has_core:
            strengths.append(f"Thu thập đầy đủ 2 kênh trụ cột ({', '.join(core_platforms)}).")
        else:
            missing_core = core_platforms - platforms_present
            flaws.append(f"Thiếu kênh trụ cột: {', '.join(missing_core)}.")

        # 2. Language Precision (% khớp ngôn ngữ thị trường)
        target_lang_matches = 0
        channels: List[str] = []

        for s in signals:
            title = s.raw_title
            channel = s.metadata.get("channel_title", "")
            if channel:
                channels.append(channel)

            if geo == GeoCode.VN:
                if self.VIETNAMESE_CHARS_PATTERN.search(title) or "là gì" in title.lower() or "hướng dẫn" in title.lower():
                    target_lang_matches += 1
                elif s.platform == PlatformType.GOOGLE_TRENDS:
                    target_lang_matches += 1
            else:
                target_lang_matches += 1

        language_precision = (target_lang_matches / float(len(signals))) * 100.0
        if language_precision >= 75.0:
            strengths.append(f"Độ chính xác ngôn ngữ cao ({language_precision:.1f}% khớp thị trường {geo.value}).")
        else:
            flaws.append(f"Có {(100.0 - language_precision):.1f}% tín hiệu là ngoại ngữ (chưa hoàn toàn bản địa hóa).")

        # 3. Creator Diversity Score
        if channels:
            unique_channels = len(set(channels))
            creator_diversity = min(100.0, (unique_channels / float(len(channels))) * 100.0)
            if creator_diversity >= 60.0:
                strengths.append(f"Nguồn phát tán đa dạng ({unique_channels} kênh độc lập).")
            else:
                flaws.append("Tập trung vào một số ít kênh (dễ bị thiên lệch quan điểm).")
        else:
            creator_diversity = 70.0

        # 4. Data Freshness Score (Tính tương thích với timeframe yêu cầu)
        now_utc = datetime.now(timezone.utc)
        freshness_samples = []
        for s in signals:
            if s.captured_at:
                days_old = (now_utc - s.captured_at).total_seconds() / 86400.0
                if days_old <= timeframe_days:
                    # Trong khoảng timeframe: điểm từ 70 -> 100
                    score = 100.0 - ((days_old / max(1.0, float(timeframe_days))) * 30.0)
                else:
                    # Quá hạn timeframe: giảm dần
                    excess_days = days_old - timeframe_days
                    score = max(10.0, 70.0 - (excess_days * 0.5))
                freshness_samples.append(score)
        
        data_freshness = sum(freshness_samples) / len(freshness_samples) if freshness_samples else 85.0

        # 5. Overall Confidence Score (Weighted Average)
        overall_confidence = (
            coverage_score * 0.25 +
            language_precision * 0.35 +
            creator_diversity * 0.20 +
            data_freshness * 0.20
        )
        overall_confidence = round(min(100.0, max(0.0, overall_confidence)), 1)

        if overall_confidence >= 80.0:
            conf_level = ConfidenceLevel.HIGH
        elif overall_confidence >= 60.0:
            conf_level = ConfidenceLevel.MEDIUM
        elif overall_confidence >= 40.0:
            conf_level = ConfidenceLevel.LOW
        else:
            conf_level = ConfidenceLevel.UNRELIABLE

        return QualityScorecard(
            coverage_score=round(coverage_score, 1),
            language_precision=round(language_precision, 1),
            data_freshness_score=round(data_freshness, 1),
            creator_diversity_score=round(creator_diversity, 1),
            overall_confidence=overall_confidence,
            confidence_level=conf_level,
            flaws_detected=flaws,
            strengths_detected=strengths,
        )
