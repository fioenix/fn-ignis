import re
from typing import Optional, Set

from ignis.application.ports.language_detector_port import ILanguageDetector
from ignis.domain.value_objects import GeoCode


class HeuristicLanguageDetector(ILanguageDetector):
    """
    Multi-region linguistic and localization verification engine.
    Uses subtractive filtering and authentic script/vocabulary rules to eliminate rubber-stamps and false negatives.
    """

    # Characters strictly unique to Vietnamese
    VI_EXCLUSIVE_CHARS_PATTERN = re.compile(
        r"[ơớờởỡợưứừửữựđĐắằẳẵặấầẩẫậếềểễệốồổỗộớờởỡợứừửữựỳỹỷỵảẻỉỏủẽĩạẹịọụ]",
        re.IGNORECASE,
    )

    # Foreign Non-Latin scripts (CJK Ideographs, Japanese Kana, Korean Hangul, Thai, Cyrillic, Arabic)
    FOREIGN_SCRIPTS_PATTERN = re.compile(
        r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff\u0e00-\u0e7f\u0400-\u04ff\u0600-\u06ff]"
    )

    # Japanese Kana strictly (Hiragana \u3040-\u309f + Katakana \u30a0-\u30ff)
    JAPANESE_KANA_PATTERN = re.compile(r"[\u3040-\u30ff]")

    # Korean Hangul
    KOREAN_HANGUL_PATTERN = re.compile(r"[\uac00-\ud7af]")

    # Thai script
    THAI_SCRIPT_PATTERN = re.compile(r"[\u0e00-\u0e7f]")

    # Non-English Latin diacritics (Vietnamese, Portuguese, French, Spanish, German, etc.)
    NON_ENGLISH_DIACRITICS = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐãõñçüöäß]"
    )

    # Foreign phrases for cross-language rejection
    FOREIGN_STOPWORD_PHRASES = {
        "formation complete", "formation complète", "avec", "cours pour", "dans le", "tuto debutant", "tuto débutant",
        "como criar", "como funcionam", "agentes autonomos", "agentes autônomos", "para você", "para voce",
        "inteligencia artificial", "inteligência artificial", "todos os", "fazer curso", "cara membuat", "untuk pemula",
        "de ia", "com ia", "para empresas"
    }

    PORTUGUESE_DISTINCTIVE_WORDS = {
        "como", "para", "com", "por", "sobre", "este", "esta", "todos", "agora", "fazer",
        "curso", "gratis", "completo", "você", "voce", "seus", "suas", "criar", "criando",
        "ferramenta", "passo", "inteligencia", "artificial", "inteligência", "automatizar",
        "não", "nao", "em", "do", "da", "que", "uma", "um", "automação", "automacao",
        "negócios", "negocios", "agentes"
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

    TECH_LOAN_WORDS = {
        "ai", "bot", "chat", "agent", "agents", "app", "apps", "tool", "tools",
        "pro", "plus", "hub", "lab", "tech", "online", "code", "dev", "web",
        "net", "top", "mini", "shop", "store", "n8n", "mcp", "gpt", "saas",
        "workflow", "api", "cloud", "data", "deep", "learn", "fast", "setup"
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

        # Step 2: Reject non-linguistic pure punctuation/number garbage
        letters_only = re.sub(r"[^a-zA-Z\u00C0-\u024F\u1EA0-\u1EF9\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af\u0e00-\u0e7f]", "", text_clean)
        if len(letters_only) < 3:
            return False

        # Step 3: Route by geographic region
        if geo_val == "VN":
            return self._is_vietnamese(
                text=text_clean,
                text_lower=text_lower,
                extra_terms=extra_terms,
                extra_stopwords=extra_stopwords,
            )
        elif geo_val in ("US", "GB", "CA", "AU", "GLOBAL"):
            return self._is_english(text_clean, text_lower, extra_terms=extra_terms)
        elif geo_val == "JP":
            return self._is_japanese(text_clean, extra_terms=extra_terms)
        elif geo_val == "KR":
            return self._is_korean(text_clean)
        elif geo_val == "TH":
            return self._is_thai(text_clean)
        elif geo_val in ("BR", "PT"):
            return self._is_portuguese(text_clean, text_lower, extra_terms=extra_terms)

        # Fallback for generic international regions: Latin script with minimum 3 alphabetic letters
        return len(letters_only) >= 3

    def _is_vietnamese(
        self,
        text: str,
        text_lower: str,
        extra_terms: Optional[Set[str]] = None,
        extra_stopwords: Optional[Set[str]] = None,
    ) -> bool:
        # 1. Reject foreign non-Latin scripts (CJK, Korean, Thai, Cyrillic, Arabic)
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False

        # 2. Reject foreign phrases
        for fp in self.FOREIGN_STOPWORD_PHRASES:
            if fp in text_lower:
                return False

        words = set(re.findall(r"\b[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]+\b", text_lower))

        if extra_stopwords and any(sw.lower() in words for sw in extra_stopwords):
            return False

        # 3. Exclusive Vietnamese characters with diacritics
        if self.VI_EXCLUSIVE_CHARS_PATTERN.search(text):
            return True

        # 4. Unaccented text verification
        pure_words = words - self.TECH_LOAN_WORDS
        active_core = self.VI_CORE_WORDS | {t.lower() for t in (extra_terms or set()) if len(t) >= 3}
        vi_core_count = sum(1 for w in pure_words if w in active_core)
        return vi_core_count >= 2

    def _is_english(self, text: str, text_lower: str, extra_terms: Optional[Set[str]] = None) -> bool:
        # 1. Reject foreign non-Latin scripts
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False

        # 2. Reject foreign diacritics
        if self.NON_ENGLISH_DIACRITICS.search(text):
            return False

        # 3. Reject foreign phrases
        for fp in self.FOREIGN_STOPWORD_PHRASES:
            if fp in text_lower:
                return False

        pure_alpha_words = set(re.findall(r"\b[a-zA-Z]+\b", text_lower))
        if not pure_alpha_words:
            return False

        # Total alpha characters must be at least 3
        total_alpha_len = sum(len(w) for w in pure_alpha_words)
        if total_alpha_len < 3:
            return False

        # 4. Reject if contains Vietnamese unaccented grammar (>= 2 core Vietnamese words)
        vi_matches = sum(1 for w in pure_alpha_words if w in self.VI_CORE_WORDS)
        if vi_matches >= 2:
            return False

        # 5. Reject if contains Portuguese/Spanish stopwords (>= 2 distinctive words)
        pt_matches = sum(1 for w in pure_alpha_words if w in self.PORTUGUESE_DISTINCTIVE_WORDS)
        if pt_matches >= 2:
            return False

        # 6. Reject pure consonant gibberish (e.g. 'asdfgh', 'zxcvbn')
        # Standard English/Latin words of length >= 4 must contain at least one vowel
        vowels_pattern = re.compile(r"[aeiouyAEIOUY]")
        long_words = [w for w in pure_alpha_words if len(w) >= 4]
        if long_words and any(not vowels_pattern.search(w) for w in long_words):
            return False

        # Must have at least 1 word with vowel
        has_vowel = any(vowels_pattern.search(w) for w in pure_alpha_words)
        return has_vowel

    def _is_japanese(self, text: str, extra_terms: Optional[Set[str]] = None) -> bool:
        # Must contain Japanese Kana (Hiragana/Katakana) to distinguish genuine Japanese from Chinese (ZH)
        if self.JAPANESE_KANA_PATTERN.search(text):
            return True
        # If agent explicitly whitelisted a domain term with Latin text (e.g. DeepSeek R1)
        if extra_terms:
            t_low = text.lower()
            for term in extra_terms:
                clean_term = term.strip().lower()
                # Must be >= 3 chars, and text must not contain Chinese characters without Kana
                if len(clean_term) >= 3 and clean_term in t_low and not re.search(r"[\u4e00-\u9fff]", text):
                    return True
        return False

    def _is_korean(self, text: str) -> bool:
        return bool(self.KOREAN_HANGUL_PATTERN.search(text))

    def _is_thai(self, text: str) -> bool:
        return bool(self.THAI_SCRIPT_PATTERN.search(text))

    def _is_portuguese(self, text: str, text_lower: str, extra_terms: Optional[Set[str]] = None) -> bool:
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False
        # Reject Vietnamese exclusive characters
        if self.VI_EXCLUSIVE_CHARS_PATTERN.search(text):
            return False
        words = set(re.findall(r"\b[a-zA-Záéíóúâêôãõç]+\b", text_lower))
        active_vocab = self.PORTUGUESE_DISTINCTIVE_WORDS | {t.lower() for t in (extra_terms or set()) if len(t) >= 3}
        return any(pw in words for pw in active_vocab)
