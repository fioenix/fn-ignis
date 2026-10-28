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


@pytest.mark.parametrize("source,mutation", [("tiktok", "valid"), ("tiktok", "origin"),
    ("tiktok", "window"), ("tiktok", "query")])
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
    request["extractor_version"] = "threads-search-top-v2" if source == "threads" else "tiktok-public-grid-v1"
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


def test_manual_threads_unsupported_locale_stages_through_the_real_form():
    from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
    from tests.fixtures.meta_host_browser_answers import host_answer

    service = HostBrowserSearchService()
    try:
        request = service.prepare(host_task_ref="task", session_ref="session", queries=["synthetic query"],
                                  result_limit=3, lifetime_seconds=60, authorized=True, source="threads")
        relay = service._tickets[request["request_id"]]["relay"]
        payload = host_answer(request, degraded=True)
        payload["answers"][0]["locale"] = "unsupported"
        status, body, _ = post(relay, payload)
        assert status == 200 and b"STAGED" in body
        assert relay.wait_closed(2)
        receipt = service.submit(request["request_id"], "task", "session")
        assert receipt["observations"] == []
        assert receipt["outcomes"][0]["status"] == "DEGRADED"
        assert "page locale is unsupported" in receipt["outcomes"][0]["note"]
    finally:
        service.close()


@pytest.fixture
def socket_free_relay(monkeypatch):
    """Keep real rendering and handlers; replace only the forbidden socket bind."""
    import time
    from ignis.infrastructure.connectors.host_browser import relay as module

    class FakeHTTP:
        server_port = 12345
        def __init__(self, address, handler):
            self.handler = handler
        def handle_request(self):
            time.sleep(0.001)
        def server_close(self):
            pass

    monkeypatch.setattr(module, "HTTPServer", FakeHTTP)
    relays = []
    def create(source="threads", count=1):
        request = handoff_request()
        request.update(source=source, extractor_version="threads-search-top-v2" if source == "threads" else "tiktok-public-grid-v1")
        request["queries"] = [dict(query_id=f"query-{i+1}", query=f"synthetic {i+1}", result_limit=3,
            search_url=f"https://www.{source}.com/search?q=synthetic%20{i+1}") for i in range(count)]
        relay = module.LoopbackRelay(request,
            "arg => ({...arg, status: 'HEALTHY', records: [{source_url: 'https://www.threads.com/@fixture/post/ID'}]})",
            lambda answer: {}, 10)
        relays.append(relay)
        return relay
    yield create
    for relay in relays:
        relay.close()


