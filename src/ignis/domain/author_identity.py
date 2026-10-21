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
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import unquote, urlsplit

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
# Keys that hold the platform handle itself, preferred over anything else that may be a handle.
_STABLE_HANDLE_KEYS = ("unique_id", "uniqueId", "username", "author_username", "handle")
# Keys that hold a handle on some connectors and a display name on others. Read last, and only
# when the value looks like a handle (no whitespace), so two creators sharing a display name are
# never merged and a declared handle in the link wins over a name.
_LOOSE_HANDLE_KEYS = ("author", "creator", "owner", "channel")

# Character-class patterns: the characters are the algorithm (the CLAUDE.md exception). They read
# the account segment of the link shapes the platforms use: /@handle (ASCII or full-width at sign,
# any Unicode handle, percent-decoded first) on TikTok, Threads and YouTube; the first path segment
# on Instagram, or the second under /stories/; /channel/, /user/ and /c/ on YouTube.
_AT_HANDLE = re.compile(r"/[@\uff20]([^/?#\s]+)")
_YOUTUBE_ACCOUNT = re.compile(r"^/(?:channel|user|c)/([^/?#]+)")
# A link written without its scheme still names an account on these hosts.
_SCHEMELESS_PLATFORM_LINK = re.compile(
    r"^(?:[a-z0-9-]+\.)*(?:tiktok\.com|threads\.com|threads\.net|instagram\.com|youtube\.com)(?:[/?#]|$)",
    re.IGNORECASE,
)
# A link written inside prose, with or without its scheme. Trailing sentence punctuation is not
# part of the link.
_LINK_IN_TEXT = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+"
    r"|(?<![\w.@/])(?:[a-z0-9-]+\.)*(?:tiktok\.com|threads\.com|threads\.net|instagram\.com|youtube\.com)/[^\s<>\"']*",
    re.IGNORECASE,
)
_LINK_TRAILING_PUNCTUATION = ".,;:!?)]}"
LINK_PLACEHOLDER = "[link]"
# Instagram paths whose first segment is a content or service namespace, not an account.
_INSTAGRAM_CONTENT_SEGMENTS = frozenset(
    {"p", "reel", "reels", "tv", "explore", "accounts", "s", "direct", "about", "legal", "developer", "web"}
)


