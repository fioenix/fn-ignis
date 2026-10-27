"""Execute the packaged Threads extractor over synthetic G2-shaped HTML trees."""
import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/threads_host_search"
EXTRACTOR = ROOT / "src/ignis/infrastructure/connectors/host_browser/threads_search.js"


class TreeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = {"tag": "fixture", "children": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict((k, v or "") for k, v in attrs), "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in {"img", "br", "input", "meta", "link"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if len(self.stack) > 1 and self.stack[-1]["tag"] == tag:
            self.stack.pop()

    def handle_data(self, data):
        self.stack[-1]["children"].append({"text": data})


def extract(frames=None, **overrides):
    assert EXTRACTOR.is_file(), "Threads extractor must be packaged"
    node = shutil.which("node")
    assert node, "Node is required for deterministic DOM contract execution"
    frames = frames or [(FIXTURES / "cards.html").read_text()]
    trees = []
    for frame in frames:
        parser = TreeParser()
        parser.feed(frame)
        trees.append(parser.root)
    payload = dict(url="https://www.threads.com/search?q=synthetic%20query", frames=trees, limit=3)
    payload.update(overrides)
    result = subprocess.run([node, str(FIXTURES / "dom_probe.js"), str(EXTRACTOR), json.dumps(payload)],
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_body_isolated_from_header_sidebar_alt_and_actions_with_exact_clock_and_counters():
    result = extract()
    assert result["status"] == "HEALTHY" and result["locale"] == "en"
    assert len(result["records"]) == 1
    row = result["records"][0]
    assert row["excerpt"] == "First body line\nSecond body line #synthetic"
    assert all(value not in row["excerpt"] for value in ("Sentinel", "Identity", "Translate", "1 / 2", "1.4K"))
    assert row["published_at"] == "2026-10-27T01:02:03.123456Z"
    assert row["counters"][0] == dict(kind="likes", unit="count", raw_display="1.4K", value=1400, precision="rounded")
    assert row["counters"][2]["value"] is None and row["counters"][3]["kind"] == "shares"
    assert result["empty_state_visible"] is False


@pytest.mark.parametrize("url", ["https://www.threads.com/search?q=synthetic%20query&filter=recent",
    "https://threads.net/search?q=synthetic%20query", "https://www.threads.com/@synthetic/post/ID",
    "https://www.threads.com/search?q=wrong", "https://www.threads.com/search?q=synthetic%20query#x"])
def test_wrong_origin_route_filter_or_query_is_not_an_evidence_surface(url):
    result = extract(url=url)
    assert result["status"] == "DEGRADED" and result["records"] == []


@pytest.mark.parametrize("frame", ["shell", "challenge", "hidden", "alt-only", "quote", "bad-clock"])
def test_unproved_shell_hidden_alt_only_nested_quote_or_bad_time_never_becomes_empty(frame):
    cards = (FIXTURES / "cards.html").read_text()
    if frame in {"shell", "challenge"}:
        html = (FIXTURES / "shell.html").read_text().replace("Loading...", "Checkpoint" if frame == "challenge" else "Loading...")
    elif frame == "hidden":
        html = cards.replace("<main>", '<main hidden="">')
    elif frame == "alt-only":
        html = cards.replace("First body line<br>Second body line <span>#synthetic</span>", "")
    elif frame == "bad-clock":
        html = cards.replace("2026-10-27T01:02:03.123456Z", "not-an-exact-time")
    else:
        inner = cards.split("<main>", 1)[1].split("</main>", 1)[0].replace("Synthetic020A", "Quoted020")
        html = cards.replace("First body line<br>Second body line <span>#synthetic</span>", inner)
    result = extract([html])
    assert result["status"] == "DEGRADED" and result["records"] == []
    assert result["empty_state_visible"] is False


def test_virtualized_removals_keep_a_bounded_unique_sample_across_explicit_reads():
    first = (FIXTURES / "cards.html").read_text()
    second = first.replace("Synthetic020A", "Synthetic020B")
    third = first.replace("Synthetic020A", "Synthetic020C")
    result = extract([first, second, third], limit=2)
    assert len(result["records"]) == 2
    assert result["records"][0]["source_url"].endswith("Synthetic020A")
    assert result["records"][1]["source_url"].endswith("Synthetic020B")


def test_unsupported_locale_is_degraded_without_guessing_labels():
    result = extract(locale="vi")
    assert result["status"] == "DEGRADED" and result["records"] == []


def test_absolute_profile_urls_and_header_text_never_join_the_body():
    cards = (FIXTURES / "cards.html").read_text().replace('href="/@synthetic.header"',
        'href="https://www.threads.com/@synthetic.header"').replace('Synthetic Header</a>',
        'Synthetic Header</a><span>Another Header Identity</span>')
    result = extract([cards])
    assert result["records"][0]["excerpt"] == "First body line\nSecond body line #synthetic"


@pytest.mark.parametrize("depth", [1, 3])
def test_timestamp_wrapper_depth_does_not_change_header_body_ownership(depth):
    cards = (FIXTURES / "cards.html").read_text().replace('Synthetic Header</a>',
        'Synthetic Header</a><span>Another Header Identity</span>')
    start = '<a href="https://www.threads.com/@synthetic.header/post/Synthetic020A">'
    end = '</time></a>'
    cards = cards.replace(start, '<span>' * depth + start).replace(end, end + '</span>' * depth)
    result = extract([cards])
    assert result["records"][0]["excerpt"] == "First body line\nSecond body line #synthetic"
