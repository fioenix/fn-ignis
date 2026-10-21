"""Author identity at rest: what Ignis removes, and the marker it keeps instead (Spec 015).

Ignis studies a market in aggregate and never needs to know who said something. Every author
field a connector emits is therefore removed before an observation is stored. What survives is a
per-mission marker: an HMAC of the author's platform reference under a key that belongs to one
mission. Within the mission the marker tells many voices from one voice; across missions the same
author gets unrelated markers, and without the key nobody can test a candidate handle against one.

The field names below are the platforms' own payload keys, matched verbatim. They are a structural
schema, not market vocabulary, so they live here rather than in `runtime_configs`: an operator
must not be able to weaken a privacy invariant by editing configuration (research R2).
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from ignis.domain.self_content import ACCOUNT_ID_METADATA_KEYS, AUTHOR_METADATA_KEYS

# Keys that name a person or carry their account, observed across the connectors (research R2).
_EXTRA_AUTHOR_KEYS = (
    "channel_id",
    "channel_title",
    "channel",
    "author_name",
    "nickname",
    "unique_id",
    "uniqueId",
    "user",
    "profile_url",
    "avatar",
)
AUTHOR_FIELD_KEYS: Tuple[str, ...] = tuple(
    dict.fromkeys(AUTHOR_METADATA_KEYS + ACCOUNT_ID_METADATA_KEYS + _EXTRA_AUTHOR_KEYS)
)

# Of those, the keys whose value is a stable reference to the account rather than a display name.
# A display name is neither unique nor stable, so it never feeds a marker.
_ACCOUNT_ID_KEYS = ACCOUNT_ID_METADATA_KEYS + ("channel_id",)
_HANDLE_KEYS = AUTHOR_METADATA_KEYS + ("unique_id", "uniqueId", "channel")

# Character-class patterns: the characters are the algorithm (the CLAUDE.md exception). They read
# the account segment of the link shapes the platforms use: /@handle on TikTok, Threads and
# YouTube; the first path segment on Instagram; /channel/, /user/ and /c/ on YouTube.
_AT_HANDLE = re.compile(r"/@([A-Za-z0-9._-]+)")
_YOUTUBE_ACCOUNT = re.compile(r"^/(?:channel|user|c)/([^/?#]+)")
# Instagram paths whose first segment is a content namespace, not an account.
_INSTAGRAM_CONTENT_SEGMENTS = frozenset({"p", "reel", "reels", "tv", "explore"})


class AuthorState(str, Enum):
    """What a stored observation can say about its author (data-model.md)."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"
    DECLARED = "DECLARED"


def _normalise_handle(value: Any) -> Optional[str]:
    text = str(value or "").strip().lstrip("@").lower()
    return text or None


def _url_account(url: Optional[str]) -> Optional[str]:
    """The account segment a link exposes, normalised, or None for a content-only link."""
    if not url or not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    at_handle = _AT_HANDLE.search(path)
    if at_handle:
        return _normalise_handle(at_handle.group(1))
    if host.endswith("instagram.com"):
        first = next((segment for segment in path.split("/") if segment), "")
        if first and first.lower() not in _INSTAGRAM_CONTENT_SEGMENTS:
            return _normalise_handle(first)
        return None
    if host.endswith("youtube.com"):
        account = _YOUTUBE_ACCOUNT.match(path)
        if account:
            return _normalise_handle(account.group(1))
    return None


def has_handle_segment(url: Optional[str]) -> bool:
    """True when a link names an account, so storing it would store who posted."""
    return _url_account(url) is not None


def _strip(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip(item)
            for key, item in value.items()
            if key not in AUTHOR_FIELD_KEYS and not (isinstance(item, str) and has_handle_segment(item))
        }
    if isinstance(value, list):
        return [_strip(item) for item in value if not (isinstance(item, str) and has_handle_segment(item))]
    return copy.deepcopy(value)


