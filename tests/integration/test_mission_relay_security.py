"""Security response headers on the actual MCP-opened viewer over disposable storage."""

import asyncio
import http.client
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from test_mission_relay_read_boundary import _setup_traps, _state, relay_case  # noqa: F401 -- fixture
from test_mission_relay_mcp import (  # noqa: F401 -- attention_case is a fixture
    _OwnedRepository,
    _caller_client,
    _http,
    _observe_chain,
    attention_case,
)
from tests.unit.test_mission_relay_http import _assert_maintained_csp

MAINTAINED_DIRECTIVES = {
    "default-src", "connect-src", "object-src", "base-uri", "frame-ancestors", "script-src", "style-src", "font-src",
}


def _header(headers, name):
    matches = [value for key, value in headers.items() if key.lower() == name.lower()]
    return matches[0] if len(matches) == 1 else None


def _assert_read_headers(route, headers, content_type):
    assert _header(headers, "Content-Type") == content_type, f"{route}: unexpected Content-Type"
    assert _header(headers, "Cache-Control") == "no-store", f"{route}: missing no-store"
    assert _header(headers, "X-Content-Type-Options") == "nosniff", f"{route}: missing nosniff"
    assert _header(headers, "Referrer-Policy") == "no-referrer", f"{route}: missing no-referrer"
    assert _header(headers, "Access-Control-Allow-Origin") is None, f"{route}: CORS must not be granted"


def _assert_page_policy(headers, html):
    csp = _header(headers, "Content-Security-Policy")
    assert csp is not None, "maintained HTML: missing Content-Security-Policy"
    _assert_maintained_csp(csp, html)
    directives = {item.strip().split()[0].lower(): item.strip().split()[1:] for item in csp.split(";") if item.strip()}
    assert set(directives) == MAINTAINED_DIRECTIVES, "maintained HTML: unexpected CSP directive set"
    assert directives["font-src"] == ["https://fonts.gstatic.com"], "maintained HTML: font origins widened"


def _refused_after_close(url, deadline_seconds=5.0):
    """Finite check that the listener stopped accepting connections."""
    target = urlsplit(url)
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=1)
        try:
            connection.request("GET", target.path)
            connection.getresponse().read()
        except ConnectionRefusedError:
            return True
        except OSError:
            pass
        finally:
            connection.close()
        time.sleep(0.1)
    return False


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_actual_mcp_opened_viewer_serves_maintained_security_headers(attention_case, monkeypatch, tmp_path):
    from ignis.interfaces.mcp import server
    case, missions, runs = attention_case
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)

    def forbidden(*args, **kwargs):
        raise AssertionError("Viewer initialized writable components or credentials")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    owned = _OwnedRepository(monkeypatch, case)
    mission_id, run_id = str(missions[0].id), str(runs[0])
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            cap = (await client.call_tool("open_mission_relay", {
                "mission_id": mission_id, "run_id": run_id,
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            })).structured_content
            assert cap["status"] == "OK"
            url = cap["url"]
            assert urlsplit(url).hostname == "127.0.0.1"

            status, headers, body = await asyncio.to_thread(_http, url)
            assert status == 200, "maintained HTML route did not succeed"
            html = body.decode("utf-8")
            assert mission_id in html and run_id in html
            _assert_read_headers("maintained HTML", headers, "text/html; charset=utf-8")
            _assert_page_policy(headers, html)

            status, headers, body = await asyncio.to_thread(_http, url + "snapshot?page_size=2")
            assert status == 200, "snapshot route did not succeed"
            snapshot = json.loads(body)
            assert snapshot["mission_id"] == mission_id and snapshot["run_id"] == run_id
            _assert_read_headers("snapshot", headers, "application/json")

            observation = snapshot["evidence"][0]["observation_id"]
            status, headers, body = await asyncio.to_thread(_http, url + f"inspect/{observation}?page_size=2")
            assert status == 200, "inspect route did not succeed"
            inspected = json.loads(body)
            assert inspected["observation"]["observation_id"] == observation
            assert inspected["mission_id"] == mission_id and inspected["run_id"] == run_id
            _assert_read_headers("inspect", headers, "application/json")
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)
    assert await asyncio.to_thread(_refused_after_close, url), "Listener still accepts connections after shutdown"


REFUSED_SCOPE = {"schema_version": 1, "status": "REFUSED", "reason_code": "SCOPE_MISMATCH"}


