"""The author identity policy as a collection pass applies it (Spec 015).

One function, so the mission pass and anything that must reproduce it -- the parity check among
them -- strip identity the same way.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Tuple

from ignis.domain.author_identity import assign_author, strip_author_identity
from ignis.domain.entities import TrendSignal
from ignis.domain.source_identity import identity_free_source_url


def apply_author_policy(
    signals: Iterable[TrendSignal],
    mission_key: Optional[bytes],
    *,
    declared: Optional[Mapping[Tuple[str, str], str]] = None,
) -> None:
    """Classify each signal's author, then remove the identity, in place.

    The classification comes first because the marker needs the identity. A link that names an
    account is replaced by an identity-free link, or dropped when none exists.
    """
    for signal in signals:
        platform = signal.platform.value if hasattr(signal.platform, "value") else str(signal.platform)
        signal.author_assignment = assign_author(
            signal.platform, signal.metadata, signal.source_url, mission_key, declared=declared
        )
        signal.source_url = identity_free_source_url(platform, signal.source_url, signal.metadata)
        signal.metadata = strip_author_identity(signal.metadata)
