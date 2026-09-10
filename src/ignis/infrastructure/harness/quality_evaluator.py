from datetime import datetime, timezone
from typing import List, Optional, Set

from ignis.application.ports.language_detector_port import ILanguageDetector
from ignis.config import settings
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import ConfidenceLevel, QualityScorecard
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector


class QualityEvaluator:
    """
    Evaluates dataset quality and integrity across multi-platform signals.
    Weights and confidence thresholds are fully configurable via environment variables.
    """

    def __init__(
        self,
        custom_lexicon: Optional[Set[str]] = None,
        custom_stopwords: Optional[Set[str]] = None,
        custom_noise: Optional[Set[str]] = None,
        detector: Optional[ILanguageDetector] = None,
    ):
        self._custom_lexicon: Set[str] = set(custom_lexicon or [])
        self._custom_stopwords: Set[str] = set(custom_stopwords or [])
        self._custom_noise: Set[str] = set(custom_noise or [])
        self._detector: ILanguageDetector = detector or HeuristicLanguageDetector()

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

    def register_noise_blacklist(self, terms: List[str]) -> None:
        """Dynamically register mission-specific negative/noise terms."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_noise.add(clean)

    def is_vietnamese(
        self,
        text: str,
        extra_terms: Optional[Set[str]] = None,
        extra_stopwords: Optional[Set[str]] = None,
        extra_noise: Optional[Set[str]] = None,
    ) -> bool:
        """Evaluate Vietnamese linguistic authenticity."""
        merged_terms = self._custom_lexicon | (extra_terms or set())
        merged_stopwords = self._custom_stopwords | (extra_stopwords or set())
        merged_noise = self._custom_noise | (extra_noise or set())
        return self._detector.is_localized(
            text=text,
            geo=GeoCode.VN,
            extra_terms=merged_terms,
            extra_stopwords=merged_stopwords,
            extra_noise=merged_noise,
        )

    def is_localized(self, title: str, geo: GeoCode = GeoCode.VN) -> bool:
        """Universal language & localization verification across geographies."""
        return self._detector.is_localized(
            text=title,
            geo=geo,
            extra_terms=self._custom_lexicon,
            extra_stopwords=self._custom_stopwords,
            extra_noise=self._custom_noise,
        )

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

        # 1. Coverage Score (% active platforms capped at 100.0)
        platforms_present: Set[str] = {
            s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            for s in signals
        }
        core_platforms = {"google", "youtube"}
        has_core = core_platforms.issubset(platforms_present)
        coverage_score = round(min(100.0, (len(platforms_present) / 5.0) * 100.0), 1)

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
            channel = (s.metadata or {}).get("channel_title", "")
            if channel:
                channels.append(channel)

            is_loc = self.is_localized(title, geo=geo)
            if s.metadata is None:
                s.metadata = {}
            else:
                s.metadata = dict(s.metadata)
            s.metadata["is_localized"] = is_loc
            if is_loc:
                target_lang_matches += 1

        language_precision = round((target_lang_matches / float(len(signals))) * 100.0, 1) if signals else 0.0
        if language_precision >= 70.0:
            strengths.append(f"High language localization ({language_precision}% verified target market language).")
        else:
            flaws.append(
                f"{round(100.0 - language_precision, 1)}% of signals are non-localized or entertainment outliers ({target_lang_matches}/{len(signals)} verified)."
            )

        # 3. View Outlier Concentration Rule (Only evaluated when n >= 3 video signals)
        content_signals = [
            s for s in signals
            if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) in ("youtube", "tiktok", "reels")
        ]
        total_views = sum(float(s.metric_value) for s in content_signals if float(s.metric_value) > 0)
        if len(content_signals) >= 3 and total_views > 0:
            max_signal = max(content_signals, key=lambda s: float(s.metric_value))
            max_views = float(max_signal.metric_value)
            view_ratio = max_views / total_views
            if view_ratio >= 0.5:
                flaws.append(
                    f"Severe view distribution skew: Single viral video ('{max_signal.raw_title[:45]}...') accounts for {round(view_ratio * 100, 1)}% of all video views ({int(max_views):,} / {int(total_views):,})."
                )

        # 4. Creator Diversity Score
        if channels:
            unique_channels = len(set(channels))
            creator_diversity = round(min(100.0, (unique_channels / float(len(channels))) * 100.0), 1)
            if creator_diversity >= 60.0:
                strengths.append(f"Diverse creator distribution ({unique_channels} independent channels).")
            else:
                flaws.append("Signals concentrated among very few creators (viewpoint bias risk).")
        else:
            creator_diversity = 70.0

        # 5. Data Freshness Score. Freshness is a property of the content, so this prefers the
        # publish time and only falls back to the ingestion time when the platform reports none.
        # The published_at field is authoritative; the metadata copy is read for rows written
        # before the field existed.
        now_utc = datetime.now(timezone.utc)
        in_timeframe_count = 0
        for s in signals:
            signal_dt = s.published_at
            if signal_dt is None and s.metadata and s.metadata.get("published_at"):
                pub_str = s.metadata["published_at"]
                try:
                    signal_dt = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
                except Exception:
                    signal_dt = None
            if signal_dt is None:
                signal_dt = s.captured_at

            if signal_dt:
                days_old = (now_utc - signal_dt).total_seconds() / 86400.0
                if days_old <= timeframe_days:
                    in_timeframe_count += 1
            else:
                in_timeframe_count += 1

        data_freshness_score = round((in_timeframe_count / float(len(signals))) * 100.0, 1)
        if data_freshness_score >= 80.0:
            strengths.append(f"High data freshness ({data_freshness_score}% matching {timeframe_days}-day window).")
        else:
            flaws.append(f"Low freshness score ({data_freshness_score}%), contains outdated signals.")

        # 6. Overall Confidence Score (Weighted average from configurable settings)
        base_confidence = (
            (coverage_score * settings.SCORECARD_WEIGHT_COVERAGE) +
            (language_precision * settings.SCORECARD_WEIGHT_LANGUAGE) +
            (data_freshness_score * settings.SCORECARD_WEIGHT_FRESHNESS) +
            (creator_diversity * settings.SCORECARD_WEIGHT_DIVERSITY)
        )

        # 7. Strict Localized Sample Size Guardrail & Penalty
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
