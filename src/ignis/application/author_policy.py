"""The author identity policy as a collection pass applies it (Spec 015).

One function, so the mission pass and anything that must reproduce it -- the parity check among
them -- strip identity the same way.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from ignis.domain.author_identity import (
    DeclaredAccount,
    assign_author,
    declared_accounts_at,
    strip_author_identity,
)
from ignis.domain.entities import TrendSignal
from ignis.domain.probe_provenance import PROBE_KEY_ALIASES
from ignis.domain.source_identity import identity_free_source_url
from ignis.infrastructure.security.pii_sanitizer import tokenise_mentions

# The requester's own query words, which also key a Google Trends source: never tokenised.
_QUERY_KEYS = frozenset(PROBE_KEY_ALIASES) | {"matched_keywords", "query"}


def _tokenise(value: Any, declared: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return tokenise_mentions(value, declared)
    if isinstance(value, Mapping):
        return {
            key: item if key in _QUERY_KEYS else _tokenise(item, declared)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_tokenise(item, declared) for item in value]
    return value


def apply_author_policy(
    signals: Iterable[TrendSignal],
    mission_key: Optional[bytes],
    *,
    declared_accounts: Sequence[DeclaredAccount] = (),
) -> None:
    """Classify each signal's author, then remove the identity, in place.

    The classification comes first because the marker needs the identity. A declared account
    counts only for content collected after its declaration. A link that names an account is
    replaced by an identity-free link, or dropped when none exists, and @mentions in the title
    and the metadata text become tokens.
    """
    for signal in signals:
        platform = signal.platform.value if hasattr(signal.platform, "value") else str(signal.platform)
        declared = declared_accounts_at(declared_accounts, signal.captured_at)
        signal.author_assignment = assign_author(
            signal.platform, signal.metadata, signal.source_url, mission_key, declared=declared
        )
        signal.source_url = identity_free_source_url(platform, signal.source_url, signal.metadata)
        # Handles written inside the content become tokens: a declared account's handle names
        # its declaration, every other handle becomes @[user] (research R7).
        mentions = {key: account_id for (account_platform, key), account_id in declared.items() if account_platform == platform}
        signal.raw_title = tokenise_mentions(signal.raw_title, mentions)
        signal.metadata = _tokenise(strip_author_identity(signal.metadata), mentions)
