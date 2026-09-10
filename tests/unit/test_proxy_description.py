"""The health report names the proxy; it must not repeat the credentials in its URI."""

import pytest

from ignis.interfaces.mcp.server import _describe_proxy


def test_unset_proxy_reads_as_direct():
    assert _describe_proxy("") == "Direct (No Proxy)"


def test_credentials_are_replaced_with_a_marker():
    described = _describe_proxy("http://operator:hunter2@proxy.example.com:8080")

    assert "hunter2" not in described
    assert "operator" not in described
    assert "proxy.example.com:8080" in described
    assert "<redacted>" in described


def test_a_proxy_without_credentials_is_reported_in_full():
    assert _describe_proxy("socks5://proxy.example.com:1080") == "socks5://proxy.example.com:1080"


def test_a_password_only_uri_is_still_redacted():
    described = _describe_proxy("http://:hunter2@proxy.example.com:8080")

    assert "hunter2" not in described


@pytest.mark.parametrize("value", ["not-a-uri", "http://", "@@@"])
def test_an_unparseable_value_is_reported_without_being_echoed(value):
    described = _describe_proxy(value)

    assert described == "Configured (unparseable URI)" or value not in described