def _get(url, headers=None):
    """GET with explicit request headers; a supplied Host replaces the automatic one."""
    target = urlsplit(url)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    try:
        connection.request("GET", target.path + ("?" + target.query if target.query else ""), headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _open_payload(mission_id, run_id):
    return {"mission_id": mission_id, "run_id": run_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_actual_listener_refuses_nonexact_host_and_origin_before_storage_read(
        attention_case, monkeypatch, tmp_path, caplog, capsys):
    from ignis.interfaces.mcp import server
    caplog.set_level("DEBUG")
    case, missions, runs = attention_case
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)

    def forbidden(*args, **kwargs):
        raise AssertionError("Viewer initialized writable components or credentials")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    owned = _OwnedRepository(monkeypatch, case)
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            cap = (await client.call_tool("open_mission_relay", _open_payload(
                str(missions[0].id), str(runs[0])))).structured_content
            assert cap["status"] == "OK"
            url = cap["url"]
            port = urlsplit(url).port
            token = urlsplit(url).path.strip("/").split("/")[-1]
            snapshot_url = url + "snapshot?page_size=2"
            status, body = await asyncio.to_thread(_get, snapshot_url, {"Origin": f"http://127.0.0.1:{port}"})
            assert status == 200, "exact-origin control did not succeed"
            assert json.loads(body)["mission_id"] == str(missions[0].id)
            reads = (len(observed.statements), len(observed.opens))
            assert reads[0] > 0 and reads[1] > 0, "The observer must see the valid control's physical read"
            refusals = (
                {"Host": f"localhost:{port}"},
                {"Host": f"attacker.invalid:{port}"},
                {"Origin": "https://attacker.invalid"},
                {"Origin": "null"},
            )
            for headers in refusals:
                status, body = await asyncio.to_thread(_get, snapshot_url, headers)
                assert (status, json.loads(body)) == (403, REFUSED_SCOPE), f"not refused: {headers}"
                assert token.encode() not in body
            assert (len(observed.statements), len(observed.opens)) == reads, "A refused request reached storage"
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)
    captured = capsys.readouterr()
    assert token not in caplog.text and token not in captured.out and token not in captured.err, "Capability token was logged"


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_parent_and_child_capabilities_inspect_only_their_own_observations(relay_case, monkeypatch, tmp_path):
    from ignis.interfaces.mcp import server
    from tests.integration.test_mission_follow_up_viewer import _link, _records
    case, parent, child, foreign = await _records(relay_case, tmp_path)
    await _link(case, parent, child)
    # Linked child sightings reuse parent source identities; source equality must not grant membership.
    shared_sources = sorted({pair[1] for pair in parent.pairs} & {pair[1] for pair in child.pairs})
    assert shared_sources, "Fixture must link parent and child sightings through a shared source"
    shared_source = shared_sources[0]
    parent_observation = sorted(o for o, source in parent.pairs if source == shared_source)[0]
    child_observation = sorted(o for o, source in child.pairs if source == shared_source)[0]
    assert parent_observation != child_observation
    foreign_observation, foreign_source = sorted(foreign.pairs)[0]
    targets = {
        "parent": (parent_observation, shared_source),
        "child": (child_observation, shared_source),
        "foreign": (foreign_observation, foreign_source),
    }
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)

    def forbidden(*args, **kwargs):
        raise AssertionError("Viewer initialized writable components or credentials")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    owned = _OwnedRepository(monkeypatch, case)
    records = {"parent": parent, "child": child, "foreign": foreign}
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            for selected in ("parent", "child"):
                record = records[selected]
                cap = (await client.call_tool("open_mission_relay", _open_payload(
                    str(record.mission.id), str(record.run.run_id)))).structured_content
                assert cap["status"] == "OK"
                status, body = await asyncio.to_thread(_get, cap["url"] + "snapshot?page_size=200")
                snapshot = json.loads(body)
                assert status == 200 and snapshot["mission_id"] == str(record.mission.id)
                assert {(row["observation_id"], row["source_id"]) for row in snapshot["evidence"]} <= record.pairs
                for target, (observation, source) in targets.items():
                    assert (observation, source) in records[target].pairs
                    status, body = await asyncio.to_thread(
                        _get, cap["url"] + f"inspect/{observation}?page_size=200")
                    if target == selected:
                        inspected = json.loads(body)
                        assert status == 200 and inspected["observation"]["observation_id"] == observation
                        assert inspected["observation"]["source_id"] == source
                        assert inspected["mission_id"] == str(record.mission.id)
                    else:
                        assert (status, json.loads(body)) == (403, REFUSED_SCOPE), f"{selected} inspected {target}"
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)


# Synthetic private values; observation text is persisted raw, so the projection's PII policy must redact it.
PRIVATE_EMAIL = "relay.sentinel@example.com"
PRIVATE_PHONE = "+84 931 405 002"
PRIVATE_SECRET = "sk-RELAYSENTINELabcdefghijklmnop"
STORED_MARKUP = '<img src=x onerror="window.untrustedExecuted=true">'

