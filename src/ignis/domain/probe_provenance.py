"""Which query brought a signal in, read back from whatever the connector called it.

A signal that arrived through a keyword probe carries the strongest available evidence of what
it is about: the query that returned it. Clustering by title-token overlap cannot recover that,
because a video title and a forum post about one subject rarely share enough words.

Connectors settled on three different metadata keys for the same fact. Rather than rewrite every
connector, the domain reads all three. These are metadata field names, not domain vocabulary --
they describe the shape of the payload, so they belong in code rather than in `market_lexicons`.
"""

from typing import Optional

from ignis.domain.entities import TrendSignal

PROBE_KEY_ALIASES = ("keyword", "matched_keyword", "probe_keyword")


def probe_keyword_of(signal: TrendSignal) -> Optional[str]:
    """Return the normalised probe keyword, or None when the signal came from a feed.

    Normalising to casefolded, whitespace-collapsed text is what lets two connectors that
    received the same keyword agree they did, even when one echoes back the display form.
    """
    metadata = signal.metadata or {}
    for key in PROBE_KEY_ALIASES:
        raw = metadata.get(key)
        if isinstance(raw, str) and raw.strip():
            return " ".join(raw.split()).casefold()
    return None