class AuthorState(str, Enum):
    """What a stored observation can say about its author (data-model.md)."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"
    DECLARED = "DECLARED"


def _normalise_handle(value: Any) -> Optional[str]:
    text = unicodedata.normalize("NFC", str(value or "")).strip().lstrip("@\uff20").lower()
    return text or None


def _url_account(url: Optional[str]) -> Optional[str]:
    """The account segment a link exposes, normalised, or None for a content-only link."""
    if not url or not isinstance(url, str):
        return None
    text = url.strip()
    if "://" not in text:
        if not _SCHEMELESS_PLATFORM_LINK.match(text):
            return None
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    path = unicodedata.normalize("NFC", unquote(parts.path or ""))
    at_handle = _AT_HANDLE.search(path)
    if at_handle:
        return _normalise_handle(at_handle.group(1))
    if host.endswith("instagram.com"):
        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            return None
        if segments[0].lower() == "stories":
            return _normalise_handle(segments[1]) if len(segments) > 1 else None
        if segments[0].lower() not in _INSTAGRAM_CONTENT_SEGMENTS:
            return _normalise_handle(segments[0])
        return None
    if host.endswith("youtube.com"):
        account = _YOUTUBE_ACCOUNT.match(path)
        if account:
            return _normalise_handle(account.group(1))
    return None


def account_in_link(url: Optional[str]) -> Optional[str]:
    """The normalised account a profile or post link names, or None when it names none."""
    return _url_account(url)


def has_handle_segment(url: Optional[str]) -> bool:
    """True when a link names an account, so storing it would store who posted."""
    return _url_account(url) is not None


def scrub_handle_links(text: Any) -> Any:
    """Replace each link inside prose that names an account with [link]; content links stay."""
    if not isinstance(text, str) or not text:
        return text

    def replace(match: "re.Match[str]") -> str:
        link = match.group(0).rstrip(_LINK_TRAILING_PUNCTUATION)
        tail = match.group(0)[len(link):]
        return f"{LINK_PLACEHOLDER}{tail}" if has_handle_segment(link) else match.group(0)

    return _LINK_IN_TEXT.sub(replace, text)


def _strip(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip(item)
            for key, item in value.items()
            if key not in AUTHOR_FIELD_KEYS and not (isinstance(item, str) and has_handle_segment(item))
        }
    if isinstance(value, (list, tuple)):
        return [_strip(item) for item in value if not (isinstance(item, str) and has_handle_segment(item))]
    if isinstance(value, str):
        return scrub_handle_links(value)
    return copy.deepcopy(value)


def strip_author_identity(metadata: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """A copy of the metadata with every author field and handle-bearing link removed, at any depth.

    Nested records -- a TikTok comment list, for one -- carry their own author fields and lose
    them too. A comment count is a number, not a record, and is kept. The input is not modified.
    """
    if not isinstance(metadata, Mapping):
        return {}
    return _strip(metadata)


def author_identity_violation(
    metadata: Optional[Mapping[str, Any]], source_url: Optional[str], title: Optional[str] = None
) -> Optional[str]:
    """What kind of author identity a sighting still carries, or None when it carries none.

    The answer names the kind only, never the value, so a refusal built from it cannot itself
    leak the identity it refused to store.
    """
    if has_handle_segment(source_url):
        return "a source_url that names an account"
    if scrub_handle_links(title) != title:
        return "a title holding a link that names an account"
    if isinstance(metadata, Mapping) and strip_author_identity(metadata) != dict(metadata):
        return "metadata holding an author field or a link that names an account"
    return None


def _first_present(metadata: Mapping[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "") and not isinstance(value, (Mapping, list)):
            return str(value).strip() or None
    return None


def _handle_like(value: Optional[str]) -> Optional[str]:
    handle = _normalise_handle(value)
    return handle if handle and not any(character.isspace() for character in handle) else None


def _references(metadata: Mapping[str, Any], source_url: Optional[str]) -> Tuple[Optional[str], List[str]]:
    """(account id, candidate handles in order of trust) as far as the payload reveals them.

    Stable handle keys first, then the link, then keys that some connectors fill with a display
    name -- and those only when the value looks like a handle.
    """
    nested_user = metadata.get("user") if isinstance(metadata.get("user"), Mapping) else {}
    account_id = _first_present(metadata, _ACCOUNT_ID_KEYS) or _first_present(nested_user, ("pk", "id"))
    candidates = [
        _handle_like(_first_present(metadata, _STABLE_HANDLE_KEYS)),
        _handle_like(_first_present(nested_user, ("username",))),
        _url_account(source_url),
        *(_handle_like(_first_present(metadata, (key,))) for key in _LOOSE_HANDLE_KEYS),
    ]
    return account_id, list(dict.fromkeys(handle for handle in candidates if handle))


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


# Bounds on what a requester may declare (research R8). Watchlists hold the same brand accounts, so
# they share these bounds and a saved brand is always one a run can declare.
MAX_DECLARED_ACCOUNTS = 50
MAX_ACCOUNT_LENGTH = 100
MAX_DECLARED_NAME_LENGTH = 120


def declarable_account_key(value: Any) -> Optional[str]:
    """A handle or account id as declared, a profile link reduced to its handle; None when the value
    names no account, is longer than MAX_ACCOUNT_LENGTH or contains a space."""
    if not isinstance(value, str):
        return None
    key = account_in_link(value) if ("/" in value or "://" in value) else normalise_account_key(value)
    if not key or len(key) > MAX_ACCOUNT_LENGTH or any(character.isspace() for character in key):
        return None
    return key


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

    The reference is the platform plus the account id, or the most trusted handle when no id is
    present; a display name never is. One author seen once by id and once only by handle
    therefore counts as two voices. That overcounts voices and so understates concentration -- the
    unsafe direction for a seeding check -- which is why the account id is preferred whenever the
    payload carries one.

    `declared` maps (platform, normalised account key) to a declared account id. A declared
    author keeps that id and gets no marker. A missing mission key (no encryption key configured)
    makes every undeclared known author UNAVAILABLE.
    """
    name = _platform_name(platform)
    account_id, handles = _references(metadata if isinstance(metadata, Mapping) else {}, source_url)
    if account_id is None and not handles:
        return AuthorAssignment(AuthorState.UNKNOWN)
    for candidate in ([account_id] if account_id is not None else []) + handles:
        if declared:
            declared_id = declared.get((name, candidate.lower()))
            if declared_id is not None:
                return AuthorAssignment(AuthorState.DECLARED, declared_account_id=declared_id)
    if mission_key is None:
        return AuthorAssignment(AuthorState.UNAVAILABLE)
    reference = f"{name}:{account_id if account_id is not None else handles[0]}"
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


def author_concentration_by_channel(signals: Iterable[Any]) -> Dict[str, "AuthorConcentration"]:
    """Concentration per platform for signals read back with their author facts.

    A signal with no fact -- a row stored before migration 031 -- counts as unknown, so legacy
    identity is never used to merge voices.
    """
    grouped: Dict[str, List[AuthorAssignment]] = {}
    for signal in signals:
        channel = _platform_name(getattr(signal, "platform", None))
        assignment = getattr(signal, "author_assignment", None) or AuthorAssignment(AuthorState.UNKNOWN)
        grouped.setdefault(channel, []).append(assignment)
    return {channel: AuthorConcentration.from_assignments(items) for channel, items in grouped.items()}


__all__: List[str] = [
    "AUTHOR_FIELD_KEYS",
    "AuthorAssignment",
    "AuthorConcentration",
    "AuthorState",
    "DeclaredAccount",
    "account_in_link",
    "assign_author",
    "author_concentration_by_channel",
    "author_identity_violation",
    "author_marker",
    "declarable_account_key",
    "declared_accounts_at",
    "has_handle_segment",
    "scrub_handle_links",
    "normalise_account_key",
    "strip_author_identity",
]