# Trusted test instrumentation: observe CSP violations, then attempt one harmless unauthorized inline script.
CSP_PROBE = """async () => {
    window.cspMarker = 'initial';
    const violations = [];
    document.addEventListener('securitypolicyviolation', (event) => violations.push({
        directive: event.effectiveDirective, disposition: event.disposition, blocked: event.blockedURI}));
    const script = document.createElement('script');
    script.textContent = "window.cspMarker = 'executed';";
    document.body.appendChild(script);
    await new Promise((resolve) => setTimeout(resolve, 200));
    return {marker: window.cspMarker, violations};
}"""


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_browser_masks_private_research_text_and_enforces_inline_script_policy(
        relay_case, monkeypatch, tmp_path):
    from dataclasses import replace
    from playwright.async_api import async_playwright, expect
    from ignis.application.use_cases.record_mission_research_work import RecordMissionResearchWorkUseCase
    from ignis.interfaces.mcp import server
    from tests.integration.test_research_recording_mcp_boundary import public_handoff
    from tests.integration.test_research_work_persistence import _arrange
    case, mission, _, _, _, handoff, revision = await _arrange(relay_case, tmp_path)
    private = f"Contact {PRIVATE_EMAIL} or {PRIVATE_PHONE} with {PRIVATE_SECRET}."
    stored = replace(handoff, result=f"Recorded summary. {private} {STORED_MARKUP}",
                     findings=(replace(handoff.findings[0], statement=f"Observations differ. {private}"),))
    recorded = await RecordMissionResearchWorkUseCase(case.repository).execute(
        str(mission.id), public_handoff(stored, revision), host_authorized=True)
    assert recorded["disposition"] == "APPLIED"
    # Research recording already redacts at write time; the stored markup is kept for text-safe rendering.
    persisted = await case.repository.load_research_work(mission.id)
    assert STORED_MARKUP in persisted.handoffs[0].result and PRIVATE_EMAIL not in persisted.handoffs[0].result
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    await case.repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
        raw_title=f"Public synthetic sighting {private}", source_url=f"https://example.invalid/{mission.id}/private",
        mission_id=mission.id, captured_at=datetime.now(timezone.utc),
        metadata={"excerpt": f"Public synthetic excerpt {private}"})])
    # The persisted observation really holds the private values, so their absence below is not vacuous.
    raw = next(s for s in await case.repository.get_mission_signals(mission.id)
               if s.raw_title.startswith("Public synthetic sighting"))
    assert all(value in raw.raw_title and value in raw.metadata["excerpt"]
               for value in (PRIVATE_EMAIL, PRIVATE_PHONE, PRIVATE_SECRET))
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)

    def forbidden(*args, **kwargs):
        raise AssertionError("Viewer initialized writable components or credentials")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    owned = _OwnedRepository(monkeypatch, case)
    private_values = (PRIVATE_EMAIL, PRIVATE_PHONE, PRIVATE_SECRET)
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            cap = (await client.call_tool("open_mission_relay", {"mission_id": str(mission.id),
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()})).structured_content
            assert cap["status"] == "OK"
            target = urlsplit(cap["url"])
            token = target.path.strip("/").split("/")[-1]
            unexpected, errors, responses = [], [], []
            async with async_playwright() as runtime:
                browser = await runtime.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(service_workers="block")

                    async def route(request_route):
                        request = request_route.request
                        parsed = urlsplit(request.url)
                        if request.method == "GET" and parsed.scheme == "http" and parsed.netloc == target.netloc:
                            await request_route.continue_()
                        else:
                            # Fonts and any other origin stay offline; nothing leaves loopback.
                            if parsed.hostname not in ("fonts.googleapis.com", "fonts.gstatic.com"):
                                unexpected.append((request.method, parsed.hostname))
                            await request_route.abort()
                    await context.route("**/*", route)
                    page = await context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("response", lambda response: responses.append(response))
                    async with page.expect_response(
                            lambda r: urlsplit(r.url).path.endswith("/snapshot"), timeout=10000) as first_snapshot:
                        assert (await page.goto(cap["url"])).status == 200
                    assert (await first_snapshot.value).status == 200
                    snapshot_rows = []
                    for response in [r for r in responses if urlsplit(r.url).path.endswith("/snapshot")]:
                        snapshot_rows.extend(json.loads(await response.text())["evidence"])
                    sighting = next(row for row in snapshot_rows if row["title"].startswith("Public synthetic sighting"))
                    assert sighting["observation_id"] == str(raw.observation_id)
                    async with page.expect_response(lambda r: "/inspect/" in urlsplit(r.url).path) as inspected:
                        await page.get_by_test_id("stage-inspector").get_by_role(
                            "button", name=sighting["title"], exact=True).click()
                    inspect_payload = await (await inspected.value).text()
                    assert json.loads(inspect_payload)["observation"]["observation_id"] == str(raw.observation_id)
                    inspector = page.get_by_test_id("stage-inspector")
                    await expect(inspector).to_contain_text("Public synthetic sighting Contact [REDACTED_EMAIL]")
                    await expect(inspector).to_contain_text("Public synthetic excerpt")
                    for value in (*private_values, token):
                        assert value not in inspect_payload, f"Delivered inspection exposes {value[:12]}"
                        assert value not in await page.evaluate("document.documentElement.outerHTML"), \
                            f"Inspector DOM exposes {value[:12]}"
                    await page.locator('[data-stage="Research"]').click()
                    output = page.get_by_role("region", name="Output", exact=True)
                    await expect(output).to_contain_text("Recorded summary.")
                    await expect(output).to_contain_text("[REDACTED_EMAIL]")
                    await expect(output).to_contain_text(STORED_MARKUP)
                    assert await output.locator("img").count() == 0
                    assert await page.evaluate("window.untrustedExecuted === undefined")
                    dom = await page.evaluate("document.documentElement.outerHTML")
                    for value in (*private_values, token):
                        assert value not in dom, f"Rendered DOM exposes {value[:12]}"
                    snapshots = [r for r in responses if urlsplit(r.url).path.endswith("/snapshot")]
                    assert snapshots, "The viewer did not fetch its typed snapshot"
                    for response in snapshots:
                        payload = await response.text()
                        assert json.loads(payload)["mission_id"] == str(mission.id)
                        for value in (*private_values, token):
                            assert value not in payload, f"Delivered snapshot exposes {value[:12]}"

                    probe = await page.evaluate(CSP_PROBE)
                    assert probe["marker"] == "initial", "Unauthorized inline script executed"
                    assert any(item["directive"] == "script-src-elem" and item["disposition"] == "enforce"
                               for item in probe["violations"]), probe["violations"]
                    assert not unexpected and not errors
                    await context.close()
                finally:
                    await browser.close()
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)


# Synthetic structured metadata on one public observation. Every value is a unique non-secret sentinel
# that no PII rule redacts, so only the projection's field selection can keep it out of the viewer.
PUBLIC_TITLE = "Public structured sighting for relay privacy"
PUBLIC_EXCERPT = "Public structured excerpt for relay privacy"
STRUCTURED_SENTINELS = {
    "access_token": "SENTINELACCESSTOKENQ7RELAY",
    "private_messages": "SENTINELPRIVATEMESSAGEQ7RELAY",
    "hidden_reasoning": "SENTINELHIDDENREASONINGQ7RELAY",
    "raw_source_owner_address": "SENTINELOWNERADDRESSQ7RELAY",
    "unknown_nested": "SENTINELUNKNOWNNESTEDQ7RELAY",
}
STRUCTURED_METADATA = {
    "excerpt": PUBLIC_EXCERPT,
    "auth": {"session": {"access_token": STRUCTURED_SENTINELS["access_token"]}},
    "private_messages": [{"direction": "inbound", "text": STRUCTURED_SENTINELS["private_messages"]}],
    "hidden_reasoning": {"summary": STRUCTURED_SENTINELS["hidden_reasoning"]},
    "raw_source": {"owner": {"address": STRUCTURED_SENTINELS["raw_source_owner_address"]}},
    "vendor_extension": {"layer": {"opaque": STRUCTURED_SENTINELS["unknown_nested"]}},
}


def _assert_absent(text, where, forbidden):
    """Report only safe labels, so a failure never echoes the payload, a sentinel or the capability."""
    __tracebackhide__ = True  # The traceback would otherwise print the forbidden values themselves.
    exposed = sorted(label for label, value in forbidden.items() if value in text)
    assert not exposed, f"{where} exposes {', '.join(exposed)}"


