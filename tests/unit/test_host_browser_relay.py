"""Exercise the real loopback transport, not a mocked browser or server."""

import importlib
import http.client
import json
import socket
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest


def relay_type():
    try:
        return importlib.import_module(
            "ignis.infrastructure.connectors.host_browser.relay"
        ).LoopbackRelay
    except ModuleNotFoundError:
        pytest.fail("The task-bound loopback relay is not implemented")


def post(relay, payload, *, origin=None, host=None, path=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    headers["Origin"] = origin if origin is not None else relay.origin
    if host is not None:
        headers["Host"] = host
    request = Request(
        path or relay.url,
        data=urlencode({"payload": json.dumps(payload)}).encode(),
        headers=headers,
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, response.read(), dict(response.headers)
    except HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def test_real_form_roundtrip_passes_json_without_transcript_reconstruction():
    seen = []
    relay = relay_type()(
        request={"query": "túi đi làm"},
        extractor="arg => ({query: arg.query})",
        receive=lambda answer: seen.append(answer) or {"status": "STAGED"},
        lifetime_seconds=10,
    )
    try:
        with urlopen(relay.url, timeout=3) as response:
            page = response.read().decode()
            assert response.headers["Cache-Control"] == "no-store"
            # Native same-origin forms must retain Origin while external referrers stay hidden.
            assert response.headers["Referrer-Policy"] == "same-origin"
            assert "form-action 'self'" in response.headers["Content-Security-Policy"]
        assert "túi đi làm" in page
        status, body, headers = post(relay, {"records": [{"excerpt": "Túi <b>đẹp</b>"}]})
        assert status == 200
        assert seen == [{"records": [{"excerpt": "Túi <b>đẹp</b>"}]}]
        assert b"STAGED" in body
        assert "Access-Control-Allow-Origin" not in headers
        assert relay.wait_closed(2)
        port = urlsplit(relay.url).port
        with socket.socket() as connection:
            assert connection.connect_ex(("127.0.0.1", port)) != 0
    finally:
        relay.close()


@pytest.mark.parametrize("origin,host", [
    ("https://www.tiktok.com", None),
    ("null", None),
    ("", None),
    (None, "attacker.example"),
])
def test_cross_origin_and_dns_rebinding_requests_cannot_stage(origin, host):
    seen = []
    relay = relay_type()({}, "arg => arg", lambda answer: seen.append(answer), 10)
    try:
        assert post(relay, {}, origin=origin, host=host)[0] == 403
        assert seen == []
    finally:
        relay.close()


def test_callback_failure_closes_listener_without_logging_or_echoing_payload(capsys):
    def fail(answer):
        raise RuntimeError("SENSITIVE_FIXTURE_MARKER")
    relay = relay_type()({}, "arg => arg", fail, 10)
    try:
        status, body, _ = post(relay, {})
        assert status == 500
        assert b"SENSITIVE_FIXTURE_MARKER" not in body
        assert relay.wait_closed(2)
        assert "SENSITIVE_FIXTURE_MARKER" not in capsys.readouterr().err
    finally:
        relay.close()


def test_unknown_path_and_oversized_body_cannot_stage():
    seen = []
    relay = relay_type()({}, "arg => arg", lambda answer: seen.append(answer), 10)
    try:
        assert post(relay, {}, path=relay.origin + "/wrong/")[0] == 404
        # The server refuses length before reading; sending the body can race its close.
        connection = http.client.HTTPConnection("127.0.0.1", urlsplit(relay.url).port)
        connection.putrequest("POST", urlsplit(relay.url).path)
        connection.putheader("Origin", relay.origin)
        connection.putheader("Content-Type", "application/x-www-form-urlencoded")
        connection.putheader("Content-Length", str(1024 * 1024 + 1))
        connection.endheaders()
        assert connection.getresponse().status == 413
        connection.close()
        assert seen == []
    finally:
        relay.close()


def test_cancel_and_expiry_close_listener_without_receiving_data():
    seen = []
    relay = relay_type()({}, "arg => arg", lambda answer: seen.append(answer), 0.1)
    assert relay.wait_closed(2)
    assert seen == []
    relay.close()
    relay = relay_type()({}, "arg => arg", lambda answer: seen.append(answer), 10)
    relay.close()
    assert relay.wait_closed(2)


def test_html_escapes_task_content_and_does_not_load_external_resources():
    relay = relay_type()({"query": "</textarea><script>alert(1)</script>"},
                         "arg => arg", lambda answer: {}, 10)
    try:
        with urlopen(relay.url, timeout=3) as response:
            page = response.read().decode()
        assert "</textarea><script>alert(1)</script>" not in page
        assert "https://fonts.googleapis.com" not in page
        assert "&lt;/textarea&gt;" in page
    finally:
        relay.close()


SEARCH_FIXTURE = (
    '<html><body><div data-e2e="search_top-item">'
    '<a href="https://www.tiktok.com/@fixture/video/7417820067028536584">'
    '<img alt="Túi đi làm siêu gọn do Fixture Poster tạo với bản nhạc gốc" width="10" height="10" '
    'src="data:image/gif;base64,R0lGODlhAQABAAAAACw="></a></div></body></html>'
)


def handoff_request():
    return {
        "request_id": "request-1", "host_task_ref": "task-1", "session_ref": "chrome-1",
        "extractor_version": "tiktok-public-grid-v1",
        "queries": [{"query_id": "query-1", "query": "túi đi làm", "result_limit": 3,
                     "search_url": "https://www.tiktok.com/search?q=t%C3%BAi%20%C4%91i%20l%C3%A0m"}],
    }


def open_relay_in_browser(relay):
    """A real Chromium on the relay page, with TikTok served from a fixture rather than the network."""
    playwright = pytest.importorskip("playwright.sync_api").sync_playwright().start()
    try:
        browser = playwright.chromium.launch()
    except Exception as error:
        playwright.stop()
        pytest.skip(f"Chromium is not installed: {type(error).__name__}")
    context = browser.new_context()
    context.route("https://www.tiktok.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=SEARCH_FIXTURE))
    page = context.new_page()
    response = page.goto(relay.url)
    return playwright, browser, context, page, response.headers


def test_relay_opens_the_search_and_stages_the_answer_the_tab_posts_back():
    seen = []
    extractor = (Path(__file__).resolve().parents[2]
                 / "src/ignis/infrastructure/connectors/host_browser/tiktok_search.js").read_text()
    relay = relay_type()(handoff_request(), extractor,
                         lambda answer: seen.append(answer) or {"status": "STAGED"}, 20)
    playwright, browser, context, page, headers = open_relay_in_browser(relay)
    try:
        assert "script-src 'nonce-" in headers["content-security-policy"]
        with context.expect_page() as opened:
            page.click("button[data-query-id='query-1']")
        tab = opened.value
        tab.wait_for_load_state()
        # The tab script answers with counts only; the records go tab-to-relay.
        assert tab.evaluate(page.locator("#tab-script").input_value()) == {
            "posted": True, "status": "HEALTHY", "records": 1}
        page.wait_for_selector("text=STAGED")
        assert len(seen) == 1
        assert {key: seen[0][key] for key in ("request_id", "host_task_ref", "session_ref", "extractor_version")} == {
            "request_id": "request-1", "host_task_ref": "task-1", "session_ref": "chrome-1",
            "extractor_version": "tiktok-public-grid-v1"}
        assert [answer["query_id"] for answer in seen[0]["answers"]] == ["query-1"]
        assert seen[0]["answers"][0]["records"][0]["source_url"].endswith("/video/7417820067028536584")
    finally:
        browser.close()
        playwright.stop()
        relay.close()


def test_relay_ignores_answers_from_another_origin_an_unopened_tab_or_the_wrong_query():
    seen = []
    relay = relay_type()(handoff_request(), "arg => arg", lambda answer: seen.append(answer) or {}, 20)
    playwright, browser, context, page, _headers = open_relay_in_browser(relay)
    answer = {"query_id": "query-1", "query": "túi đi làm", "records": []}
    try:
        # Same page, wrong origin.
        page.evaluate("answer => window.postMessage({kind: 'ignis-host-answer', answer}, '*')", answer)
        # A TikTok tab the relay did not open.
        with context.expect_page() as stray:
            page.evaluate("window.open('https://www.tiktok.com/search?q=other')")
        stray.value.wait_for_load_state()
        stray.value.evaluate(f"answer => window.opener.postMessage({{kind: 'ignis-host-answer', answer}}, '{relay.origin}')", answer)
        # The tab the relay opened, answering for a query it was not opened for.
        with context.expect_page() as opened:
            page.click("button[data-query-id='query-1']")
        opened.value.wait_for_load_state()
        opened.value.evaluate(
            f"answer => window.opener.postMessage({{kind: 'ignis-host-answer', answer: {{...answer, query_id: 'other'}}}}, '{relay.origin}')",
            answer)
        page.wait_for_timeout(500)
        assert seen == []
        assert page.locator("#payload").input_value() == ""
        assert page.locator("#handoff-status").inner_text().startswith("0 of 1")
    finally:
        browser.close()
        playwright.stop()
        relay.close()


@pytest.mark.parametrize("source,mutation", [("threads", "valid"), ("threads", "origin"), ("threads", "window"),
    ("threads", "query"), ("threads", "request"), ("tiktok", "valid"), ("tiktok", "origin")])
def test_source_bound_relay_script_uses_opened_window_query_and_request_without_socket(monkeypatch, source, mutation):
    import re
    import shutil
    import subprocess
    import time
    from ignis.infrastructure.connectors.host_browser import relay as module

    class FakeHTTP:
        server_port = 12345
        def __init__(self, *args):
            pass
        def handle_request(self):
            time.sleep(0.001)
        def server_close(self):
            pass
    monkeypatch.setattr(module, "HTTPServer", FakeHTTP)
    request = handoff_request()
    request["source"] = source
    request["extractor_version"] = "threads-search-top-v1" if source == "threads" else "tiktok-public-grid-v1"
    request["queries"][0]["search_url"] = request["queries"][0]["search_url"].replace("www.tiktok.com", "www.threads.com") if source == "threads" else request["queries"][0]["search_url"]
    relay = module.LoopbackRelay(request, "arg => ({records: []})", lambda answer: {}, 10)
    try:
        node = shutil.which("node")
        assert node, "Node is required for the relay contract"
        script = re.search(r'<script nonce="[^"]+">(.*?)</script>', relay._page, re.S).group(1)
        data = re.search(r'<script type="application/json" id="relay-data">(.*?)</script>', relay._page, re.S).group(1)
        harness = r'''
const vm=require('vm'), data=JSON.parse(process.argv[1]), script=process.argv[2];
let click, message, submitted=0, payload={value:''}; const tab={}, wrong={};
const document={getElementById:id=> id==='relay-data'?{textContent:JSON.stringify(data)}:id==='payload'?payload:{textContent:''},
 querySelector:selector=>selector==='form'?{requestSubmit:()=>submitted++}:{addEventListener:(name,cb)=>click=cb}};
vm.runInNewContext(script,{document,window:{open:()=>tab,addEventListener:(name,cb)=>message=cb},CSS:{escape:x=>x},Map,JSON});
const mutation=process.argv[3],source=process.argv[4];
if(mutation!=='window')click();
const answer={query_id:'query-1',query:mutation==='query'?'wrong':data.queries[0].query,records:[]};
message({origin:mutation==='origin'?'https://attacker.invalid':source==='threads'?'https://www.threads.com':'https://www.tiktok.com',
 source:mutation==='window'?wrong:tab,data:{kind:'ignis-host-answer',request_id:mutation==='request'?'wrong':data.request_id,answer}});
message({origin:'https://attacker.invalid',source:tab,data:{kind:'ignis-host-answer',answer}});
console.log(JSON.stringify({submitted,payload:payload.value?JSON.parse(payload.value):null}));
'''
        result = subprocess.run([node, "-e", harness, data, script, mutation, source], capture_output=True, text=True, check=True)
        result = json.loads(result.stdout)
        assert result["submitted"] == (1 if mutation == "valid" else 0)
        if mutation == "valid":
            assert result["payload"].get("source", "tiktok") == source
    finally:
        relay.close()


def test_threads_handoff_returns_only_counts_and_refuses_opener_loss():
    import shutil
    import subprocess
    path = Path(__file__).resolve().parents[2] / "src/ignis/infrastructure/connectors/host_browser/threads_handoff.js"
    assert path.is_file(), "Threads handoff must be packaged"
    code = r'''
const fs=require('fs'),vm=require('vm');const source=fs.readFileSync(process.argv[1],'utf8');
let posted; const context={URL,location:{href:'https://www.threads.com/search?q=synthetic'},
 window:{opener:{postMessage:(value,origin)=>posted={value,origin}}}};
const fn=vm.runInNewContext('('+source+')',context), extract=()=>({status:'HEALTHY',records:[{excerpt:'Synthetic private transport fixture'}]});
const result=fn(extract,[{query_id:'q',query:'synthetic',result_limit:3}],'http://127.0.0.1:12345','request');
context.window.opener=null;const lost=fn(extract,[{query_id:'q',query:'synthetic',result_limit:3}],'http://127.0.0.1:12345','request');
console.log(JSON.stringify({result,lost,request:posted.value.request_id,origin:posted.origin}));
'''
    result = subprocess.run([shutil.which("node"), "-e", code, str(path)], capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert value["result"] == {"posted": True, "status": "HEALTHY", "records": 1}
    assert value["lost"]["posted"] is False
    assert value["request"] == "request"
