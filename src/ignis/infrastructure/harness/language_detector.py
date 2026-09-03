import re
from typing import Optional, Set

from ignis.application.ports.language_detector_port import ILanguageDetector
from ignis.domain.value_objects import GeoCode


class HeuristicLanguageDetector(ILanguageDetector):
    """
    Multi-region heuristic language and localization detector.
    Evaluates linguistic authenticity, diacritic markers, scripts, and noise filters.
    """

    # Characters strictly unique to Vietnamese
    VI_EXCLUSIVE_CHARS_PATTERN = re.compile(
        r"[ơớờởỡợưứừửữựđĐắằẳẵặấầẩẫậếềểễệốồổỗộớờởỡợứừửữựỳỹỷỵảẻỉỏủẽĩạẹịọụ]",
        re.IGNORECASE,
    )

    # Shared Latin diacritics (Portuguese, Spanish, French, etc.)
    SHARED_LATIN_DIACRITICS = re.compile(r"[ôéèáàâóíúç]", re.IGNORECASE)

    # Foreign Non-Latin scripts (Hangul, Hanzi/Kanji, Kana, Thai, Cyrillic, Arabic)
    FOREIGN_SCRIPTS_PATTERN = re.compile(
        r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff\u0e00-\u0e7f\u0400-\u04ff\u0600-\u06ff]"
    )

    # Specific script patterns
    JAPANESE_SCRIPT_PATTERN = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
    KOREAN_SCRIPT_PATTERN = re.compile(r"[\uac00-\ud7af]")
    THAI_SCRIPT_PATTERN = re.compile(r"[\u0e00-\u0e7f]")

    FOREIGN_STOPWORDS = {
        # French
        "formation", "complete", "complète", "avec", "cours", "pour", "dans", "tuto", "debutant", "débutant",
        # Portuguese / Spanish
        "como", "funcionam", "chegou", "novos", "veja", "agentes", "autonomos", "autônomos",
        "para", "com", "por", "sobre", "este", "esta", "todos", "agora", "fazer", "curso",
        "gratis", "completo", "você", "voce", "seus", "suas", "criar", "criando",
        "ferramenta", "passo", "inteligencia", "artificial", "automatizar",
        # Indonesian / Malay
        "cara", "yang", "untuk", "bisa"
    }

    PORTUGUESE_STOPWORDS = {
        "como", "para", "com", "por", "sobre", "este", "esta", "todos", "agora", "fazer",
        "curso", "gratis", "completo", "você", "voce", "seus", "suas", "criar", "criando",
        "ferramenta", "passo", "inteligencia", "artificial", "automatizar", "não", "nao",
        "em", "de", "da", "do", "que", "um", "uma"
    }

    TECH_LOAN_WORDS = {
        "ai", "bot", "chat", "agent", "app", "tool", "pro", "plus", "hub", "lab",
        "tech", "online", "code", "dev", "web", "net", "top", "mini", "shop", "store"
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

        # Step 1: Reject negative noise blacklist terms
        if extra_noise and self._matches_noise(text_lower, extra_noise):
            return False

        # Step 2: Route by geographic region
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

        # Fallback for generic international regions:
        return len(text_clean) >= 3

    def _is_vietnamese(
        self,
        text: str,
        text_lower: str,
        extra_terms: Optional[Set[str]] = None,
        extra_stopwords: Optional[Set[str]] = None,
    ) -> bool:
        # Layer 1: Reject foreign non-Latin scripts
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False

        words = set(re.findall(r"\b[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]+\b", text_lower))

        # Layer 2: Reject foreign stopwords
        all_stopwords = self.FOREIGN_STOPWORDS | (extra_stopwords or set())
        if any(fw in words for fw in all_stopwords):
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
        # English market: Reject Asian/Cyrillic/Arabic foreign scripts
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False
        # Must contain Latin word characters
        words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text_lower)
        return len(words) >= 1

    def _is_japanese(self, text: str) -> bool:
        return bool(self.JAPANESE_SCRIPT_PATTERN.search(text))

    def _is_korean(self, text: str) -> bool:
        return bool(self.KOREAN_SCRIPT_PATTERN.search(text))

    def _is_thai(self, text: str) -> bool:
        return bool(self.THAI_SCRIPT_PATTERN.search(text))

    def _is_portuguese(self, text: str, text_lower: str) -> bool:
        if self.FOREIGN_SCRIPTS_PATTERN.search(text):
            return False
        if re.search(r"[ãõáéíóúâêôç]", text, re.IGNORECASE):
            return True
        words = set(re.findall(r"\b[a-zA-Z]+\b", text_lower))
        return any(pw in words for pw in self.PORTUGUESE_STOPWORDS)
