"""Recognising content authored by the operator's own connected accounts.

Every authenticated connector can see two different surfaces: the public one that market
listening is about, and the account's own timeline. Signals from the second surface distort
demand analysis — the operator's own post is not market evidence — so they are identified here
and dropped unless the caller asked for them. The matching is deliberately pure and offline:
identities are supplied by the caller, and nothing in this module reaches for I/O.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Metadata keys a connector may use for the author of a signal.
AUTHOR_METADATA_KEYS = ("username", "author", "author_username", "creator", "handle", "owner")
# Metadata keys carrying a numeric or opaque account identifier.
ACCOUNT_ID_METADATA_KEYS = ("user_id", "author_id", "account_id", "owner_id", "creator_id")


@dataclass(frozen=True)
class SelfIdentity:
    """One connected account belonging to the operator."""

    platform: str
    account_id: Optional[str] = None
    username: Optional[str] = None
    source: str = "unknown"

    @property
    def normalized_username(self) -> Optional[str]:
        if not self.username:
            return None
        return self.username.strip().lstrip("@").lower() or None

    @property
    def normalized_account_id(self) -> Optional[str]:
        if self.account_id is None:
            return None
        return str(self.account_id).strip() or None

    @property
    def is_usable(self) -> bool:
        return bool(self.normalized_username or self.normalized_account_id)


def _platform_of(signal: Any) -> str:
    platform = getattr(signal, "platform", None)
    value = platform.value if hasattr(platform, "value") else platform
    return str(value or "").strip().lower()


def _metadata_of(signal: Any) -> Dict[str, Any]:
    metadata = getattr(signal, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _url_handles(url: str) -> List[str]:
    """Extract the account handles a post URL exposes.

    Covers the shapes the connectors actually produce: threads.net/@handle/post/...,
    tiktok.com/@handle/video/..., instagram.com/handle/p/... and instagram.com/reel/...
    """
    if not url:
        return []
    lowered = url.lower()
    handles = [h for h in re.findall(r"/@([a-z0-9._-]+)", lowered)]
    instagram = re.match(r"https?://(?:www\.)?instagram\.com/([a-z0-9._-]+)/(?:p|reel|tv)/", lowered)
    if instagram:
        handles.append(instagram.group(1))
    return handles


def is_self_authored(signal: Any, identities: Sequence[SelfIdentity]) -> bool:
    """True when the signal was authored by one of the operator's own accounts."""
    platform = _platform_of(signal)
    relevant = [i for i in identities if i.is_usable and (not i.platform or i.platform.strip().lower() == platform)]
    if not relevant:
        return False

    metadata = _metadata_of(signal)
    authors = {
        str(metadata[key]).strip().lstrip("@").lower()
        for key in AUTHOR_METADATA_KEYS
        if metadata.get(key) not in (None, "")
    }
    account_ids = {
        str(metadata[key]).strip()
        for key in ACCOUNT_ID_METADATA_KEYS
        if metadata.get(key) not in (None, "")
    }
    url_handles = set(_url_handles(str(getattr(signal, "source_url", "") or "")))

    for identity in relevant:
        username = identity.normalized_username
        if username and (username in authors or username in url_handles):
            return True
        account_id = identity.normalized_account_id
        if account_id and account_id in account_ids:
            return True
    return False


def partition_self_authored(
    signals: Iterable[Any],
    identities: Sequence[SelfIdentity],
) -> Tuple[List[Any], List[Any]]:
    """Split signals into (public, self-authored) without reordering either side."""
    public: List[Any] = []
    own: List[Any] = []
    for signal in signals:
        (own if is_self_authored(signal, identities) else public).append(signal)
    return public, own
