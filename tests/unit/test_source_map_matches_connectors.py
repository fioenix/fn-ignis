"""The source-map diagram must agree with what the connectors declare.

A capability label on a picture is read as fact. "Discovers topics" next to Threads told a reader
an untargeted pull returns subjects nobody seeded, when the registry routes that connector to
keyword probing instead -- so the diagram promised discovery the system never performs.

The expectation here is derived from the connector classes and the registry's own routing rule,
not from a second hand-written table. A table copied beside the diagram would drift from the code
in the same way the diagram did, and the test would then certify the copy rather than the system.
"""

import re
from pathlib import Path

import pytest

from ignis.application.ports.connector_port import IngressScope
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
from ignis.infrastructure.connectors.tiktok.creative_center_plugin import (
    TikTokCreativeCenterPlugin,
)
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin

SOURCE_MAP = Path(__file__).resolve().parents[2] / "docs" / "diagrams" / "ignis-source-map.html"

# The label the diagram uses for a connector whose untargeted feed can surface unseeded subjects.
DISCOVERY_LABEL = "discovers topics"
# The label for one that a public-market pass sends to keyword probing instead.
PROBE_LABEL = "keyword probe"

# Heading text in the diagram, mapped to the connector class it describes. This is the only
# hand-written part, and it is a naming link rather than a capability claim.
DIAGRAM_CARDS = {
    "Google Trends RSS": GoogleTrendsRssPlugin,
    "YouTube Data API": YouTubeDataPlugin,
    "Threads": ThreadsPlugin,
    "Instagram Reels": ReelsPlugin,
    "TikTok Creative Center": TikTokCreativeCenterPlugin,
    "TikTok video &amp; comments": TikTokPlugin,
}


def _build(plugin_class):
    try:
        return plugin_class()
    except TypeError:
        return plugin_class(api_key="")


def _discovers_on_a_public_pass(plugin) -> bool:
    """The registry's rule, read from the connector's own declarations.

    `build_connector_registry` sends a plugin to the keyword probe when its default feed belongs
    to the authenticated account, or when an untargeted pull returns a popularity chart rather
    than a question. Everything else can discover.
    """
    account_only = getattr(plugin, "default_feed_scope", IngressScope.PUBLIC_MARKET) == (
        IngressScope.OWN_PROFILE
    )
    yields_topics = getattr(plugin, "feed_yields_candidate_topics", True)
    return yields_topics and not account_only


def _card_body(heading: str) -> str:
    """The text of the diagram card under a heading, up to the next heading or band."""
    markup = SOURCE_MAP.read_text(encoding="utf-8")
    start = markup.find(f">{heading}<")
    assert start != -1, f"the source map has no card headed {heading!r}"
    following = [
        markup.find(f">{other}<", start + 1)
        for other in DIAGRAM_CARDS
        if markup.find(f">{other}<", start + 1) != -1
    ]
    end = min(following) if following else len(markup)
    return markup[start:end]


@pytest.mark.parametrize("heading,plugin_class", sorted(DIAGRAM_CARDS.items()))
def test_card_capability_label_matches_the_connector(heading, plugin_class):
    body = _card_body(heading)
    expected_discovery = _discovers_on_a_public_pass(_build(plugin_class))

    says_discovery = DISCOVERY_LABEL in body
    says_probe = PROBE_LABEL in body

    assert says_discovery or says_probe, (
        f"the {heading!r} card states neither {DISCOVERY_LABEL!r} nor {PROBE_LABEL!r}; a reader "
        "cannot tell what the connector contributes"
    )
    assert says_discovery == expected_discovery, (
        f"the {heading!r} card says {DISCOVERY_LABEL!r}={says_discovery}, but the connector "
        f"declares default_feed_scope and feed_yields_candidate_topics such that a public-market "
        f"pass would treat it as discovery={expected_discovery}. On a public pass the registry "
        "routes an account-only feed, or one that yields no candidate topics, to keyword probing."
    )


def test_diagram_defines_both_labels_for_the_reader():
    markup = SOURCE_MAP.read_text(encoding="utf-8")
    assert re.search(r"discovers topics.{0,200}(untargeted|unseeded|nobody seeded)", markup, re.S), (
        "the source map uses 'discovers topics' without defining it"
    )
    assert PROBE_LABEL in markup, (
        "the source map never uses 'keyword probe', so connectors routed there have no label"
    )
