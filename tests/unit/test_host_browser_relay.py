"""Exercise the real loopback transport, not a mocked browser or server."""

import importlib
import http.client
import json
import socket
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
