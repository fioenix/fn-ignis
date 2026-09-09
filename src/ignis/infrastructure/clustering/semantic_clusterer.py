import math
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.domain.entities import TopicCluster, TrendSignal
from ignis.domain.probe_provenance import probe_keyword_of


class SemanticClusterer(IClusteringEngine):
    """
    Semantic topic clustering algorithm and Cross-Platform Momentum calculation.
    Uses Szymkiewicz-Simpson Overlap & Jaccard index for short text title matching.
    Sub-50ms deterministic execution without external LLM dependency.
    """

    AMBIGUOUS_UNIGRAMS: Set[str] = {
        "người", "đại", "việt", "nam", "mới", "hay", "làm", "nhất", "cực",
        "quá", "siêu", "top", "tin", "xem", "cho", "của", "và", "các", "những",
        "một", "hai", "ba", "bốn", "năm", "ngày", "đêm", "giờ", "phút", "vs", "new"
    }

    def __init__(
        self,
        similarity_threshold: float = 0.25,
        custom_stopwords: Optional[Set[str]] = None,
    ):
        self.similarity_threshold = similarity_threshold
        self._custom_stopwords: Set[str] = set(custom_stopwords or [])
        self._taxonomies: List[Tuple[str, Set[str]]] = []

    def register_stopwords(self, terms: List[str]) -> None:
        """Dynamically register stopwords from database or runtime config."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_stopwords.add(clean)

    def register_taxonomies(self, taxonomies: List[dict]) -> None:
        """Load industry taxonomies (industry_code + keywords) from the database for classification."""
        loaded: List[Tuple[str, Set[str]]] = []
        for item in taxonomies or []:
            code = str(item.get("industry_code") or "").strip().lower()
            keywords = {str(k).strip().lower() for k in (item.get("keywords") or []) if str(k).strip()}
            if code and keywords:
                loaded.append((code, keywords))
        self._taxonomies = loaded

    @staticmethod
    def _fold_accents(text: str) -> str:
        """Fold Vietnamese diacritics so 'khóa học' matches the ASCII lexicon entry 'khoa hoc'."""
        decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
        return "".join(ch for ch in decomposed if not unicodedata.combining(ch))

    # A category shorter than this is an abbreviation or a stray fragment, not a label.
    MIN_CATEGORY_CHARS = 3

    @classmethod
    def _is_usable_category(cls, raw: str) -> bool:
        """Whether a connector-provided category is a label rather than a number.

        The category arrives in connector metadata and is trusted ahead of taxonomy matching,
        so a parser that mislabels a column poisons it: three live clusters were filed under
        "27.6k", "6.4k" and "28k", which are view counts. The Creative Center parser is fixed at
        source, but third-party plugins implement the same port and cannot all be relied on.
        """
        text = (raw or "").strip()
        if len(text) < cls.MIN_CATEGORY_CHARS:
            return False
        # A metric, not a label: digits with an optional scale suffix or thousands separators.
        return not re.fullmatch(r"[\d.,]+\s*[kKmMbB]?", text)

    def _classify_category(self, group: List[TrendSignal]) -> str:
        """Resolve a cluster category: source-provided first, then taxonomy match, else unclassified."""
        source_categories: List[str] = []
        for s in group:
            raw = (s.metadata or {}).get("category")
            if raw and self._is_usable_category(str(raw)):
                source_categories.append(str(raw).strip().lower())
        if source_categories:
            return max(set(source_categories), key=source_categories.count)

        if self._taxonomies:
            # Taxonomy keywords are stored without diacritics, so fold both sides before matching.
            tokens: Set[str] = set()
            for s in group:
                tokens |= {self._fold_accents(t) for t in self._tokenize(s.raw_title)}
            haystack = self._fold_accents(" ".join(self._clean_title(s.raw_title).lower() for s in group))
            best_code, best_hits = "", 0
            for code, keywords in self._taxonomies:
                hits = sum(1 for kw in keywords if (kw in tokens) or (" " in kw and kw in haystack))
                if hits > best_hits:
                    best_code, best_hits = code, hits
            if best_code:
                return best_code

        return "unclassified"

    @classmethod
    def _clean_title(cls, text: str) -> str:
        """
        Strip hashtags (#tag), mentions (@user), URLs, emojis, and noise artifacts
        to extract core semantic phrase without relying on static dictionaries.
        """
        if not text:
            return ""
        import unicodedata
        text = unicodedata.normalize("NFC", text)
        # 1. Remove URLs
        s = re.sub(r"https?://\S+|www\.\S+", " ", text)
        # 2. Remove hashtags entirely (strip # and following tag characters)
        s = re.sub(r"#\w+", " ", s)
        # 3. Remove standalone viral noise words
        s = re.sub(r"\b(xuhuong|fyp|foryou|foryoupage|viral|trending|shorts|reels)\b", " ", s, flags=re.IGNORECASE)
        # 4. Remove user mentions
        s = re.sub(r"@\w+", " ", s)
        # 5. Remove emojis & unicode surrogate/pictograph blocks
        s = re.sub(r"[\U00010000-\U0010ffff]", " ", s)
        s = re.sub(r"[\u2600-\u27bf]", " ", s)
        # 6. Remove repeated emoticon artifacts like =)) :)) ^^
        s = re.sub(r"[=:]\)+|\^\^|(?::|;|=)-?[)(/\\dDpP]", " ", s)
        # 7. Normalize whitespaces and strip leading/trailing punctuation
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
            canonical = cls._clean_title(canonical)

        if not canonical:
            canonical = "Aggregated trending topic"

        # Capitalize first character for clean presentation
        canonical = canonical[0].upper() + canonical[1:] if len(canonical) > 1 else canonical.upper()
        if len(canonical) > 80:
            canonical = canonical[:77].rsplit(" ", 1)[0] + "..." if " " in canonical[:77] else canonical[:77] + "..."
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
        if len(intersection) == 1:
            shared_token = next(iter(intersection))
            # If both titles have 2 or more tokens, a single shared token is insufficient
            # to declare identical topics (two titles sharing only one generic word are different topics)
            if len(tokens_a) >= 2 and len(tokens_b) >= 2:
                return 0.0
            # If one side is a single token, reject ambiguous/generic single unigrams
            if shared_token.lower() in self.AMBIGUOUS_UNIGRAMS:
                return 0.0

        overlap = len(intersection) / min(len(tokens_a), len(tokens_b))
        jaccard = len(intersection) / len(tokens_a.union(tokens_b))
        
        # Weighted composite: 70% Overlap + 30% Jaccard
        return 0.7 * overlap + 0.3 * jaccard

    # Log10 ceilings calibrating the 40 (platform) / 40 (metric) / 20 (velocity) contract of spec 003 FR-003.
    # They keep realistic volumes on the linear part of the curve instead of pinning every topic at the cap,
    # while a genuine multi-platform breakout can still reach the >= 80 BREAKOUT threshold.
    METRIC_LOG_CEILING = 8.0
    VELOCITY_LOG_CEILING = 4.0

    # Words kept in a topic label.
    TOPIC_LABEL_MAX_WORDS = 6
    # A token appearing in more than this share of clusters describes the corpus, not one topic.
    MAX_TOKEN_DOCUMENT_SHARE = 0.15
    # Minimum in-cluster count per cluster it appears in, before a token may headline a label.
    MIN_TOKEN_DISTINCTIVENESS = 0.9

    def _token_document_frequency(self, groups: List[List[TrendSignal]]) -> Dict[str, int]:
        """Count how many clusters each token appears in, so ubiquitous words can be discounted."""
        doc_freq: Dict[str, int] = {}
        for group in groups:
            tokens: Set[str] = set()
            for signal in group:
                tokens |= self._tokenize(signal.raw_title or "")
            for token in tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1
        return doc_freq

    def _build_topic_label(
        self,
        canonical_name: str,
        group: List[TrendSignal],
        doc_freq: Dict[str, int],
        total_clusters: int,
    ) -> str:
        """Summarise a cluster into a short topic label instead of one signal's verbatim title.

        Score every window of words in the canonical name by how many of its tokens recur across
        the cluster's other signals, and keep the densest window: what survives is the vocabulary
        the cluster actually shares rather than whatever preceded it in one post.
        """
        canonical = self._clean_title(canonical_name or "")
        words = [w for w in canonical.split() if w]
        if not words:
            return canonical_name or ""

        shared: Set[str] = set()
        counts: Dict[str, int] = {}
        if len(group) > 1:
            for signal in group:
                for token in self._tokenize(signal.raw_title or ""):
                    counts[token] = counts.get(token, 0) + 1
            quorum = max(2, (len(group) + 1) // 2)
            ceiling = max(2, int(total_clusters * self.MAX_TOKEN_DOCUMENT_SHARE))
            shared = {
                token for token, count in counts.items()
                if count >= quorum and doc_freq.get(token, 1) <= ceiling
            }

        window = min(self.TOPIC_LABEL_MAX_WORDS, len(words))
        normalized = [re.sub(r"[^\w]", "", w.lower()) for w in words]
        best_start, best_score = 0, -1
        for start in range(0, len(words) - window + 1):
            score = sum(1 for token in normalized[start:start + window] if token in shared)
            if score > best_score:
                best_start, best_score = start, score

        if best_score <= 0 and counts:
            # No phrase recurs across the cluster, so quoting any window would just quote one post.
            # Fall back to the tokens this cluster leans on that the rest of the corpus does not.
            # A bare number is never a topic: a year, a count or a score carries no subject on
            # its own. Digits stay in the tokens themselves, where they separate "iPhone 17" from
            # "iPhone 16", and are only barred from headlining a label.
            ranked = sorted(
                (
                    (token, count / max(1, doc_freq.get(token, 1)))
                    for token, count in counts.items()
                    if count > 1 and not token.isdigit()
                ),
                key=lambda kv: (-kv[1], kv[0]),
            )
            top = [token for token, weight in ranked[:3] if weight > self.MIN_TOKEN_DISTINCTIVENESS]
            if top:
                return " \u00b7 ".join(top)

        start, end = best_start, best_start + window
        if best_score > 0:
            while end - start > 2 and normalized[start] not in shared:
                start += 1
            while end - start > 2 and normalized[end - 1] not in shared:
                end -= 1

        label = " ".join(words[start:end]).strip(" -:;,.\"'")
        if start > 0:
            label = "\u2026 " + label
        if end < len(words):
            label = label + " \u2026"
        return label or canonical

    def _calculate_cross_platform_score(self, signals: List[TrendSignal]) -> float:
        if not signals:
            return 0.0

        unique_platforms = {s.platform for s in signals}
        platform_diversity_score = (len(unique_platforms) / 5.0) * 40.0

        total_metric = sum(s.metric_value for s in signals)
        metric_score = min(40.0, (math.log10(max(0.0, total_metric) + 1.0) / self.METRIC_LOG_CEILING) * 40.0)

        avg_velocity = sum(s.growth_velocity for s in signals) / len(signals)
        velocity_score = min(20.0, (math.log10(max(0.0, avg_velocity) + 1.0) / self.VELOCITY_LOG_CEILING) * 20.0)

        return round(min(100.0, platform_diversity_score + metric_score + velocity_score), 1)

    async def cluster_signals(self, signals: List[TrendSignal]) -> List[TopicCluster]:
        if not signals:
            return []

        # Signals retrieved by the same keyword are about the same subject by construction, which
        # is stronger evidence than token overlap: a video title and a forum post about one topic
        # rarely share enough words to cross the threshold. Only signals that arrived in a feed,
        # and so carry no provenance, are matched by similarity.
        by_probe: Dict[str, List[TrendSignal]] = {}
        unattributed: List[TrendSignal] = []
        for signal in signals:
            probe = probe_keyword_of(signal)
            if probe:
                by_probe.setdefault(probe, []).append(signal)
            else:
                unattributed.append(signal)

        groups: List[List[TrendSignal]] = list(by_probe.values())

        tokenized_signals = [(s, self._tokenize(s.raw_title)) for s in unattributed]
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

            groups.append(group)

        from ignis.domain.normalization import normalize_cluster_name

        # Labelling needs the whole pass: a token only earns a headline by being rarer across the
        # other clusters than inside this one, which cannot be judged one group at a time.
        doc_freq = self._token_document_frequency(groups)
        clusters: List[TopicCluster] = []

        for group in groups:
            canonical_name = normalize_cluster_name(self._select_canonical_name(group))

            # Deterministic cluster UUID based on normalized canonical_name to prevent duplicate cluster records across runs
            cluster_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"cluster:{canonical_name}")
            for s in group:
                s.cluster_id = cluster_id

            score = self._calculate_cross_platform_score(group)

            cluster = TopicCluster(
                id=cluster_id,
                canonical_name=canonical_name,
                summary_text=f"Aggregated topic from {len(group)} signals across {len({s.platform for s in group})} platforms.",
                category=self._classify_category(group),
                cross_platform_score=score,
                signals=group,
                first_seen_at=min(s.captured_at for s in group),
                last_updated_at=datetime.now(timezone.utc),
            )
            cluster.topic_label = self._build_topic_label(
                canonical_name, group, doc_freq, len(groups)
            )
            clusters.append(cluster)

        clusters.sort(key=lambda c: c.cross_platform_score, reverse=True)
        return clusters
