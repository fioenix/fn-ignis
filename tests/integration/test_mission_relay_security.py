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
