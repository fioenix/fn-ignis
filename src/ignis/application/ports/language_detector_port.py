from abc import ABC, abstractmethod
from typing import Optional, Set
from ignis.domain.value_objects import GeoCode


class ILanguageDetector(ABC):
    """Port interface for multi-region language and localization verification."""

    @abstractmethod
    def is_localized(
        self,
        text: str,
        geo: GeoCode = GeoCode.VN,
        extra_terms: Optional[Set[str]] = None,
        extra_stopwords: Optional[Set[str]] = None,
        extra_noise: Optional[Set[str]] = None,
    ) -> bool:
        """
        Verify if the given text matches the authentic linguistic profile of the target geo region.
        
        Args:
            text: Raw title or content to evaluate.
            geo: Target geographic region code (e.g., VN, US, JP, KR, TH, BR, GLOBAL).
            extra_terms: Optional domain-specific whitelist terms.
            extra_stopwords: Optional foreign stopwords to filter out.
            extra_noise: Optional negative noise/spam terms.
            
        Returns:
            True if text is localized for the target market; False otherwise.
        """
        pass
