"""Retired private Threads Relay/Playwright collection has no code path left."""
from ignis.infrastructure.connectors import meta_browser_ingress as ingress


def test_retired_threads_page_capture_and_relay_are_removed():
    assert not hasattr(ingress, "collect_json_payloads")
    assert not hasattr(ingress, "THREADS_SEARCH_RELAY_EXTRACTOR")
    assert not hasattr(ingress, "collect_threads_search_suggestions_via_browser")