def strip_author_identity(metadata: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """A copy of the metadata with every author field and handle-bearing link removed, at any depth.

    Nested records -- a TikTok comment list, for one -- carry their own author fields and lose
    them too. A comment count is a number, not a record, and is kept. The input is not modified.
    """
    if not isinstance(metadata, Mapping):
        return {}
    return _strip(metadata)


def author_identity_violation(metadata: Optional[Mapping[str, Any]], source_url: Optional[str]) -> Optional[str]:
    """What kind of author identity a sighting still carries, or None when it carries none.

    The answer names the kind only, never the value, so a refusal built from it cannot itself
    leak the identity it refused to store.
    """
    if has_handle_segment(source_url):
        return "a source_url that names an account"
    if isinstance(metadata, Mapping) and strip_author_identity(metadata) != dict(metadata):
        return "metadata holding an author field or a link that names an account"
    return None


def _first_present(metadata: Mapping[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "") and not isinstance(value, (Mapping, list)):
            return str(value).strip() or None
    return None


def _references(metadata: Mapping[str, Any], source_url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(account id, normalised handle) as far as the payload reveals them."""
    nested_user = metadata.get("user") if isinstance(metadata.get("user"), Mapping) else {}
    account_id = _first_present(metadata, _ACCOUNT_ID_KEYS) or _first_present(nested_user, ("pk", "id"))
    handle = (
        _normalise_handle(_first_present(metadata, _HANDLE_KEYS))
        or _normalise_handle(_first_present(nested_user, ("username",)))
        or _url_account(source_url)
    )
    return account_id, handle


def author_marker(mission_key: bytes, reference: str) -> str:
    """HMAC-SHA256 of the author reference under the mission key, truncated to 64 bits (research R3)."""
    return hmac.new(mission_key, reference.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


@dataclass(frozen=True)
class AuthorAssignment:
    """The identity-free fact about one observation's author within one mission.

    `declared_name` is filled only when the fact is read back for a declared account; it is the
    name the requester gave, never something taken from the platform.
    """

    state: AuthorState
    marker: Optional[str] = None
    declared_account_id: Optional[str] = None
    declared_name: Optional[str] = None


def normalise_account_key(value: Any) -> Optional[str]:
    """A declared account as stored and matched: lower case, no leading @."""
    return _normalise_handle(value)


@dataclass(frozen=True)
class DeclaredAccount:
    """An account the requester declared for one mission: the only identity Ignis keeps (R8)."""

    id: str
    mission_id: str
    platform: str
    account_key: str
    declared_name: str
    declared_at: datetime


def declared_accounts_at(
    accounts: Iterable[DeclaredAccount], moment: Optional[datetime]
) -> Dict[Tuple[str, str], str]:
    """(platform, account key) -> declared account id, for content collected at `moment`.

    A declaration applies only to content collected after it was made, so an observation is never
    attributed after the fact. Content with no collection time gets no declaration.
    """
    if moment is None:
        return {}
    return {
        (account.platform, account.account_key): account.id
        for account in accounts
        if account.declared_at <= moment
    }


def _platform_name(platform: Any) -> str:
    value = platform.value if hasattr(platform, "value") else platform
    return str(value or "").strip().lower()


def assign_author(
    platform: Any,
    metadata: Optional[Mapping[str, Any]],
    source_url: Optional[str],
    mission_key: Optional[bytes],
    *,
    declared: Optional[Mapping[Tuple[str, str], str]] = None,
) -> AuthorAssignment:
    """Classify an observation's author before the identity is stripped.

    The reference is the platform plus the account id, or the normalised handle when no id is
    present. One author seen once by id and once only by handle therefore counts twice; that
    overcounts voices, which is the safe direction for a seeding check.

    `declared` maps (platform, normalised account key) to a declared account id. A declared
    author keeps that id and gets no marker. A missing mission key (no encryption key configured)
    makes every undeclared known author UNAVAILABLE.
    """
    name = _platform_name(platform)
    account_id, handle = _references(metadata if isinstance(metadata, Mapping) else {}, source_url)
    if account_id is None and handle is None:
        return AuthorAssignment(AuthorState.UNKNOWN)
    for candidate in (account_id, handle):
        if candidate is not None and declared:
            declared_id = declared.get((name, candidate.lower()))
            if declared_id is not None:
                return AuthorAssignment(AuthorState.DECLARED, declared_account_id=declared_id)
    if mission_key is None:
        return AuthorAssignment(AuthorState.UNAVAILABLE)
    reference = f"{name}:{account_id if account_id is not None else handle}"
    return AuthorAssignment(AuthorState.KNOWN, marker=author_marker(mission_key, reference))


@dataclass(frozen=True)
class AuthorConcentration:
    """How many voices a set of observations comes from, without saying whose (research R3, US2).

    `top_share` is the share of attributed observations from the single most frequent author, or
    None when no observation could be attributed. Declared accounts count as authors.
    """

    distinct_authors: int
    unknown: int
    unavailable: int
    top_share: Optional[float]

    @classmethod
    def from_assignments(cls, assignments: Iterable[AuthorAssignment]) -> "AuthorConcentration":
        voices: Counter = Counter()
        unknown = unavailable = 0
        for assignment in assignments:
            if assignment.state is AuthorState.KNOWN and assignment.marker:
                voices[assignment.marker] += 1
            elif assignment.state is AuthorState.DECLARED and assignment.declared_account_id:
                voices[f"declared:{assignment.declared_account_id}"] += 1
            elif assignment.state is AuthorState.UNAVAILABLE:
                unavailable += 1
            else:
                unknown += 1
        attributed = sum(voices.values())
        top_share = (max(voices.values()) / attributed) if attributed else None
        return cls(len(voices), unknown, unavailable, top_share)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "distinct_authors": self.distinct_authors,
            "unknown": self.unknown,
            "unavailable": self.unavailable,
            "top_share": self.top_share,
        }


__all__: List[str] = [
    "AUTHOR_FIELD_KEYS",
    "AuthorAssignment",
    "AuthorConcentration",
    "AuthorState",
    "DeclaredAccount",
    "assign_author",
    "author_identity_violation",
    "author_marker",
    "declared_accounts_at",
    "has_handle_segment",
    "normalise_account_key",
    "strip_author_identity",
]
