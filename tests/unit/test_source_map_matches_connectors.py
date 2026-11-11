"""Keep the historical source-map legend readable after discovery retirement."""

import re
from pathlib import Path

SOURCE_MAP = Path(__file__).resolve().parents[2] / "docs" / "diagrams" / "ignis-source-map.html"
PROBE_LABEL = "keyword probe"


def test_diagram_defines_both_labels_for_the_reader():
    markup = SOURCE_MAP.read_text(encoding="utf-8")
    assert re.search(r"discovers topics.{0,200}(untargeted|unseeded|nobody seeded)", markup, re.S), (
        "the source map uses 'discovers topics' without defining it"
    )
    assert PROBE_LABEL in markup, (
        "the source map never uses 'keyword probe', so connectors routed there have no label"
    )
