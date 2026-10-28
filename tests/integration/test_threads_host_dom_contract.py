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
    payload['action_labels'] = {
        'en': {'likes': 'Like', 'replies': 'Reply', 'reposts': 'Repost', 'shares': 'Share'},
        'vi': {'likes': 'Thích', 'replies': 'Trả lời', 'reposts': 'Đăng lại', 'shares': 'Chia sẻ'},
    }
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
    result = extract(locale="")
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


def test_review_malformed_anchor_is_skipped_without_losing_valid_posts():
    cards = (FIXTURES / "cards.html").read_text()
    malformed = '<a href="http://[invalid">Malformed link</a>'
    cards = cards.replace('First body line<br>', malformed + 'First body line<br>')
    result = extract([cards])
    assert result["status"] == "HEALTHY"
    assert len(result["records"]) == 1
    assert "First body line" in result["records"][0]["excerpt"]


def test_vietnamese_structure_and_label_prefixed_counters_match_english():
    vi = extract([(FIXTURES / "cards.vi.html").read_text()], locale="vi-VN")
    en = extract()
    assert vi["locale"] == "vi" and vi["status"] == "HEALTHY"
    assert len(vi["records"]) == len(en["records"]) == 1
    assert vi["records"][0]["excerpt"] == en["records"][0]["excerpt"]
    for left, right in zip(vi["records"][0]["counters"], en["records"][0]["counters"], strict=True):
        assert {k: v for k, v in left.items() if k != "raw_display"} == {
            k: v for k, v in right.items() if k != "raw_display"}
    assert vi["records"][0]["counters"][0]["raw_display"] == "Thích1,4K"
    assert vi["records"][0]["counters"][2]["raw_display"] == "Đăng lại"


def test_unknown_locale_collects_structure_without_positional_measurements():
    result = extract([(FIXTURES / "cards.vi.html").read_text()], locale="th")
    assert result["locale"] == "th" and result["status"] == "HEALTHY"
    assert len(result["records"]) == 1
    assert len(result["records"][0]["counters"]) == 4
    assert all(c["value"] is None and c["precision"] == "unknown" for c in result["records"][0]["counters"])


@pytest.mark.parametrize("display,value,precision", [
    ("1,4K", 1400, "rounded"), ("4.1K", 4100, "rounded"), ("1,25M", 1250000, "rounded"),
    ("1K", 1000, "rounded"), ("1.2345K", 1235, "rounded"), ("466", 466, "exact"),
    ("", None, "unknown"), ("1,400", None, "unknown"), ("9" * 40 + "M", None, "unknown"),
])
def test_counter_label_is_removed_only_for_parsing(display, value, precision):
    html = (FIXTURES / "cards.vi.html").read_text().replace("Thích1,4K", "Thích" + display)
    result = extract([html], locale="vi")
    assert result["records"][0]["counters"][0] == dict(
        kind="likes", unit="count", raw_display="Thích" + display, value=value, precision=precision)


def test_action_order_cannot_assign_counter_kinds():
    html = (FIXTURES / "cards.vi.html").read_text().replace("<title>Thích</title>", "<title>Other</title>")
    counters = extract([html], locale="vi")["records"][0]["counters"]
    assert counters[0]["precision"] == "unknown" and counters[0]["value"] is None
    assert counters[1]["kind"] == "replies" and counters[1]["value"] == 9


def test_prepare_injects_seeded_labels_into_the_packaged_extractor_without_transport_changes(tmp_path, monkeypatch):
    from ignis.application.use_cases import host_browser_search as module
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay
    captured = []
    class CaptureRelay(NoSocketRelay):
        def __init__(self, request, extractor, *args):
            super().__init__()
            captured.append(extractor)
    monkeypatch.setattr(module, "LoopbackRelay", CaptureRelay)
    service = module.HostBrowserSearchService()
    try:
        service.prepare("task", "session", ["synthetic query"], 3, 60, True, source="threads")
        script = tmp_path / "prepared.js"
        script.write_text(captured[0])
        monkeypatch.setattr(__import__(__name__, fromlist=["EXTRACTOR"]), "EXTRACTOR", script)
        result = extract([(FIXTURES / "cards.vi.html").read_text()], locale="vi", action_labels={})
        assert result["records"][0]["counters"][0]["value"] == 1400
    finally:
        service.close()


@pytest.mark.parametrize("clock", ["2099-01-01T00:00:00Z", "2026-10-27T01:02:03"])
def test_future_and_zoneless_timestamps_are_dropped_in_vietnamese(clock):
    html = (FIXTURES / "cards.vi.html").read_text().replace("2026-10-27T01:02:03.123456Z", clock)
    result = extract([html], locale="vi")
    assert result["records"] == [] and result["status"] == "DEGRADED"


@pytest.mark.asyncio
@pytest.mark.parametrize("title,display", [("Me gusta", "Me GuStA1,4K"), ("ME GUSTA", "me gusta1,4K")])
async def test_operator_registered_lowercase_labels_match_titles_and_prefixes(tmp_path, monkeypatch, title, display):
    from ignis.interfaces.mcp import server
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.connectors.host_browser.action_labels import action_labels_from_rows
    from ignis.infrastructure.connectors.host_browser.validator import _counters
    from ignis.domain.host_browser_search import HostPublicRecord

    repo = SqliteTrendRepository(str(tmp_path / "labels.db"))
    monkeypatch.setattr(server, "get_components", lambda: {"repository": repo})
    try:
        response = json.loads(await server.handle_register_domain_lexicon(
            "threads_action_labels_es", ["Me gusta"], "likes"))
        assert response["status"] == "SUCCESS"
        labels = action_labels_from_rows(await repo.get_domain_lexicons("threads_action_labels_es"))
        assert labels == {"es": {"likes": "me gusta"}}
        html = (FIXTURES / "cards.vi.html").read_text().replace(
            "<title>Thích</title>", "<title>" + title + "</title>").replace("Thích1,4K", display)
        result = extract([html], locale="es", action_labels=labels)
        counters = result["records"][0]["counters"]
        assert counters[0] == dict(kind="likes", unit="count", raw_display=display, value=1400, precision="rounded")
        record = HostPublicRecord.model_validate(dict(source_url=None, excerpt="Synthetic body", counters=counters))
        assert _counters(record.counters, labels["es"]) == counters
    finally:
        await repo.close()


def test_t058_oversized_excerpt_is_bounded_without_losing_other_cards():
    html = (FIXTURES / "cards.html").read_text().replace("First body line", "x" * 2200)
    result = extract([html])
    assert result["status"] == "HEALTHY"
    assert len(result["records"][0]["excerpt"]) == 2000
