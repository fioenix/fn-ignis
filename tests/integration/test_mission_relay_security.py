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