def _structured_row(rows, observation_id, source_id, where):
    matches = [row for row in rows if row["observation_id"] == observation_id]
    assert len(matches) == 1, f"{where} lacks the selected observation"
    row = matches[0]
    assert row["source_id"] == source_id, f"{where} changed the source identity"
    assert row["title"] == PUBLIC_TITLE, f"{where} lacks the public title"
    assert PUBLIC_EXCERPT in (row["excerpt"] or ""), f"{where} lacks the public excerpt"
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_browser_excludes_structured_private_observation_metadata(
        relay_case, monkeypatch, tmp_path, caplog, capsys):
    from playwright.async_api import async_playwright, expect
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    from ignis.interfaces.mcp import server
    from tests.unit.test_mission_claims import _eligible_mission
    caplog.set_level("DEBUG")
    case = relay_case[0]
    _, _, mission, _, _ = await _eligible_mission(tmp_path, repository=case.repository)
    mission_id = str(mission.id)
    await case.repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE, raw_title=PUBLIC_TITLE,
        source_url=f"https://example.invalid/{mission_id}/structured", mission_id=mission.id,
        captured_at=datetime.now(timezone.utc), metadata=STRUCTURED_METADATA)])
    # The canonical record really retains every private category, so the absence checks below are not vacuous.
    stored = [s for s in await case.repository.get_mission_signals(mission.id) if s.raw_title == PUBLIC_TITLE]
    assert len(stored) == 1 and stored[0].metadata == STRUCTURED_METADATA, "Storage did not retain the metadata"
    assert stored[0].observation_id is not None and stored[0].source_id is not None
    observation_id, source_id = str(stored[0].observation_id), str(stored[0].source_id)
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)

    def forbidden(*args, **kwargs):
        raise AssertionError("Viewer initialized writable components or credentials")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    owned = _OwnedRepository(monkeypatch, case)
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            cap = (await client.call_tool("open_mission_relay", {"mission_id": mission_id, "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()})).structured_content
            assert cap["status"] == "OK"
            target = urlsplit(cap["url"])
            token = target.path.strip("/").split("/")[-1]
            private = dict(STRUCTURED_SENTINELS, capability_token=token)
            _assert_absent(json.dumps({k: v for k, v in cap.items() if k != "url"}), "MCP open result", private)

            # Bounded refused reads: one malformed route, one observation outside the selected corpus.
            status, body = await asyncio.to_thread(_get, cap["url"] + "inspect/not-an-observation?page_size=2")
            assert (status, json.loads(body)) == (400, {"schema_version": 1, "status": "REFUSED",
                                                       "reason_code": "INVALID_REQUEST"})
            _assert_absent(body.decode("utf-8"), "Malformed refusal", private)
            status, body = await asyncio.to_thread(
                _get, cap["url"] + "inspect/00000000-0000-4000-8000-000000000000?page_size=200")
            assert (status, json.loads(body)) == (403, REFUSED_SCOPE)
            _assert_absent(body.decode("utf-8"), "Out-of-scope refusal", private)

            unexpected, errors, console, responses = [], [], [], []
            async with async_playwright() as runtime:
                browser = await runtime.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(service_workers="block")

                    async def route(request_route):
                        request = request_route.request
                        parsed = urlsplit(request.url)
                        if request.method == "GET" and parsed.scheme == "http" and parsed.netloc == target.netloc:
                            await request_route.continue_()
                        else:
                            # Webfonts and any other origin stay offline; nothing leaves loopback.
                            if parsed.hostname not in ("fonts.googleapis.com", "fonts.gstatic.com"):
                                unexpected.append((request.method, parsed.hostname))
                            await request_route.abort()
                    await context.route("**/*", route)
                    page = await context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("console", lambda message: console.append(message.text))
                    page.on("response", lambda response: responses.append(response))

                    async with page.expect_response(
                            lambda r: urlsplit(r.url).path.endswith("/snapshot"), timeout=10000) as first_snapshot:
                        document = await page.goto(cap["url"])
                        assert document.status == 200, "maintained HTML route did not succeed"
                        html = await document.text()
                        assert mission_id in html and observation_id in html and PUBLIC_TITLE in html
                        _assert_absent(html, "Initial HTML", private)
                    first = await first_snapshot.value
                    assert first.status == 200, "first snapshot did not succeed"
                    payload = await first.text()
                    snapshot = json.loads(payload)
                    assert snapshot["mission_id"] == mission_id and snapshot["run_id"] is None
                    _structured_row(snapshot["evidence"], observation_id, source_id, "First snapshot")
                    _assert_absent(payload, "First snapshot", private)

                    async with page.expect_response(lambda r: "/inspect/" in urlsplit(r.url).path) as inspected:
                        await page.get_by_test_id("stage-inspector").get_by_role(
                            "button", name=PUBLIC_TITLE, exact=True).click()
                    response = await inspected.value
                    assert response.status == 200, "inspection did not succeed"
                    payload = await response.text()
                    inspection = json.loads(payload)
                    assert inspection["mission_id"] == mission_id and inspection["run_id"] is None
                    _structured_row([inspection["observation"]], observation_id, source_id, "Inspection")
                    _assert_absent(payload, "Inspection", private)
                    inspector = page.get_by_test_id("stage-inspector")
                    await expect(inspector).to_contain_text(PUBLIC_TITLE)
                    await expect(inspector).to_contain_text(PUBLIC_EXCERPT)
                    await expect(inspector).to_contain_text(observation_id)
                    _assert_absent(await page.evaluate("document.documentElement.outerHTML"), "Inspector DOM", private)

                    # A later refresh settles only once the viewer shows that response's read receipt.
                    async with page.expect_response(
                            lambda r: urlsplit(r.url).path.endswith("/snapshot"), timeout=10000) as refreshed:
                        pass
                    response = await refreshed.value
                    assert response.status == 200, "refresh did not succeed"
                    payload = await response.text()
                    snapshot = json.loads(payload)
                    assert snapshot["mission_id"] == mission_id
                    _structured_row(snapshot["evidence"], observation_id, source_id, "Refresh")
                    _assert_absent(payload, "Refresh", private)
                    await expect(page.get_by_test_id("snapshot-state")).to_contain_text(snapshot["read_at"])
                    await expect(page.get_by_test_id("mission-authority")).to_contain_text(mission_id)
                    _assert_absent(await page.evaluate("document.documentElement.outerHTML"), "Refreshed DOM", private)

                    _assert_absent("\n".join(console), "Browser console", private)
                    assert not unexpected and not errors, "Browser left loopback or raised a page error"
                    await context.close()
                finally:
                    await browser.close()
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)
    captured = capsys.readouterr()
    diagnostics = dict(private, viewer_url=cap["url"])
    _assert_absent(caplog.text, "Captured logs", diagnostics)
    _assert_absent(captured.out + captured.err, "Captured output", diagnostics)


# One dummy privacy class across the remaining outward-text consumers of a single disposable Market mission.
OUTWARD_EMAIL = "outward.sentinel@example.com"
OUTWARD_PUBLIC = "Outward public marker"
# queried_window is free text on MissionProbeOutcome; the real Gap generator copies it into attempted probes.
OUTWARD_WINDOW = f"{OUTWARD_PUBLIC} window {OUTWARD_EMAIL}"


async def _outward_mission(relay_case, tmp_path, monkeypatch):
    """Current permitted claim plus recorded research, through the existing fixture and owner write paths.

    Channel note, probe queried window and claim wording keep the email in storage (read-time masking). Research labels, the host
    receipt, ACK and the cancellation reason are redacted by the owner commit path at write time.
    """
    import tests.unit.test_mission_claims as claim_fixture
    from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
    from ignis.domain.research_work import ReasonWorkPayload
    from ignis.domain.research_workspace import MissionProbeOutcome
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from tests.integration.test_research_work_persistence import _arrange, _commit
    from tests.unit.test_mission_claims import _observation_candidate
    from uuid import uuid4
    from dataclasses import replace
    with monkeypatch.context() as patch:
        # The fixture's own probe outcomes carry a connector note and queried window through the real
        # record_probe_outcomes path, before the frame and claim exist; surface/status/fingerprint stay as built.
        def outcome(**fields):
            return MissionProbeOutcome(**{**fields, "queried_window": OUTWARD_WINDOW,
                                          "note": f"{OUTWARD_PUBLIC} channel note {OUTWARD_EMAIL}"})
        patch.setattr(claim_fixture, "MissionProbeOutcome", outcome)
        case, mission, domain, port, work, handoff, _ = await _arrange(relay_case, tmp_path)
    store = WorkspaceRepository(repository=case.repository)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    signal = next(s for s in evidence.signals if s.raw_title == "Demand evidence")
    submitted = await SubmitMissionClaimsUseCase(case.repository, store).execute(str(mission.id), work.inputs.frame_digest,
        [_observation_candidate(signal, wording=f"{OUTWARD_PUBLIC} claim wording {OUTWARD_EMAIL}")], created_by="t081-outward")
    assert submitted["permitted"] == 1
    claim = (await store.load_mission_evidence_snapshot(mission.id)).claims[0]
    revision = (await case.repository.load_research_work(mission.id)).revision
    other = replace(work, work_id=uuid4(), state="ASSIGNED", version=1, dependencies=(), ownership_fence="outward-fence",
                    question=f"{OUTWARD_PUBLIC} question {OUTWARD_EMAIL}", assignee_ref=f"assignee {OUTWARD_EMAIL}")
    assigned = await _commit(case.repository, port, mission, "ASSIGN_WORK", other, revision=revision)
    receipt = domain.ResearchActivityReceipt(work_id=other.work_id, epoch=1, ownership_fence=other.ownership_fence,
        execution_ref=f"{OUTWARD_PUBLIC} execution", occurred_at=handoff.occurred_at,
        fresh_until=handoff.occurred_at + timedelta(days=300), provenance="HOST_REPORTED")
    started = await _commit(case.repository, port, mission, "START_WORK", port.ResearchWorkStartAdmission(
        work_id=other.work_id, expected_version=1, ownership_fence=other.ownership_fence, receipt=receipt),
        revision=assigned.revision)
    finding = replace(handoff.findings[0], finding_id=uuid4(), handoff_id=uuid4(), work_id=other.work_id,
        statement=f"{OUTWARD_PUBLIC} finding {OUTWARD_EMAIL}", limitations=(f"limit {OUTWARD_EMAIL}",),
        open_questions=(f"open {OUTWARD_EMAIL}",), alternative_explanation=f"alternative {OUTWARD_EMAIL}")
    result = replace(handoff, handoff_id=finding.handoff_id, work_id=other.work_id, expected_version=started.work_version,
        ownership_fence=other.ownership_fence, consumer_ref=f"consumer {OUTWARD_EMAIL}",
        result=f"{OUTWARD_PUBLIC} result {OUTWARD_EMAIL}", limitations=(f"handoff limit {OUTWARD_EMAIL}",),
        open_questions=(f"handoff open {OUTWARD_EMAIL}",), findings=(finding,))
    recorded = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", result, revision=started.revision)
    acked = await _commit(case.repository, port, mission, "ACK_HANDOFF", port.ResearchHandoffAcknowledgement(
        handoff_id=result.handoff_id, consumer_ref=result.consumer_ref, expected_version=recorded.work_version,
        disposition="ACCEPTED", reason_code=None, inputs=result.inputs), revision=recorded.revision)
    cancelled = await _commit(case.repository, port, mission, "REQUEST_CANCEL", ReasonWorkPayload(work_id=work.work_id,
        expected_version=work.version, ownership_fence=work.ownership_fence,
        reason=f"{OUTWARD_PUBLIC} cancel {OUTWARD_EMAIL}"), revision=acked.revision)
    assert [r.disposition for r in (assigned, started, recorded, acked, cancelled)] == ["APPLIED"] * 5
    run = (await store.list_run_journals(mission.id))[0]
    return case, mission, run, signal, claim, other, result, finding, recorded.work_version, cancelled.revision


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_browser_masks_outward_text_across_current_and_withdrawn_permission(
        relay_case, monkeypatch, tmp_path, caplog, capsys):
    from playwright.async_api import async_playwright, expect
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from ignis.interfaces.mcp import server
    from tests.integration.test_research_work_persistence import _sql
    caplog.set_level("DEBUG")
    case, mission, run, signal, claim, other, handoff, finding, ack_version, research_revision = await _outward_mission(
        relay_case, tmp_path, monkeypatch)
    mission_id, run_id = str(mission.id), str(run.run_id)
    # Storage truth first: which values are raw (read-time masking) and which were redacted on write.
    stored = await WorkspaceRepository(repository=case.repository).load_mission_evidence_snapshot(mission.id)
    assert all(OUTWARD_EMAIL in outcome.note for outcome in stored.outcomes), "Channel note was not retained raw"
    assert [o.queried_window for o in stored.outcomes] == [OUTWARD_WINDOW] * 2, "Queried window was not retained raw"
    pairs = {(str(s.observation_id), str(s.source_id)) for s in stored.signals}
    withdrawn = (str(signal.observation_id), str(signal.source_id))
    assert len(pairs) == 6 and withdrawn in pairs
    assert OUTWARD_EMAIL in stored.claims[0].wording, "Claim wording was not retained raw"
    research = await case.repository.load_research_work(mission.id)
    written = json.dumps([(w.question, w.assignee_ref) for w in research.work_items]
                         + [(h.consumer_ref, h.result, h.limitations) for h in research.handoffs]
                         + [(f.statement, f.alternative_explanation) for f in research.findings]
                         + [a.consumer_ref for a in research.acknowledgements] + [e.reason for e in research.events])
    assert OUTWARD_EMAIL not in written and "[REDACTED_EMAIL]" in written and OUTWARD_PUBLIC in written
    _setup_traps(monkeypatch, case.repository)

    def forbidden(*args, **kwargs):
        raise AssertionError("Viewer initialized writable components or credentials")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    owned = _OwnedRepository(monkeypatch, case)
    console, errors, unexpected, snapshots = [], [], [], []
    async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
        cap = (await client.call_tool("open_mission_relay", _open_payload(mission_id, run_id))).structured_content
        assert cap["status"] == "OK"
        target = urlsplit(cap["url"])
        token = target.path.strip("/").split("/")[-1]
        private = {"email": OUTWARD_EMAIL, "capability_token": token}
        async with async_playwright() as runtime:
            browser = await runtime.chromium.launch(headless=True)
            try:
                context = await browser.new_context(service_workers="block")

                async def route(request_route):
                    parsed = urlsplit(request_route.request.url)
                    if request_route.request.method == "GET" and parsed.scheme == "http" and parsed.netloc == target.netloc:
                        await request_route.continue_()
                    else:
                        if parsed.hostname not in ("fonts.googleapis.com", "fonts.gstatic.com"):
                            unexpected.append(parsed.hostname)
                        await request_route.abort()
                await context.route("**/*", route)
                page = await context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: console.append(message.text))
                inspector = page.get_by_test_id("stage-inspector")

                async def visit(stage, *expected):
                    await page.locator(f'[data-stage="{stage}"]').first.click()
                    for text in expected:
                        await expect(inspector).to_contain_text(text)
                    for summary in await inspector.locator("details summary").all():
                        await summary.click()
                    _assert_absent(await page.evaluate("document.documentElement.outerHTML"), f"{stage} DOM", private)

                async def settled_snapshot():
                    async with page.expect_response(
                            lambda r: urlsplit(r.url).path.endswith("/snapshot"), timeout=10000) as response:
                        pass
                    response = await response.value
                    assert response.status == 200, "refresh did not succeed"
                    payload = await response.text()
                    data = json.loads(payload)
                    await expect(page.get_by_test_id("snapshot-state")).to_contain_text(data["read_at"])
                    snapshots.append(payload)
                    return data, payload

                # State 1: current permitted claim with recorded research.
                with _observe_chain(case, monkeypatch) as observed:
                    document = await page.goto(cap["url"])
                    assert document.status == 200
                    html = await document.text()
                    assert mission_id in html and run_id in html and str(claim.claim_id) in html and OUTWARD_PUBLIC in html
                    _assert_absent(html, "Initial HTML", private)
                    data, payload = await settled_snapshot()
                    assert (data["mission_id"], data["run_id"]) == (mission_id, run_id)
                    assert data["counts"] == {"observations": 6, "sources": 6}
                    assert {(e["observation_id"], e["source_id"]) for e in data["evidence"]} == pairs
                    gate = data["claim_gate"]
                    assert gate["state"] == "CURRENT" and [c["claim_id"] for c in gate["claims"]] == [str(claim.claim_id)]
                    assert gate["claims"][0]["frame_digest"] == gate["frame_digest"] == claim.frame_digest
                    assert gate["claims"][0]["wording"].startswith(f"{OUTWARD_PUBLIC} claim wording [REDACTED_EMAIL]")
                    assert all(c["note"].startswith(f"{OUTWARD_PUBLIC} channel note [REDACTED") for c in data["channels"]
                               if c["status"] is not None)
                    view = data["research"]
                    assert (view["mission_id"], view["revision"]) == (mission_id, research_revision)
                    inputs = handoff.inputs.to_payload()
                    sources = [{"observation_id": str(o), "source_id": str(s)} for o, s in handoff.observation_sources]
                    [work] = [w for w in view["work_items"] if w["work_id"] == str(other.work_id)]
                    assert work["inputs"] == inputs and work["question"].startswith(OUTWARD_PUBLIC)
                    [recorded] = [h for h in view["handoffs"] if h["handoff_id"] == str(handoff.handoff_id)]
                    assert (recorded["work_id"], recorded["inputs"], recorded["observation_sources"]) == (
                        str(other.work_id), inputs, sources)
                    assert recorded["result"].startswith(f"{OUTWARD_PUBLIC} result [REDACTED_EMAIL]")
                    [found] = [f for f in view["findings"] if f["finding_id"] == str(finding.finding_id)]
                    assert (found["revision"], found["work_id"], found["handoff_id"], found["inputs"]) == (
                        1, str(other.work_id), str(handoff.handoff_id), inputs)
                    assert [f["finding_id"] for f in recorded["findings"]] == [str(finding.finding_id)]
                    [ack] = [a for a in view["acknowledgements"] if a["handoff_id"] == str(handoff.handoff_id)]
                    assert (ack["consumer_ref"], ack["expected_version"], ack["disposition"]) == (
                        "consumer [REDACTED_EMAIL]", ack_version, "ACCEPTED")
                    # Refreshes page events after the delivered cursor; the cancellation is in the initial page.
                    initial = json.loads(await page.evaluate("document.getElementById('relay-initial').textContent"))
                    assert any(e["kind"] == "CANCELLATION_REQUESTED" and (e["reason"] or "").startswith(
                        f"{OUTWARD_PUBLIC} cancel [REDACTED_EMAIL]") for e in initial["event_page"]["events"])
                    _assert_absent(payload, "Current snapshot", private)
                    await expect(page.get_by_test_id("event-timeline")).to_contain_text(f"{OUTWARD_PUBLIC} cancel")
                    await visit("Sources", f"{OUTWARD_PUBLIC} channel note")
                    async with page.expect_response(lambda r: "/inspect/" in urlsplit(r.url).path) as inspected:
                        await inspector.get_by_role("button", name="Demand evidence", exact=True).click()
                    response = await inspected.value
                    assert response.status == 200, "inspection did not succeed"
                    inspection = await response.text()
                    inspected_data = json.loads(inspection)
                    assert (inspected_data["mission_id"], inspected_data["run_id"]) == (mission_id, run_id)
                    assert (inspected_data["observation"]["observation_id"],
                            inspected_data["observation"]["source_id"]) == withdrawn
                    _assert_absent(inspection, "Inspection", private)
                    await expect(inspector).to_contain_text(str(signal.observation_id))
                    await expect(inspector).to_contain_text("Demand evidence")
                    _assert_absent(await page.evaluate("document.documentElement.outerHTML"), "Inspection DOM", private)
                    await visit("Research", f"{OUTWARD_PUBLIC} result", f"{OUTWARD_PUBLIC} question",
                                f"{OUTWARD_PUBLIC} execution", str(finding.finding_id),
                                f"Work {other.work_id} → consumer consumer [REDACTED_EMAIL] · {handoff.handoff_id}",
                                *(f"Observation {o['observation_id']} · source {o['source_id']}" for o in sources))
                    await visit("Cross-check", str(signal.observation_id))
                    await visit("Synthesis", f"{OUTWARD_PUBLIC} claim wording")
                    current_claims = inspector.get_by_test_id("current-claims").locator("article")
                    await expect(current_claims).to_have_count(1)
                    await expect(current_claims).to_contain_text(f"claim {claim.claim_id}")
                    await expect(inspector.get_by_test_id("claim-history").locator("article")).to_have_count(0)
                observed.assert_no_writes()

                # State 2: the existing fixture withdrawal invalidates current permission on the same mission.
                await _sql(case, "DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?",
                           (mission.id, signal.observation_id))
                before = _state(case)
                with _observe_chain(case, monkeypatch) as observed:
                    data, payload = await settled_snapshot()
                    for _ in range(2):  # a read already in flight at the withdrawal may still be current
                        if data["claim_gate"]["state"] != "CURRENT":
                            break
                        data, payload = await settled_snapshot()
                    gate = data["claim_gate"]
                    assert (data["mission_id"], data["run_id"]) == (mission_id, run_id)
                    assert data["counts"] == {"observations": 5, "sources": 5}
                    assert {(e["observation_id"], e["source_id"]) for e in data["evidence"]} == pairs - {withdrawn}
                    assert gate["state"] == "STALE" and gate["claims"] == []
                    assert [h["claim_id"] for h in gate["history"]] == [str(claim.claim_id)]
                    assert gate["history"][0]["wording"].startswith(f"{OUTWARD_PUBLIC} claim wording [REDACTED_EMAIL]")
                    assert gate["gap_report"]["failed_gates"] == ["MISSING_DEMAND_EVIDENCE"]
                    masked_window = f"{OUTWARD_PUBLIC} window [REDACTED_EMAIL]"
                    assert sorted((p["connector_surface"], p["status"], p["queried_window"])
                                  for p in gate["gap_report"]["attempted_probes"]) == [
                        ("google", "HEALTHY", masked_window), ("youtube", "HEALTHY", masked_window)]
                    _assert_absent(payload, "Withdrawn snapshot", private)
                    await visit("Synthesis", "Gap Report", "MISSING_DEMAND_EVIDENCE")
                    await expect(inspector.get_by_test_id("current-claims").locator("article")).to_have_count(0)
                    history = inspector.get_by_test_id("claim-history").locator("article")
                    await expect(history).to_have_count(1)
                    await expect(history).to_contain_text(f"claim {claim.claim_id}")
                    await expect(history).to_contain_text(f"{OUTWARD_PUBLIC} claim wording [REDACTED_EMAIL]")
                    gap = inspector.get_by_test_id("gap-report")
                    for surface in ("google", "youtube"):
                        await expect(gap).to_contain_text(f"Attempted probe: {surface} · HEALTHY · {masked_window}")
                    _assert_absent(await page.evaluate("document.documentElement.outerHTML"), "Synthesis ledger DOM", private)
                    await visit("Research", f"{OUTWARD_PUBLIC} result")
                observed.assert_no_writes()
                _assert_absent("\n".join(console), "Browser console", private)
                assert not unexpected and not errors, "Browser left loopback or raised a page error"
                await context.close()
            finally:
                await browser.close()
    owned.assert_closed_unchanged(case, before)
    captured = capsys.readouterr()
    diagnostics = dict(private, viewer_url=cap["url"])
    _assert_absent(caplog.text, "Captured logs", diagnostics)
    _assert_absent(captured.out + captured.err, "Captured output", diagnostics)


EXPIRED = {"schema_version": 1, "status": "REFUSED", "reason_code": "CAPABILITY_EXPIRED"}


def _exact_refusal(status, body, expected_status, payload, label, private):
    """Exact typed refusal, checked after a privacy guard; failures report only the label and expectation."""
    __tracebackhide__ = True
    _assert_absent(body.decode("utf-8", "replace"), label, private)
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None
    matched = status == expected_status and parsed == payload
    assert matched, f"{label}: expected {expected_status} {payload['reason_code']}"


def _raw(url, method, suffix):
    """One request on a raw socket, so a HEAD response is checked for bytes the server actually sent."""
    import socket
    target = urlsplit(url)
    with socket.create_connection((target.hostname, target.port), timeout=5) as sock:
        sock.sendall(f"{method} {target.path}{suffix} HTTP/1.1\r\nHost: {target.netloc}\r\n"
                     f"Connection: close\r\n\r\n".encode("ascii"))
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("ascii").split("\r\n")
    headers = dict(line.split(": ", 1) for line in lines[1:])
    return int(lines[0].split(" ")[1]), headers, body


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_actual_head_reads_and_real_clock_expiry_refuse_before_storage(attention_case, monkeypatch, tmp_path):
    from ignis.interfaces.mcp import server
    case, missions, runs = attention_case
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)

    def forbidden(*args, **kwargs):
        raise AssertionError("Viewer initialized writable components or credentials")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    owned = _OwnedRepository(monkeypatch, case)
    mission_id, run_id = str(missions[0].id), str(runs[0])
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            # A genuinely short real wall-clock capability; nothing patches time or the token.
            expires = datetime.now(timezone.utc) + timedelta(seconds=4)
            cap = (await client.call_tool("open_mission_relay", {"mission_id": mission_id, "run_id": run_id,
                                                                 "expires_at": expires.isoformat()})).structured_content
            # Exact checks are folded into booleans so a regression reports safe labels, never a payload or capability.
            opened = (cap["status"] == "OK" and datetime.fromisoformat(cap["expires_at"]) == expires
                      and (cap["mission_id"], cap["run_id"]) == (mission_id, run_id))
            assert opened, "MCP open did not return the exact selected scope and deadline"
            url = cap["url"]
            token = urlsplit(url).path.strip("/").split("/")[-1]
            private = {"capability_token": token}

            def before_deadline():
                # Setup guard, not product behavior: each pre-expiry request must start well inside the window.
                assert datetime.now(timezone.utc) < expires - timedelta(seconds=1), "Pre-expiry window consumed by setup"

            before_deadline()
            status, headers, body = await asyncio.to_thread(_raw, url, "GET", "snapshot?page_size=2")
            _assert_absent(body.decode("utf-8", "replace"), "Initial snapshot body", private)
            snapshot = json.loads(body)
            selected = status == 200 and (snapshot["mission_id"], snapshot["run_id"]) == (mission_id, run_id)
            assert selected, "Initial snapshot did not return the selected scope"
            observation = snapshot["evidence"][0]["observation_id"]
            routes = {"document": "", "snapshot": "snapshot?page_size=2", "inspect": f"inspect/{observation}?page_size=2"}
            for name, suffix in routes.items():
                before_deadline()
                status, got, body = await asyncio.to_thread(_raw, url, "GET", suffix)
                text = body.decode("utf-8", "replace")
                _assert_absent(text, f"{name} GET body", private)
                identified = status == 200 and mission_id in text and (name != "inspect" or observation in text)
                assert identified, f"{name}: GET did not return the selected identity"
                before_deadline()
                status, head, head_body = await asyncio.to_thread(_raw, url, "HEAD", suffix)
                bodiless = status == 200 and head_body == b""
                assert bodiless, f"{name}: HEAD sent a body or failed"
                for field in ("Content-Type", "Cache-Control", "Referrer-Policy", "X-Content-Type-Options"):
                    assert head.get(field) == got.get(field), f"{name}: HEAD {field} differs from GET"
                assert int(head["Content-Length"]) > 0
                assert ("Content-Security-Policy" in head) == (name == "document")
            # Unsupported forms with a valid capability: exact typed refusals, HEAD still bodiless.
            before_deadline()
            status, _, body = await asyncio.to_thread(_raw, url, "POST", "snapshot?page_size=2")
            _exact_refusal(status, body, 405, {"schema_version": 1, "status": "REFUSED",
                                               "reason_code": "METHOD_NOT_ALLOWED"}, "POST snapshot", private)
            before_deadline()
            status, head, head_body = await asyncio.to_thread(_raw, url, "HEAD", "?page_size=2")
            refused = (status, head_body, head.get("Content-Type")) == (400, b"", "application/json")
            assert refused, "HEAD document with a query was not a bodiless 400"
            reads = (len(observed.statements), len(observed.opens))
            assert reads[0] > 0 and reads[1] > 0, "The observer must see the successful physical reads"

            # Cross the explicit deadline once on the real clock (bounded by the 4 s window).
            await asyncio.sleep(max(0.0, (expires - datetime.now(timezone.utc)).total_seconds()) + 0.25)
            assert datetime.now(timezone.utc) > expires
            for name, suffix in routes.items():
                status, _, body = await asyncio.to_thread(_raw, url, "GET", suffix)
                _exact_refusal(status, body, 403, EXPIRED, f"{name} GET after expiry", private)
                status, head, head_body = await asyncio.to_thread(_raw, url, "HEAD", suffix)
                bodiless = status == 403 and head_body == b""
                assert bodiless, f"{name}: HEAD not refused after expiry"
                assert int(head["Content-Length"]) == len(json.dumps(EXPIRED, separators=(",", ":")))
            assert (len(observed.statements), len(observed.opens)) == reads, "An expired request reached storage"
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)
    assert await asyncio.to_thread(_refused_after_close, url), "Listener still accepts connections after shutdown"
