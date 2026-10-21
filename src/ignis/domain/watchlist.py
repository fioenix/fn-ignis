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

from ignis.domain.author_identity import (
    MAX_DECLARED_ACCOUNTS,
    MAX_DECLARED_NAME_LENGTH,
    declarable_account_key,
)
from ignis.domain.value_objects import PlatformType

# Bounds that keep one run inside the per-channel daily request ceilings (spec FR-001, FR-002).
MAX_TOPICS = 10
MAX_KEYWORDS_PER_TOPIC = 20
MAX_DISCOVERY_SHARE = 0.2
MAX_CATEGORIES_PER_TOPIC = 20
# Longest name, category, keyword or declared name; a search term or label, never a document.
MAX_TEXT_LENGTH = 200

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


def _clean(value: Any) -> Optional[str]:
    """Stripped, composed text, or None when blank or holding a control character or lone surrogate,
    which PostgreSQL cannot store and a digest cannot encode."""
    if not isinstance(value, str):
        return None
    # Vietnamese arrives composed or decomposed depending on the keyboard; one form keeps one digest
    # and one length.
    text = unicodedata.normalize("NFC", value.strip())
    if not text or any(unicodedata.category(character) in ("Cc", "Cs") for character in text):
        return None
    return text


def _text(value: Any, what: str, limit: int = MAX_TEXT_LENGTH) -> str:
    text = _clean(value)
    if text is None:
        raise _invalid(f"{what} must be non-blank text without control characters.")
    if len(text) > limit:
        raise WatchlistDefinitionError("TEXT_TOO_LONG", f"{what} is longer than {limit} characters.")
    return text


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
    account = declarable_account_key(item.get("account"))
    name = _clean(item.get("declared_name"))
    # The same rules as set_mission_declared_accounts, so every saved brand can be declared on a run.
    if platform not in BRAND_PLATFORMS or account is None or name is None or len(name) > MAX_DECLARED_NAME_LENGTH:
        raise WatchlistDefinitionError(
            "INVALID_BRAND",
            f"A brand needs a platform among {', '.join(sorted(BRAND_PLATFORMS))}, an account or profile"
            f" link without spaces, and a declared_name of at most {MAX_DECLARED_NAME_LENGTH} characters.",
        )
    return WatchlistBrand(platform, account, name)


def _topic(value: Any) -> WatchlistTopic:
    item = _object(value, _TOPIC_KEYS, "A topic")
    name = _text(item.get("name"), "A topic name")
    categories = _texts(item.get("categories"), f"Categories of topic '{name}'")
    if len(categories) > MAX_CATEGORIES_PER_TOPIC:
        raise WatchlistDefinitionError(
            "TOO_MANY_CATEGORIES", f"Topic '{name}' has more than {MAX_CATEGORIES_PER_TOPIC} categories."
        )
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
    if len({(b.platform, b.account) for t in topics for b in t.brands}) > MAX_DECLARED_ACCOUNTS:
        raise WatchlistDefinitionError(
            "TOO_MANY_BRANDS", f"A watchlist names at most {MAX_DECLARED_ACCOUNTS} brand accounts, as a run declares them."
        )
    return WatchlistDefinition(topics)


def definition_from_payload(payload: Mapping[str, Any]) -> WatchlistDefinition:
    """A stored, already validated definition, read without re-applying today's limits.

    Versions are immutable, so a rule tightened later must not make an earlier version unreadable.
    """
    return WatchlistDefinition(tuple(
        WatchlistTopic(
            name=topic["name"],
            categories=tuple(topic.get("categories") or ()),
            keywords=tuple(topic.get("keywords") or ()),
            brands=tuple(
                WatchlistBrand(b["platform"], b["account"], b["declared_name"]) for b in topic.get("brands") or ()
            ),
            discovery_share=float(topic.get("discovery_share") or 0.0),
        )
        for topic in payload.get("topics") or ()
    ))


def watchlist_name(value: Any) -> Optional[str]:
    """A watchlist's display name, stripped and composed, or None when blank, too long or holding a
    control character."""
    text = _clean(value)
    return text if text is not None and len(text) <= MAX_TEXT_LENGTH else None


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