def run_node(code, *args):
    import shutil
    import subprocess
    node = shutil.which("node")
    assert node, "Node is required for the relay contract"
    result = subprocess.run([node, "-e", code, *args], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def relay_scripts(relay):
    import re
    script = re.search(r'<script nonce="[^"]+">(.*?)</script>', relay._page, re.S).group(1)
    data = json.loads(re.search(r'<script type="application/json" id="relay-data">(.*?)</script>', relay._page, re.S).group(1))
    return script, data


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("mutation", ["valid", "tampered", "request", "query", "text", "limit", "kind", "duplicate"])
def test_threads_encrypted_same_tab_roundtrip_and_invalid_messages_leave_state_unchanged(socket_free_relay, count, mutation):
    relay = socket_free_relay(count=count)
    script, data = relay_scripts(relay)
    code = r'''
const vm=require('vm'), crypto=require('crypto').webcrypto;
const data=JSON.parse(process.argv[1]), script=process.argv[2], tabScript=process.argv[3], mutation=process.argv[4];
(async()=>{
let listener, submitted=0, urls=[], results=[], channels=[], payload={value:''}, status={textContent:'initial'};
const document={getElementById:id=>id==='relay-data'?{textContent:JSON.stringify(data)}:id==='payload'?payload:status,
 querySelector:s=>s==='form'?{requestSubmit:()=>submitted++}:{addEventListener:()=>{}}};
class BroadcastChannel {constructor(name){channels.push(name)} set onmessage(cb){listener=cb} close(){}}
const shared={crypto,TextEncoder,TextDecoder,Uint8Array,atob,btoa,URL,Map,JSON};
vm.runInNewContext(script,{...shared,document,BroadcastChannel,window:{open:()=>({}),addEventListener:()=>{}},CSS:{escape:x=>x}});
for(const query of data.queries){
 let navigate;
 const context={...shared,location:{href:query.search_url,replace:url=>urls.push(url)},window:{opener:null},setTimeout:cb=>navigate=cb};
 const result=await vm.runInNewContext(tabScript,context);results.push(result);
 if(navigate)navigate();
}
let raw=urls[0]?.split('#')[1];
if(raw && mutation!=='valid'){
 const key=await crypto.subtle.importKey('raw',Buffer.from(data.fragment_key,'base64url'),'AES-GCM',false,['encrypt','decrypt']);
 const bytes=Buffer.from(raw,'base64url');
 const msg=JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:bytes.subarray(0,12)},key,bytes.subarray(12))));
 if(mutation==='request')msg.request_id='wrong';
 if(mutation==='query')msg.answer.query_id='wrong';
 if(mutation==='text')msg.answer.query='wrong';
 if(mutation==='limit')msg.answer.records=Array(4).fill({});
 if(mutation==='kind')msg.kind='wrong';
 if(mutation==='duplicate')msg.answer.records=[];
 const iv=crypto.getRandomValues(new Uint8Array(12));
 const encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv},key,new TextEncoder().encode(JSON.stringify(msg)));
 raw=Buffer.concat([iv,Buffer.from(encrypted)]).toString('base64url');
 if(mutation==='tampered'){const b=Buffer.from(raw,'base64url');b[20]^=1;raw=b.toString('base64url');}
}
if(listener && raw)await listener({data:raw});
const interim={submitted,payload:payload.value,status:status.textContent};
if(mutation==='duplicate')await listener({data:urls[0].split('#')[1]});
if(mutation==='valid'||mutation==='duplicate')for(const url of urls.slice(1))await listener({data:url.split('#')[1]});
const final=payload.value;
if(listener)await listener({data:urls[0]?.split('#')[1]});
console.log(JSON.stringify({results,urls,channels,interim,submitted,payload:payload.value?JSON.parse(payload.value):null,unchangedAfterSubmit:final===payload.value}));
})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = run_node(code, json.dumps(data), script, relay.tab_script, mutation)
    assert result["results"] == [{"posted": True, "status": "HEALTHY", "records": 1}] * count
    assert len(result["urls"]) == count
    for url in result["urls"]:
        assert url.startswith(relay.url + "receive#")
        assert "@fixture" not in url and data["fragment_key"] not in url
    import base64
    ivs = [base64.urlsafe_b64decode(url.split("#")[1] + "=" * (-len(url.split("#")[1]) % 4))[:12]
           for url in result["urls"]]
    assert len(set(ivs)) == count
    assert result["channels"] == ["ignis-host-answer:" + data["request_id"]]
    if mutation not in {"valid", "duplicate"}:
        assert result["interim"] == dict(submitted=0, payload="", status="initial")
    else:
        assert result["submitted"] == 1 and result["unchangedAfterSubmit"]
        assert result["payload"]["source"] == "threads"
        for field in ("request_id", "host_task_ref", "session_ref", "extractor_version"):
            assert result["payload"][field] == data[field]
        assert [a["query_id"] for a in result["payload"]["answers"]] == [q["query_id"] for q in data["queries"]]
        if mutation == "duplicate":
            assert result["payload"]["answers"][0]["records"] == []


@pytest.mark.parametrize("failure", ["oversize", "origin", "filter", "query", "hash", "route", "crypto"])
def test_threads_refuses_before_navigation_and_returns_no_record_content(socket_free_relay, failure):
    relay = socket_free_relay()
    code = r'''
const vm=require('vm'),crypto=require('crypto').webcrypto;
(async()=>{let navigations=0,timers=0;const failure=process.argv[2];
let href='https://www.threads.com/search?q=synthetic%201';
if(failure==='origin')href=href.replace('www.threads.com','attacker.invalid');
if(failure==='filter')href+='&filter=recent';if(failure==='hash')href+='#x';
if(failure==='query')href=href.replace('synthetic%201','wrong');if(failure==='route')href=href.replace('/search','/profile');
let script=process.argv[1];if(failure==='oversize')script=script.replace("'https://www.threads.com/@fixture/post/ID'","'x'.repeat(1000000)");
const result=await vm.runInNewContext(script,{URL,location:{href,replace:()=>navigations++},window:{opener:null},
 crypto:failure==='crypto'?{}:crypto,TextEncoder,Uint8Array,btoa,setTimeout:()=>timers++});
console.log(JSON.stringify({result,navigations,timers}));})().catch(e=>{console.error(e);process.exit(1)});
'''
    value = run_node(code, relay.tab_script, failure)
    assert value["result"]["posted"] is False
    assert value["result"]["reason"] == ("Fragment too large" if failure == "oversize" else
                                         "Encrypted handoff unavailable" if failure == "crypto" else
                                         "Unapproved search page")
    assert set(value["result"]) == {"posted", "reason"}
    assert value["navigations"] == value["timers"] == 0


def test_threads_receiver_exact_route_headers_hash_clear_and_no_key(socket_free_relay):
    import io
    from email.message import Message
    relay = socket_free_relay()
    _, data = relay_scripts(relay)
    assert len(__import__("base64").urlsafe_b64decode(data["fragment_key"] + "=")) == 32
    assert data["fragment_key"] in relay.tab_script
    assert data["fragment_key"] not in relay.url
    assert relay_scripts(socket_free_relay())[1]["fragment_key"] != data["fragment_key"]
    def get(path, method="GET", host=None, target=relay):
        handler = object.__new__(target._server.handler)
        handler.path = path
        handler.headers = Message()
        handler.headers["Host"] = host or target.origin.removeprefix("http://")
        handler.wfile = io.BytesIO()
        headers = {}
        handler.send_response = lambda code: headers.update(status=code)
        handler.send_header = lambda name, value: headers.update({name: value})
        handler.end_headers = lambda: None
        getattr(handler, "do_" + method)()
        return headers, handler.wfile.getvalue().decode()
    path = urlsplit(relay.url).path + "receive"
    headers, receiver = get(path)
    assert headers["status"] == 200
    assert headers["Referrer-Policy"] == "no-referrer" and headers["Cache-Control"] == "no-store"
    assert "script-src 'nonce-" in headers["Content-Security-Policy"]
    assert data["fragment_key"] not in receiver
    assert "Answer sent to the relay; close this tab" in receiver
    assert "<script src=" not in receiver and "decrypt" not in receiver
    import re
    js = re.search(r'<script nonce="[^"]+">(.*?)</script>', receiver, re.S).group(1)
    value = run_node(r'''
const vm=require('vm');let order=[],sent=[];
class BroadcastChannel {constructor(name){this.name=name}postMessage(raw){sent.push([this.name,raw]);order.push('post')}close(){}}
vm.runInNewContext(process.argv[1],{location:{hash:'#ciphertext',pathname:'/cap/receive',search:''},
 history:{replaceState:(...args)=>order.push(args[2])},BroadcastChannel});
console.log(JSON.stringify({order,sent}));
''', js)
    assert value == dict(order=["/cap/receive", "post"], sent=[["ignis-host-answer:request-1", "ciphertext"]])
    for wrong in (path + "/", path + "?x=1", "/receive"):
        assert get(wrong)[0]["status"] == 404
    assert get(path, "POST")[0]["status"] == 404
    assert get(path, host="attacker.invalid")[0]["status"] == 403
    relay._stop.set()
    assert get(path)[0]["status"] == 410
    tiktok = socket_free_relay(source="tiktok")
    assert "fragment_key" not in relay_scripts(tiktok)[1]
    assert "BroadcastChannel" not in tiktok._page and "receive#" not in tiktok.tab_script
    assert tiktok._fragment_key is None and tiktok._receiver_page is None
    assert get(urlsplit(tiktok.url).path + "receive", target=tiktok)[0]["status"] == 404


def test_threads_prepare_exposes_key_only_in_tab_script_and_releases_relay_copies(socket_free_relay):
    from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
    service = HostBrowserSearchService()
    try:
        prepared = service.prepare(host_task_ref="task", session_ref="session", queries=["synthetic"],
                                   result_limit=3, lifetime_seconds=60, authorized=True, source="threads")
        relay = service._tickets[prepared["request_id"]]["relay"]
        _, data = relay_scripts(relay)
        key = data["fragment_key"]
        assert key in prepared["tab_script"]
        assert key not in json.dumps({name: value for name, value in prepared.items() if name != "tab_script"})
        service.cancel(prepared["request_id"], "task", "session")
        assert relay.wait_closed(2)
        assert relay._fragment_key is None
        assert key not in relay._page and key not in relay.tab_script
    finally:
        service.close()
