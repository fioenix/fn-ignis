"""What makes two sightings the same external object.

One resolver, called by three callers that must never disagree: the reconciliation audit, the
backfill it gates, and the live write path. A second copy of this mapping is not a duplicated
constant, it is a second definition of identity -- the audit would then be measuring a corpus the
writer no longer produces, and the digests it publishes would stop meaning anything.

The identity is the platform plus the object namespace plus the platform's own identifier. How
that identifier was found is recorded separately, in identity_source, and takes no part in the
key: the same YouTube video reached the corpus once with video_id in its metadata and once
resolvable only from its URL, and keying on the route filed it as two objects three times.

A title is deliberately not part of identity. Ten URLs in the corpus report two different titles,
which makes a title something observed about a source rather than part of what it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit, urlunsplit

# The object namespace each connector's identifier points into. Two routes into one namespace
# describe one object, so both carry the same kind here. These kind names are ours; the field
# names and URL shapes they are read from are third-party and matched verbatim.
KIND_VIDEO = "video"
KIND_TAG = "tag"
KIND_POST = "post"
KIND_REEL = "reel"
KIND_KEYWORD = "keyword"
KIND_URL = "url"

# Metadata fields, in the order they are tried. The connector recorded the platform's identifier
# here, so it is preferred over anything parsed back out of a URL.
METADATA_KEYS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "youtube": (("video_id", KIND_VIDEO),),
    "tiktok": (("item_id", KIND_VIDEO), ("hashtag", KIND_TAG)),
    "threads": (("post_id", KIND_POST),),
    "reels": (("reel_id", KIND_REEL),),
    # Google Trends has no object id: the trend keyword is the object. A probe keyword is the same
    # keyword reached by a different mechanism, and the mechanism is recorded per observation.
    "google": (("keyword", KIND_KEYWORD), ("probe_keyword", KIND_KEYWORD)),
}

# URL shapes to recover an identifier from when metadata carries none, tried in order.
URL_PATTERNS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "youtube": (
        (r"[?&]v=([A-Za-z0-9_-]{6,})", KIND_VIDEO),
        (r"youtu\.be/([A-Za-z0-9_-]{6,})", KIND_VIDEO),
    ),
    "tiktok": ((r"/video/(\d+)", KIND_VIDEO), (r"/tag/([^/?#]+)", KIND_TAG)),
    "threads": ((r"/post/([A-Za-z0-9_-]+)", KIND_POST), (r"/t/([A-Za-z0-9_-]+)", KIND_POST)),
    # Instagram serves one shortcode space under both /reel/ and /p/, and /p/ on a reel's
    # shortcode redirects to the reel. One namespace, named after the connector that writes it.
    "reels": ((r"/reel/([A-Za-z0-9_-]+)", KIND_REEL), (r"/p/([A-Za-z0-9_-]+)", KIND_REEL)),
    "google": ((r"[?&]q=([^&]+)", KIND_KEYWORD),),
}

# Query parameters that never change which object a URL points at.
TRACKING_PARAMS = frozenset(
    {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
)

IDENTITY_FROM_METADATA = "metadata_external_id"
IDENTITY_FROM_URL = "url_external_id"
IDENTITY_FROM_NORMALIZED_URL = "normalized_url_fallback"
IDENTITY_UNRESOLVED = "unresolved"


def normalize_url(raw: Optional[str]) -> str:
    """Drop the parts of a URL that never distinguish two objects."""
    if not raw:
        return ""
    parts = urlsplit(raw.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = "&".join(
        f"{k}={v}" for k, v in sorted(parse_qsl(parts.query)) if k not in TRACKING_PARAMS
    )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


@dataclass(frozen=True)
class SourceIdentity:
    """One canonical external object.

    external_id carries its namespace, as "<kind>:<value>". The namespace has to be inside the
    key rather than beside it: on TikTok a hashtag and a video are different objects on one
    platform, so a tag literally named "12345" and item 12345 must not become one row. Keeping
    them in one column is what lets UNIQUE(platform, external_id) be the whole identity.
    """

    platform: str
    external_id: str
    identity_source: str

    @property
    def canonical_identity(self) -> str:
        """The identity as one comparable string, for digests and for grouping."""
        return f"{self.platform}:{self.external_id}"


def resolve_source_identity(
    platform: str, source_url: Optional[str], metadata: Any
) -> Optional[SourceIdentity]:
    """The canonical source a sighting belongs to, or None when nothing identifies it."""
    meta = metadata if isinstance(metadata, dict) else {}
    for key, kind in METADATA_KEYS.get(platform, ()):
        value = meta.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return SourceIdentity(
                platform=platform,
                external_id=f"{kind}:{str(value).strip()}",
                identity_source=IDENTITY_FROM_METADATA,
            )

    for pattern, kind in URL_PATTERNS.get(platform, ()):
        match = re.search(pattern, source_url or "")
        if match:
            return SourceIdentity(
                platform=platform,
                external_id=f"{kind}:{match.group(1)}",
                identity_source=IDENTITY_FROM_URL,
            )

    normalized = normalize_url(source_url)
    if normalized:
        return SourceIdentity(
            platform=platform,
            external_id=f"{KIND_URL}:{normalized}",
            identity_source=IDENTITY_FROM_NORMALIZED_URL,
        )

    return None
