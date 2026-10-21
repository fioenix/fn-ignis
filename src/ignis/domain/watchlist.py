"""Watchlists: what a user follows across runs (Spec 016).

A watchlist version is an immutable definition of topics. Each topic names categories, keywords
and brand accounts, plus the share of a run's requests that may go to discovery inside the
topic's categories. The digest is taken over the normalised definition, so saving the same
meaning twice does not create a new version.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple

from ignis.domain.author_identity import normalise_account_key
from ignis.domain.value_objects import PlatformType

# Bounds that keep one run inside the per-channel daily request ceilings (spec FR-001, FR-002).
MAX_TOPICS = 10
MAX_KEYWORDS_PER_TOPIC = 20
MAX_DISCOVERY_SHARE = 0.2

# Platforms whose content has an account a brand can own; Google Trends has none.
BRAND_PLATFORMS = frozenset(p.value for p in PlatformType if p is not PlatformType.GOOGLE_TRENDS)

_TOPIC_KEYS = frozenset({"name", "categories", "keywords", "brands", "discovery_share"})
_BRAND_KEYS = frozenset({"platform", "account", "declared_name"})


class WatchlistDefinitionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WatchlistBrand:
    platform: str
    account: str
    declared_name: str

    def to_payload(self) -> dict:
        return {"platform": self.platform, "account": self.account, "declared_name": self.declared_name}


@dataclass(frozen=True)
class WatchlistTopic:
    name: str
    categories: Tuple[str, ...]
    keywords: Tuple[str, ...]
    brands: Tuple[WatchlistBrand, ...]
    discovery_share: float

    def to_payload(self) -> dict:
        return {
            "name": self.name,
            "categories": list(self.categories),
            "keywords": list(self.keywords),
            "brands": [brand.to_payload() for brand in self.brands],
            "discovery_share": self.discovery_share,
        }


@dataclass(frozen=True)
class WatchlistDefinition:
    topics: Tuple[WatchlistTopic, ...]

    def to_payload(self) -> dict:
        return {"topics": [topic.to_payload() for topic in self.topics]}

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _invalid(message: str) -> WatchlistDefinitionError:
    return WatchlistDefinitionError("INVALID_DEFINITION", message)


def _object(value: Any, allowed: frozenset, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{what} must be an object.")
    unknown = set(value) - allowed
    if unknown:
        raise _invalid(f"{what} has unknown fields: {', '.join(sorted(map(str, unknown)))}.")
    return value


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{what} must be non-blank text.")
    # Vietnamese arrives composed or decomposed depending on the keyboard; one form keeps one digest.
    return unicodedata.normalize("NFC", value.strip())


def _texts(value: Any, what: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _invalid(f"{what} must be a list of text.")
    return tuple(_text(item, what) for item in value)


def _share(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WatchlistDefinitionError("DISCOVERY_SHARE_OUT_OF_RANGE", "discovery_share must be a number.")
    if not 0 <= value <= MAX_DISCOVERY_SHARE:
        raise WatchlistDefinitionError(
            "DISCOVERY_SHARE_OUT_OF_RANGE", f"discovery_share must be between 0 and {MAX_DISCOVERY_SHARE}."
        )
    return float(value)


def _brand(value: Any) -> WatchlistBrand:
    item = _object(value, _BRAND_KEYS, "A brand")
    platform = str(item.get("platform") or "").strip().lower()
    account = normalise_account_key(item.get("account"))
    name = item.get("declared_name")
    if platform not in BRAND_PLATFORMS or account is None or not isinstance(name, str) or not name.strip():
        raise WatchlistDefinitionError(
            "INVALID_BRAND",
            f"A brand needs a platform among {', '.join(sorted(BRAND_PLATFORMS))}, an account and a declared_name.",
        )
    return WatchlistBrand(platform, account, unicodedata.normalize("NFC", name.strip()))


def _topic(value: Any) -> WatchlistTopic:
    item = _object(value, _TOPIC_KEYS, "A topic")
    name = _text(item.get("name"), "A topic name")
    categories = _texts(item.get("categories"), f"Categories of topic '{name}'")
    keywords = _texts(item.get("keywords"), f"Keywords of topic '{name}'")
    if not keywords:
        raise WatchlistDefinitionError("NO_KEYWORDS", f"Topic '{name}' needs at least one keyword.")
    if len(keywords) > MAX_KEYWORDS_PER_TOPIC:
        raise WatchlistDefinitionError(
            "TOO_MANY_KEYWORDS", f"Topic '{name}' has more than {MAX_KEYWORDS_PER_TOPIC} keywords."
        )
    if len({k.casefold() for k in keywords}) != len(keywords):
        raise WatchlistDefinitionError("DUPLICATE_KEYWORD", f"Topic '{name}' repeats a keyword.")
    raw_brands = item.get("brands") or []
    if not isinstance(raw_brands, (list, tuple)):
        raise _invalid(f"Brands of topic '{name}' must be a list.")
    brands = tuple(_brand(b) for b in raw_brands)
    if len({(b.platform, b.account) for b in brands}) != len(brands):
        raise WatchlistDefinitionError("DUPLICATE_BRAND", f"Topic '{name}' declares one brand account twice.")
    share = _share(item.get("discovery_share"))
    if share > 0 and not categories:
        raise WatchlistDefinitionError(
            "DISCOVERY_NEEDS_CATEGORY", f"Topic '{name}' needs a category to bound its discovery."
        )
    return WatchlistTopic(name, categories, keywords, brands, share)


def parse_watchlist_definition(value: Any) -> WatchlistDefinition:
    """Validate and normalise a definition, or raise WatchlistDefinitionError with a stable code."""
    item = _object(value, frozenset({"topics"}), "A watchlist definition")
    raw_topics = item.get("topics")
    if not isinstance(raw_topics, (list, tuple)):
        raise _invalid("topics must be a list.")
    if not raw_topics:
        raise WatchlistDefinitionError("NO_TOPICS", "A watchlist needs at least one topic.")
    if len(raw_topics) > MAX_TOPICS:
        raise WatchlistDefinitionError("TOO_MANY_TOPICS", f"A watchlist holds at most {MAX_TOPICS} topics.")
    topics = tuple(_topic(t) for t in raw_topics)
    if len({t.name.casefold() for t in topics}) != len(topics):
        raise WatchlistDefinitionError("DUPLICATE_TOPIC", "Two topics share a name.")
    return WatchlistDefinition(topics)


def watchlist_name(value: Any) -> Optional[str]:
    """A watchlist's display name, stripped and composed, or None when blank."""
    if not isinstance(value, str) or not value.strip():
        return None
    return unicodedata.normalize("NFC", value.strip())


def watchlist_name_key(name: str) -> str:
    """What makes two names the same inside a workspace: case-folded, as stored in name_key."""
    return name.casefold()


@dataclass(frozen=True)
class WatchlistVersion:
    version: int
    definition: WatchlistDefinition
    created_at: datetime


@dataclass(frozen=True)
class WatchlistRun:
    mission_id: str
    version: int
    started_at: datetime
    mission_status: Optional[str] = None


@dataclass(frozen=True)
class Watchlist:
    id: str
    workspace_id: str
    name: str
    created_at: datetime
    versions: Tuple[WatchlistVersion, ...]
    runs: Tuple[WatchlistRun, ...] = ()

    @property
    def current(self) -> WatchlistVersion:
        return self.versions[-1]


class WatchlistConflict(Exception):
    """A save the store refuses: the name is taken in the workspace, or the watchlist is unknown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
