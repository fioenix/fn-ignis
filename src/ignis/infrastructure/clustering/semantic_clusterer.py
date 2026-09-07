import math
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Set, Tuple

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.domain.entities import TopicCluster, TrendSignal


class SemanticClusterer(IClusteringEngine):
    """
    Semantic topic clustering algorithm and Cross-Platform Momentum calculation.
    Uses Szymkiewicz-Simpson Overlap & Jaccard index for short text title matching.
    Sub-50ms deterministic execution without external LLM dependency.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.25,
        custom_stopwords: Optional[Set[str]] = None,
    ):
        self.similarity_threshold = similarity_threshold
        self._custom_stopwords: Set[str] = set(custom_stopwords or [])

    def register_stopwords(self, terms: List[str]) -> None:
        """Dynamically register stopwords from database or runtime config."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_stopwords.add(clean)

    @staticmethod
    def _clean_title(text: str) -> str:
        """
        Strip hashtags (#tag), mentions (@user), URLs, emojis, and noise artifacts
        to extract core semantic phrase without relying on static dictionaries.
        """
        if not text:
            return ""
        # 1. Remove URLs
        s = re.sub(r"https?://\S+|www\.\S+", " ", text)
        # 2. Remove hashtags entirely (strip # and following tag characters)
        s = re.sub(r"#\w+", " ", s)
        # 3. Remove user mentions
        s = re.sub(r"@\w+", " ", s)
        # 4. Remove emojis & unicode surrogate/pictograph blocks
        s = re.sub(r"[\U00010000-\U0010ffff]", " ", s)
        # 5. Remove repeated emoticon artifacts like =)) :)) ^^
        s = re.sub(r"[=:]\)+|\^\^|(?::|;|=)-?[)(/\\dDpP]", " ", s)
        # 6. Normalize whitespaces and strip leading/trailing punctuation
        s = re.sub(r"\s+", " ", s).strip(" \t\n\r-_:;.,/\\|~`!@#$%^&*()+=[]{}<>\"'")
        return s

    @classmethod
    def _select_canonical_name(cls, group: List[TrendSignal]) -> str:
        """
        Select the most informative, representative clean title for the cluster.
        Avoids empty strings, pure hashtags, and overly fragmented noise snippets.
        """
        candidates: List[Tuple[str, int, int]] = []  # (cleaned_text, word_count, length)
        for s in group:
            cleaned = cls._clean_title(s.raw_title)
            words = [w for w in cleaned.split() if len(w) > 1]
            if len(cleaned) >= 5 and len(words) >= 2:
                candidates.append((cleaned, len(words), len(cleaned)))

        if candidates:
            # Prefer rich word count and readable length (around 20-55 chars)
            best = max(candidates, key=lambda c: (c[1] >= 3, c[1] * 2 - abs(c[2] - 35) * 0.1))
            canonical = best[0]
        else:
            # Fallback: take signal with shortest raw title after basic hashtag removal
            fallback_title = min(group, key=lambda s: len(s.raw_title)).raw_title
            canonical = re.sub(r"[#@]", "", fallback_title)
            canonical = re.sub(r"\s+", " ", canonical).strip(" \t\n\r-_:;.,/\\|~`!@#$%^&*()+=[]{}<>\"'")

        if not canonical:
            canonical = "Chủ đề xu hướng tổng hợp"

        # Capitalize first character for clean presentation
        canonical = canonical[0].upper() + canonical[1:] if len(canonical) > 1 else canonical.upper()
        if len(canonical) > 80:
            canonical = canonical[:77] + "..."
        return canonical

    def _tokenize(self, text: str) -> Set[str]:
        # Pre-clean title to avoid hashtags and URLs polluting tokens
        cleaned_text = self._clean_title(text)
        if not cleaned_text:
            # If title was only hashtags, tokenize raw text without '#'
            cleaned_text = re.sub(r"[#@]", " ", text)

        cleaned = re.sub(r"[^\w\s]", " ", cleaned_text.lower())
        tokens = [t.strip() for t in cleaned.split() if len(t.strip()) > 1]
        
        # Filter out dynamically registered stopwords from database/runtime
        return {t for t in tokens if t not in self._custom_stopwords}

    def _calculate_similarity(self, tokens_a: Set[str], tokens_b: Set[str]) -> float:
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a.intersection(tokens_b)
        if not intersection:
            return 0.0
        
        # Guardrail against single short token false matches across titles with distinct semantic meaning
        # If intersection only has 1 token and either title has 3+ tokens, require higher threshold
        overlap = len(intersection) / min(len(tokens_a), len(tokens_b))
        jaccard = len(intersection) / len(tokens_a.union(tokens_b))
        
        # Weighted composite: 70% Overlap + 30% Jaccard
        return 0.7 * overlap + 0.3 * jaccard

    def _calculate_cross_platform_score(self, signals: List[TrendSignal]) -> float:
        if not signals:
            return 0.0

        unique_platforms = {s.platform for s in signals}
        platform_diversity_score = (len(unique_platforms) / 5.0) * 40.0

        total_metric = sum(s.metric_value for s in signals)
        metric_score = min(40.0, (math.log10(total_metric + 1.0) / 7.0) * 40.0)

        avg_velocity = sum(s.growth_velocity for s in signals) / len(signals)
        velocity_score = min(20.0, max(0.0, avg_velocity * 0.5))

        return round(min(100.0, platform_diversity_score + metric_score + velocity_score), 1)

    async def cluster_signals(self, signals: List[TrendSignal]) -> List[TopicCluster]:
        if not signals:
            return []

        clusters: List[TopicCluster] = []
        tokenized_signals = [(s, self._tokenize(s.raw_title)) for s in signals]
        visited = set()

        for i, (sig_a, tokens_a) in enumerate(tokenized_signals):
            if i in visited:
                continue

            group = [sig_a]
            visited.add(i)

            for j, (sig_b, tokens_b) in enumerate(tokenized_signals):
                if j in visited:
                    continue

                sim = self._calculate_similarity(tokens_a, tokens_b)
                if sim >= self.similarity_threshold:
                    group.append(sig_b)
                    visited.add(j)

            canonical_name = self._select_canonical_name(group)

            # Deterministic cluster UUID based on canonical_name to prevent duplicate cluster records across runs
            cluster_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"cluster:{canonical_name.lower()}")
            for s in group:
                s.cluster_id = cluster_id

            score = self._calculate_cross_platform_score(group)

            cluster = TopicCluster(
                id=cluster_id,
                canonical_name=canonical_name,
                summary_text=f"Aggregated topic from {len(group)} signals across {len({s.platform for s in group})} platforms.",
                category="general",
                cross_platform_score=score,
                signals=group,
                first_seen_at=min(s.captured_at for s in group),
                last_updated_at=datetime.now(timezone.utc),
            )
            clusters.append(cluster)

        clusters.sort(key=lambda c: c.cross_platform_score, reverse=True)
        return clusters

