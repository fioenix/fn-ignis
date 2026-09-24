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
from urllib.parse import parse_qsl, unquote_plus, urlsplit, urlunsplit

# The object namespace each connector's identifier points into. Two routes into one namespace
# describe one object, so both carry the same kind here. These kind names are ours; the field
# names and URL shapes they are read from are third-party and matched verbatim.
KIND_VIDEO = "video"
KIND_TAG = "tag"
KIND_POST = "post"
KIND_REEL = "reel"
KIND_KEYWORD = "keyword"
KIND_URL = "url"

# Threads and Instagram address one object by two values that are not translations of each other:
# the Graph API reports a numeric primary key, a permalink carries a shortcode, and there is no
# arithmetic from one to the other. They get their own namespaces rather than being filed
# together, because "post:<value>" would assert the values are comparable -- and an all-digit
# shortcode would then collide with somebody else's primary key. Two rows for one object is a gap
# we can measure; a wrong merge is silent and unrecoverable.
KIND_POST_SHORTCODE = "post_shortcode"
KIND_REEL_SHORTCODE = "reel_shortcode"

# What closes that gap, and the only thing that may: one connector record carrying both values.
# Every Threads and Reels emission path does -- the Graph responses ask for `id` and `permalink`
# together, and the browser payloads carry `pk` beside `code` -- so the record itself witnesses
# that one primary key and one shortcode are one object. String equality between the two spaces
# is still not evidence, and never becomes evidence.
#
# The pair is ordered: the platform's own primary key is canonical and the shortcode points at
# it. Only the alias side is ever redirected, so a ledger row can never make one canonical object
# resolve to another, and there are no chains to keep consistent.
ALIASABLE_NAMESPACES: Dict[str, Tuple[str, str]] = {
    "threads": (KIND_POST, KIND_POST_SHORTCODE),
    "reels": (KIND_REEL, KIND_REEL_SHORTCODE),
}

# How an alias came to be believed. Recorded on the ledger row rather than on the observation:
# the route that resolved a sighting is still the URL, and which object that URL belongs to is
# the ledger's fact about two identifiers, not the sighting's fact about itself.
ALIAS_FROM_CO_WITNESS = "connector_record_co_witness"

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
    "threads": (
        (r"/post/([A-Za-z0-9_-]+)", KIND_POST_SHORTCODE),
        (r"/t/([A-Za-z0-9_-]+)", KIND_POST_SHORTCODE),
    ),
    # Instagram serves one shortcode space under both /reel/ and /p/, and /p/ on a reel's
    # shortcode redirects to the reel. One namespace, named after the connector that writes it.
    "reels": (
        (r"/reel/([A-Za-z0-9_-]+)", KIND_REEL_SHORTCODE),
        (r"/p/([A-Za-z0-9_-]+)", KIND_REEL_SHORTCODE),
    ),
    "google": ((r"[?&]q=([^&]+)", KIND_KEYWORD),),
}

# Query parameters that never change which object a URL points at.
TRACKING_PARAMS = frozenset(
    {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
)

def _canonical_value(kind: str, raw: str) -> str:
    """The identifier itself, freed of whatever the route did to it.

    Only the route differs here, never the object. Creative Center reports a hashtag as "#aothun"
    in metadata and as /tag/aothun in the URL; Google Trends percent-encodes the keyword into the
    explore URL that it also carries verbatim in metadata. Canonicalising the value is what stops
    one object from occupying one row per route.
    """
    value = raw.strip()
    if kind == KIND_TAG:
        return value.lstrip("#").strip()
    if kind == KIND_KEYWORD:
        return unquote_plus(value).strip()
    return value


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


def _from_metadata(platform: str, metadata: Any) -> Optional[SourceIdentity]:
    """The identity the connector's own identifier gives, if it wrote one."""
    meta = metadata if isinstance(metadata, dict) else {}
    for key, kind in METADATA_KEYS.get(platform, ()):
        value = meta.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            canonical = _canonical_value(kind, str(value))
            if canonical:
                return SourceIdentity(
                    platform=platform,
                    external_id=f"{kind}:{canonical}",
                    identity_source=IDENTITY_FROM_METADATA,
                )
    return None


def _from_url(platform: str, source_url: Optional[str]) -> Optional[SourceIdentity]:
    """The identity recoverable from the URL shape alone, ignoring metadata entirely."""
    for pattern, kind in URL_PATTERNS.get(platform, ()):
        match = re.search(pattern, source_url or "")
        if match:
            canonical = _canonical_value(kind, match.group(1))
            if canonical:
                return SourceIdentity(
                    platform=platform,
                    external_id=f"{kind}:{canonical}",
                    identity_source=IDENTITY_FROM_URL,
                )
    return None


def resolve_source_identity(
    platform: str, source_url: Optional[str], metadata: Any
) -> Optional[SourceIdentity]:
    """The canonical source a sighting belongs to, or None when nothing identifies it."""
    from_metadata = _from_metadata(platform, metadata)
    if from_metadata is not None:
        return from_metadata

    from_url = _from_url(platform, source_url)
    if from_url is not None:
        return from_url

    normalized = normalize_url(source_url)
    if normalized:
        return SourceIdentity(
            platform=platform,
            external_id=f"{KIND_URL}:{normalized}",
            identity_source=IDENTITY_FROM_NORMALIZED_URL,
        )

    return None


@dataclass(frozen=True)
class IdentityAlias:
    """One shortcode proven to name one primary key, and what proved it.

    Directed and single-hop by construction: alias_external_id always sits in the platform's
    shortcode namespace and canonical_external_id in its primary-key namespace, so a ledger built
    only from these can never point a canonical object at another canonical object.
    """

    platform: str
    alias_external_id: str
    canonical_external_id: str
    witnessed_by: str


def alias_namespace_prefix(platform: str) -> Optional[str]:
    """The external_id prefix a ledger lookup is allowed to redirect, or None for that platform.

    The write path gates on this so that only a shortcode is ever resolved through the ledger. A
    primary key is canonical and stays canonical, whatever rows the table happens to contain.
    """
    pair = ALIASABLE_NAMESPACES.get(platform)
    return None if pair is None else f"{pair[1]}:"


def resolve_identity_alias(
    platform: str, source_url: Optional[str], metadata: Any
) -> Optional[IdentityAlias]:
    """The alias one connector record proves, or None when the record proves nothing.

    Both halves have to come from the same record, and each has to land in the namespace the
    platform declared for it. Half the evidence is not evidence: a metadata-only record links its
    primary key to no shortcode, and a permalink whose path yields no shortcode -- an explore
    page, a profile -- is not a shortcode that happens to be missing.
    """
    pair = ALIASABLE_NAMESPACES.get(platform)
    if pair is None:
        return None
    canonical_kind, alias_kind = pair

    from_metadata = _from_metadata(platform, metadata)
    from_url = _from_url(platform, source_url)
    if from_metadata is None or from_url is None:
        return None
    if not from_metadata.external_id.startswith(f"{canonical_kind}:"):
        return None
    if not from_url.external_id.startswith(f"{alias_kind}:"):
        return None

    return IdentityAlias(
        platform=platform,
        alias_external_id=from_url.external_id,
        canonical_external_id=from_metadata.external_id,
        witnessed_by=ALIAS_FROM_CO_WITNESS,
    )
