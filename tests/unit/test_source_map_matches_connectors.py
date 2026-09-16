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

# The three routes a public-market pass can take a connector down. The diagram carries a label for
# the first two; the third has none because no current connector falls into it, and a connector
# that lands there while wearing a label is exactly what this contract must catch.
ROUTE_DISCOVERY = "discovery"
ROUTE_PROBE = "keyword probe"
ROUTE_SKIPPED = "skipped"

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


def _public_pass_route(plugin) -> str:
    """The registry's rule, read from the connector's own declarations.

    `fetch_from_all` refuses a connector's untargeted pull on a public pass for two reasons: the
    feed belongs to the authenticated account, or it is a popularity chart rather than a question.
    Refusing the feed is not the same as probing instead -- the probe only happens when the
    connector implements a real keyword search. Without one it is skipped and contributes nothing,
    which is the third state the earlier version of this contract folded into "keyword probe".
    """
    account_only = getattr(plugin, "default_feed_scope", IngressScope.PUBLIC_MARKET) == (
        IngressScope.OWN_PROFILE
    )
    yields_topics = getattr(plugin, "feed_yields_candidate_topics", True)
    if yields_topics and not account_only:
        return ROUTE_DISCOVERY
    return ROUTE_PROBE if plugin.supports_search else ROUTE_SKIPPED


# Where the cards stop. Without this the last card's body ran to the end of the file and absorbed
# the legend, which defines both labels -- so that card was compared against the legend's wording
# rather than its own, and could not fail.
LEGEND_MARKER = "================= legend ================="


def _card_body(heading: str) -> str:
    """The text of the diagram card under a heading, up to the next heading or the legend."""
    markup = SOURCE_MAP.read_text(encoding="utf-8")
    start = markup.find(f">{heading}<")
    assert start != -1, f"the source map has no card headed {heading!r}"
    legend = markup.find(LEGEND_MARKER, start + 1)
    assert legend != -1, "the source map has no legend block to bound the last card"
    following = [
        markup.find(f">{other}<", start + 1)
        for other in DIAGRAM_CARDS
        if markup.find(f">{other}<", start + 1) != -1
    ] + [legend]
    return markup[start: min(following)]


@pytest.mark.parametrize("heading,plugin_class", sorted(DIAGRAM_CARDS.items()))
def test_card_capability_label_matches_the_connector(heading, plugin_class):
    body = _card_body(heading)
    route = _public_pass_route(_build(plugin_class))

    says_discovery = DISCOVERY_LABEL in body
    says_probe = PROBE_LABEL in body

    assert says_discovery or says_probe, (
        f"the {heading!r} card states neither {DISCOVERY_LABEL!r} nor {PROBE_LABEL!r}; a reader "
        "cannot tell what the connector contributes"
    )
    assert not (says_discovery and says_probe), (
        f"the {heading!r} card carries both labels, so it promises two different routes"
    )

    if route == ROUTE_SKIPPED:
        pytest.fail(
            f"the {heading!r} card promises "
            f"{DISCOVERY_LABEL if says_discovery else PROBE_LABEL!r}, but the connector declares "
            "an account-scoped or chart-only feed and implements no keyword search, so a "
            "public-market pass skips it and it contributes nothing. Either restore its search "
            "probe or give the diagram a label for a connector the public pass cannot use."
        )

    expected = ROUTE_DISCOVERY if says_discovery else ROUTE_PROBE
    assert route == expected, (
        f"the {heading!r} card reads {expected!r}, but the connector's declarations route it to "
        f"{route!r} on a public-market pass. The registry sends an account-only feed, or one that "
        "yields no candidate topics, to the keyword probe -- and only when the connector "
        "implements a keyword search of its own."
    )


def test_diagram_defines_both_labels_for_the_reader():
    markup = SOURCE_MAP.read_text(encoding="utf-8")
    assert re.search(r"discovers topics.{0,200}(untargeted|unseeded|nobody seeded)", markup, re.S), (
        "the source map uses 'discovers topics' without defining it"
    )
    assert PROBE_LABEL in markup, (
        "the source map never uses 'keyword probe', so connectors routed there have no label"
    )
