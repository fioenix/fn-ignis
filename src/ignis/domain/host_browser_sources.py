"""Immutable routing facts and compatibility policies for host-browser sources."""

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from urllib.parse import quote

from ignis.domain.source_identity import identity_free_source_url


@dataclass(frozen=True)
class HostBrowserSource:
    origin: str
    search_path: str
    transport: Literal["opener_post_message", "fragment_receive"]
    # What the extractor emits; the validator accepts the wider accepted_record_path (T003 review).
    record_path: str
    accepted_record_path: str
    canonical_path: str
    extractor_version: str
    platform: str
    sampling_ordering: str
    legacy_envelope: bool
    localized_attribution: bool
    validates_locale: bool
    measured_counters: bool
    # The content id encodes the publication second (Spec 025 FR-007); checked live before use.
    dates_from_content_id: bool = False
    display_name: str = ""
    # Locale-qualified attribution wording lives in this seed's `<source>_attribution_<locale>` domains.
    attribution_locale_seed: str = "038_tiktok_attribution_locales.sql"
    # A locale without observed wording yields no records: the caption field can name the poster.
    locale_requires_attribution: bool = False
    sample_note: str = "Bounded visible public video grid; window and counters unmeasured"

    def search_url(self, query: str) -> str:
        return self.origin + self.search_path + "?q=" + quote(query, safe="")

    def canonical_url(self, path: str, *, original_url: str | None = None) -> str | None:
        if self.legacy_envelope:
            return identity_free_source_url(self.platform, original_url or self.origin + path, {})
        return self.origin + self.canonical_path + re.fullmatch(self.accepted_record_path, path).group(1)


_SOURCES = MappingProxyType({
    "tiktok": HostBrowserSource(
        origin="https://www.tiktok.com", search_path="/search/video", transport="opener_post_message",
        record_path=r"^/@[A-Za-z0-9_.]+/video/[0-9]+$",
        accepted_record_path=r"/(?:@[A-Za-z0-9_.]+/video/|share/video/)[0-9]+",
        canonical_path="/share/video/", extractor_version="tiktok-public-grid-v4", platform="tiktok", display_name="TikTok",
        sampling_ordering="visible_grid", legacy_envelope=True, localized_attribution=True,
        validates_locale=False, measured_counters=False, dates_from_content_id=True,
    ),
    "threads": HostBrowserSource(
        origin="https://www.threads.com", search_path="/search", transport="fragment_receive",
        record_path=r"^/(?:@[A-Za-z0-9_.]+/post/|t/)[A-Za-z0-9_-]+(?:/media)?/?$",
        accepted_record_path=r"/(?:@[A-Za-z0-9_.]+/post/|t/)([A-Za-z0-9_-]+)(?:/media)?/?",
        canonical_path="/t/", extractor_version="threads-search-top-v2", platform="threads", display_name="Threads",
        sampling_ordering="top_visible_sample", legacy_envelope=False, localized_attribution=False,
        validates_locale=True, measured_counters=True,
    ),
    # T020 spike: Instagram drops window.opener on load, so the answer returns by fragment.
    "instagram": HostBrowserSource(
        origin="https://www.instagram.com", search_path="/explore/search/keyword/", transport="fragment_receive",
        record_path=r"^/(?:p|reel)/[A-Za-z0-9_-]+/?$",
        accepted_record_path=r"/(?:p|reel)/([A-Za-z0-9_-]+)/?",
        canonical_path="/p/", extractor_version="instagram-keyword-grid-v1", platform="reels",
        sampling_ordering="visible_grid", legacy_envelope=False, localized_attribution=True,
        validates_locale=True, measured_counters=False, display_name="Instagram",
        attribution_locale_seed="041_instagram_attribution.sql", locale_requires_attribution=True,
        sample_note="Bounded visible keyword grid captions; window, dates and counters unmeasured",
    ),
})


def get_source(source: str) -> HostBrowserSource:
    """Refuse unsupported sources rather than falling back to TikTok."""
    try:
        return _SOURCES[source]
    except KeyError:
        raise ValueError("Unsupported host search source") from None
