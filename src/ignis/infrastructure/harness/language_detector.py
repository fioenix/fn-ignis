import re
from typing import Optional, Set

from ignis.application.ports.language_detector_port import ILanguageDetector
from ignis.domain.value_objects import GeoCode


class HeuristicLanguageDetector(ILanguageDetector):
    """
    Multi-region linguistic and localization verification engine.
    Strictly verifies target language authenticity and eliminates rubber-stamp heuristics.
    """

    # Characters strictly unique to Vietnamese
    VI_EXCLUSIVE_CHARS_PATTERN = re.compile(
        r"[ơớờởỡợưứừửữựđĐắằẳẵặấầẩẫậếềểễệốồổỗộớờởỡợứừửữựỳỹỷỵảẻỉỏủẽĩạẹịọụ]",
        re.IGNORECASE,
    )

    # General Vietnamese diacritics (including shared Latin with accents)
    VI_ALL_DIACRITICS_PATTERN = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]",
        re.IGNORECASE,
    )

    # Foreign Non-Latin scripts (CJK Ideographs, Japanese Kana, Korean Hangul, Thai, Cyrillic, Arabic)
    FOREIGN_SCRIPTS_PATTERN = re.compile(
        r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff\u0e00-\u0e7f\u0400-\u04ff\u0600-\u06ff]"
    )

    # Japanese Kana strictly (Hiragana \u3040-\u309f + Katakana \u30a0-\u30ff)
    JAPANESE_KANA_PATTERN = re.compile(r"[\u3040-\u30ff]")
    CJK_IDEOGRAPHS_PATTERN = re.compile(r"[\u4e00-\u9fff]")

    # Korean Hangul
    KOREAN_HANGUL_PATTERN = re.compile(r"[\uac00-\ud7af]")

    # Thai script
    THAI_SCRIPT_PATTERN = re.compile(r"[\u0e00-\u0e7f]")

    # Distinctive non-English diacritics
    NON_ENGLISH_DIACRITICS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐãõñçüöäß]")

    # Unambiguous foreign multi-word phrases or non-English terms for Vietnamese filter
    VI_FOREIGN_PHRASES = {
        "formation complete", "formation complète", "avec", "cours pour", "dans le", "tuto debutant", "tuto débutant",
        "como criar", "como funcionam", "agentes autonomos", "agentes autônomos", "para você", "para voce",
        "inteligencia artificial", "inteligência artificial", "todos os", "fazer curso", "cara membuat", "untuk pemula"
    }

    PORTUGUESE_STOPWORDS = {
        "como", "para", "com", "por", "sobre", "este", "esta", "todos", "agora", "fazer",
        "curso", "gratis", "completo", "você", "voce", "seus", "suas", "criar", "criando",
        "ferramenta", "passo", "inteligencia", "artificial", "inteligência", "automatizar",
        "não", "nao", "em", "de", "da", "do", "que", "um", "uma", "automação", "automacao",
        "negócios", "negocios", "agentes"
    }

    TECH_LOAN_WORDS = {
        "ai", "bot", "chat", "agent", "agents", "app", "apps", "tool", "tools",
        "pro", "plus", "hub", "lab", "tech", "online", "code", "dev", "web",
        "net", "top", "mini", "shop", "store", "n8n", "mcp", "gpt", "saas",
        "workflow", "api", "cloud", "data", "deep", "learn", "fast", "setup"
    }

    VI_CORE_WORDS = {
        "va", "cua", "la", "trong", "cho", "voi", "ve", "tu", "dong", "hoa",
        "huong", "dan", "cach", "lam", "chu", "doanh", "nghiep", "ung", "dung",
        "giai", "phap", "phan", "mem", "tri", "tue", "nhan", "tao", "tro", "ly",
        "kiem", "tien", "nguoi", "viet", "nam", "danh", "bai", "hoc", "khoa",
        "thuc", "chien", "tong", "quan", "chi", "tiet", "zalo", "acc", "clone",
        "gia", "ban", "mua", "chot", "don", "kho", "hang", "cai", "dat",
        "sao", "gi", "tai", "bao", "nhieu", "cskh", "dai", "phi", "khong",
        "duoc", "nay", "moi", "tot", "nhat", "hay", "chia", "se", "kinh",
        "nghiem", "lieu", "tich", "xay", "dung", "van", "khach", "dich",
        "vu", "cong", "nghe", "nen", "tang"
    }

    # Core high-frequency English vocabulary and grammatical markers
    COMMON_ENGLISH_WORDS = {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on", "with",
        "he", "as", "you", "do", "at", "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
        "or", "an", "will", "my", "one", "all", "would", "there", "their", "what", "so", "up", "out", "if",
        "about", "who", "get", "which", "go", "me", "when", "make", "can", "like", "time", "no", "just", "him",
        "know", "take", "people", "into", "year", "your", "good", "some", "could", "them", "see", "other", "than",
        "then", "now", "look", "only", "come", "its", "over", "think", "also", "back", "after", "use", "two",
        "how", "our", "work", "first", "well", "way", "even", "new", "want", "because", "any", "these", "give",
        "day", "most", "us", "is", "are", "was", "were", "been", "has", "had", "guide", "tutorial", "best",
        "top", "review", "vs", "building", "build", "create", "creating", "free", "course", "complete", "beginner",
        "advanced", "automation", "system", "systems", "market", "marketing", "business", "software", "solution",
        "solutions", "enterprise", "agency", "step", "steps", "simple", "easy", "fast", "speed", "trends",
        "intelligence", "strategy", "strategies", "platform", "tools", "tool", "agents", "agent", "workflow",
        "workflows", "management", "analysis", "case", "study", "studies", "overview", "using", "with", "without",
        "future", "power", "scale", "scaling", "models", "model", "pipeline", "framework", "architecture"
    }

    def _matches_noise(self, text_lower: str, active_noise: Set[str]) -> bool:
        if not active_noise:
            return False
        for term in active_noise:
            if not term:
                continue
            clean_term = term.lstrip("#").strip()
            if not clean_term:
                continue
            pattern = rf"(?:\b|#){re.escape(clean_term)}\b"
            if re.search(pattern, text_lower):
                return True
        return False

    def _matches_extra_terms(self, text_lower: str, extra_terms: Optional[Set[str]]) -> bool:
        if not extra_terms:
            return False
        for term in extra_terms:
            clean = term.strip().lower()
            if clean and clean in text_lower:
                return True
        return False

    def is_localized(
        self,
        text: str,
        geo: GeoCode = GeoCode.VN,
        extra_terms: Optional[Set[str]] = None,
        extra_stopwords: Optional[Set[str]] = None,
        extra_noise: Optional[Set[str]] = None,
    ) -> bool:
        if not text or len(text.strip()) < 2:
            return False

        text_clean = text.strip()
        text_lower = text_clean.lower()
        geo_val = (geo.value if hasattr(geo, "value") else str(geo)).upper()

        # Step 1: Reject negative noise blacklist terms across all regions
        if extra_noise and self._matches_noise(text_lower, extra_noise):
            return False

        # Step 2: Global Whitelist - If text explicitly matches agent registered domain terms, allow it
        if extra_terms and self._matches_extra_terms(text_lower, extra_terms):
            return True

        # Step 3: Reject non-linguistic pure punctuation/number garbage
        letters_only = re.sub(r"[^a-zA-Z\u00C0-\u024F\u1EA0-\u1EF9\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af\u0e00-\u0e7f]", "", text_clean)
        if len(letters_only) < 2:
            return False

        # Step 4: Route by geographic region
        if geo_val == "VN":
            return self._is_vietnamese(
                text=text_clean,
                text_lower=text_lower,
                extra_terms=extra_terms,
                extra_stopwords=extra_stopwords,
            )
        elif geo_val in ("US", "GB", "CA", "AU", "GLOBAL"):
            return self._is_english(text_clean, text_lower)
        elif geo_val == "JP":
            return self._is_japanese(text_clean)
        elif geo_val == "KR":
            return self._is_korean(text_clean)
        elif geo_val == "TH":
            return self._is_thai(text_clean)
        elif geo_val in ("BR", "PT"):
            return self._is_portuguese(text_clean, text_lower)

        # Fallback for generic international regions: Latin script with minimum 3 alphabetic letters
        return len(letters_only) >= 3

    def _is_vietnamese(
        self,
        text: str,
        text_lower: str,
        extra_terms: Optional[Set[str]] = None,
        extra_stopwords: Optional[Set[str]] = None,
    ) -> bool:
        # Layer 1: Reject foreign non-Latin scripts (CJK, Korean, Thai, Cyrillic, Arabic)
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False

        # Layer 2: Reject unambiguous foreign phrases
        for fp in self.VI_FOREIGN_PHRASES:
            if fp in text_lower:
                return False

        words = set(re.findall(r"\b[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]+\b", text_lower))

        if extra_stopwords and any(sw.lower() in words for sw in extra_stopwords):
            return False

        # Layer 3: Exclusive Vietnamese characters with diacritics
        if self.VI_EXCLUSIVE_CHARS_PATTERN.search(text):
            return True

        # Layer 4: Unaccented text verification
        pure_words = words - self.TECH_LOAN_WORDS
        active_core = self.VI_CORE_WORDS | (extra_terms or set())
        vi_core_count = sum(1 for w in pure_words if w in active_core)
        return vi_core_count >= 2

    def _is_english(self, text: str, text_lower: str) -> bool:
        # 1. Reject foreign scripts (CJK, Japanese Kana, Korean Hangul, Thai, Cyrillic, Arabic)
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False

        # 2. Reject distinctive foreign non-English diacritics
        if self.NON_ENGLISH_DIACRITICS.search(text):
            return False

        # 3. Reject known non-English stopword phrases
        for fp in self.VI_FOREIGN_PHRASES:
            if fp in text_lower:
                return False

        # 4. Tokenize Latin words
        words = re.findall(r"\b[a-zA-Z]+\b", text_lower)
        if not words:
            return False

        # 5. Check against English vocabulary
        all_english_vocab = self.COMMON_ENGLISH_WORDS | self.TECH_LOAN_WORDS
        english_match_count = sum(1 for w in words if w in all_english_vocab)

        # Single word: must be in English vocabulary
        if len(words) == 1:
            return words[0] in all_english_vocab

        # Multi-word: require at least 2 recognized English words or >= 50% English words
        if english_match_count >= 2:
            return True

        return (english_match_count / float(len(words))) >= 0.5

    def _is_japanese(self, text: str) -> bool:
        # Must contain Japanese Kana (Hiragana/Katakana) to distinguish genuine Japanese from Chinese (ZH)
        return bool(self.JAPANESE_KANA_PATTERN.search(text))

    def _is_korean(self, text: str) -> bool:
        # Must contain Korean Hangul
        return bool(self.KOREAN_HANGUL_PATTERN.search(text))

    def _is_thai(self, text: str) -> bool:
        # Must contain Thai script
        return bool(self.THAI_SCRIPT_PATTERN.search(text))

    def _is_portuguese(self, text: str, text_lower: str) -> bool:
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False
        # Reject Vietnamese exclusive characters
        if self.VI_EXCLUSIVE_CHARS_PATTERN.search(text):
            return False
        words = set(re.findall(r"\b[a-zA-Záéíóúâêôãõç]+\b", text_lower))
        return any(pw in words for pw in self.PORTUGUESE_STOPWORDS)
