"""Task binding, missingness and replay safety for real host-search orchestration."""

import importlib
from datetime import datetime, timezone

import pytest


def test_staged_answer_expiry_refuses_acceptance_without_renewing_task(service, monkeypatch):
    from datetime import timedelta
    import ignis.application.use_cases.host_browser_search as module
    request = prepare(service)
    service.stage(request["request_id"], answer(request))
    deadline = datetime.fromisoformat(request["expires_at"]) + timedelta(seconds=1)
    class ExpiredClock:
        @staticmethod
        def now(zone):
            return deadline
    monkeypatch.setattr(module, "datetime", ExpiredClock)
    with pytest.raises(ValueError, match="expired"):
        service.submit(request["request_id"], "task-1", "chrome-1")


def test_restart_does_not_accept_prior_process_ticket(service):
    request = prepare(service)
    service.stage(request["request_id"], answer(request))
    service.close()
    with pytest.raises(ValueError, match="UNKNOWN_REQUEST"):
        service.submit(request["request_id"], "task-1", "chrome-1")


def service_type():
    try:
        return importlib.import_module(
            "ignis.application.use_cases.host_browser_search"
        ).HostBrowserSearchService
    except ModuleNotFoundError:
        pytest.fail("Host-browser search orchestration is not implemented")


@pytest.fixture
def service():
    class LazyService:
        instance = None

        def __getattr__(self, name):
            if self.instance is None:
                self.instance = service_type()()
            return getattr(self.instance, name)

    service = LazyService()
    yield service
    if service.instance is not None:
        service.instance.close()


def prepare(service, **overrides):
    inputs = dict(host_task_ref="task-1", session_ref="chrome-1", queries=["túi đi làm"],
                  result_limit=3, lifetime_seconds=60, authorized=True)
    inputs.update(overrides)
    return service.prepare(**inputs)


def answer(request, **overrides):
    query = request["queries"][0]
    payload = dict(request_id=request["request_id"], host_task_ref="task-1", session_ref="chrome-1",
                   extractor_version="tiktok-public-grid-v1", answers=[dict(
                       query_id=query["query_id"], query=query["query"], page_url=query["search_url"],
                       captured_at=datetime.now(timezone.utc).isoformat(), search_verified=True,
                       empty_state_visible=False, status="HEALTHY", records=[dict(
                           source_url="https://www.tiktok.com/@fixture/video/7417820067028536584",
                           excerpt="Túi đi làm", published_at=None,
                       )],
                   )])
    payload.update(overrides)
    return payload


def test_preparation_binds_exact_query_and_refuses_unbounded_or_unauthorized_scope(service):
    request = prepare(service)
    assert request["queries"][0]["search_url"] == "https://www.tiktok.com/search?q=t%C3%BAi%20%C4%91i%20l%C3%A0m"
    assert request["mode"] == "TACTICAL"
    for overrides in [dict(queries=[]), dict(result_limit=0), dict(lifetime_seconds=0), dict(authorized=False)]:
        with pytest.raises(ValueError):
            prepare(service, **overrides)


def test_tactical_result_retains_unknown_metrics_and_exact_provenance(service):
    request = prepare(service)
    payload = answer(request)
    service.stage(request["request_id"], payload)
    receipt = service.submit(request["request_id"], "task-1", "chrome-1")
    assert receipt["status"] == "ACCEPTED"
    assert receipt["mode"] == "TACTICAL"
    record = receipt["observations"][0]
    assert record["published_at"] is None
    assert record["metric_value"] is None
    assert record["query"] == "túi đi làm"
    assert record["collection_path"] == "host_browser:tiktok-public-grid-v1"
    assert "mission_id" not in receipt
    assert receipt["outcomes"][0]["queried_window"] is None
    assert service.submit(request["request_id"], "task-1", "chrome-1") == receipt


def test_host_excerpt_is_masked_before_receipt_and_not_retained_raw(service):
    request = prepare(service)
    payload = answer(request)
    payload["answers"][0]["records"][0]["excerpt"] = (
        "Túi đi làm 200000 VND; contact seller@example.test, 0931.405.002; api_key=fixture-token"
    )
    service.stage(request["request_id"], payload)
    retained = repr(service.instance._tickets[request["request_id"]])
    for sensitive in ("seller@example.test", "0931.405.002", "fixture-token"):
        assert sensitive not in retained
    receipt = service.submit(request["request_id"], "task-1", "chrome-1")
    record = receipt["observations"][0]
    assert record["excerpt"] == (
        "Túi đi làm 200000 VND; contact [REDACTED_EMAIL], [REDACTED_PHONE]; api_key=[REDACTED_SECRET]"
    )
    # The caller gets the content link without the poster's handle (Spec 015).
    assert record["source_url"] == "https://www.tiktok.com/share/video/7417820067028536584"
    assert record["query"] == "túi đi làm"


@pytest.mark.parametrize("mutation", ["task", "session", "page", "capture", "extra", "private", "empty"])
def test_invalid_answer_cannot_be_promoted_or_retried(service, mutation):
    request = prepare(service)
    payload = answer(request)
    if mutation == "task":
        payload["host_task_ref"] = "other-task"
    elif mutation == "session":
        payload["session_ref"] = "other-session"
    elif mutation == "page":
        payload["answers"][0]["page_url"] = "https://www.tiktok.com/search?q=wrong"
    elif mutation == "capture":
        payload["answers"][0]["captured_at"] = "2000-01-01T00:00:00Z"
    elif mutation == "extra":
        payload["cookies"] = "not-a-real-secret"
    elif mutation == "private":
        payload["answers"][0]["records"][0]["source_url"] = "https://www.tiktok.com/messages"
    elif mutation == "empty":
        payload["answers"][0].update(status="EMPTY_NO_DATA", records=[], empty_state_visible=False)
    with pytest.raises(ValueError):
        service.stage(request["request_id"], payload)
    with pytest.raises(ValueError):
        service.submit(request["request_id"], "task-1", "chrome-1")


def test_verified_empty_is_distinct_from_degraded_blank(service):
    for state, verified, empty in [("EMPTY_NO_DATA", True, True), ("DEGRADED", False, False)]:
        request = prepare(service)
        payload = answer(request)
        payload["answers"][0].update(status=state, records=[], search_verified=verified, empty_state_visible=empty)
        service.stage(request["request_id"], payload)
        result = service.submit(request["request_id"], "task-1", "chrome-1")
        assert result["outcomes"][0]["status"] == state


def test_cancel_and_wrong_submission_identity_preserve_boundaries(service):
    request = prepare(service)
    with pytest.raises(ValueError):
        service.cancel(request["request_id"], "other-task", "chrome-1")
    assert service.cancel(request["request_id"], "task-1", "chrome-1")["status"] == "CANCELLED"
    with pytest.raises(ValueError):
        service.submit(request["request_id"], "task-1", "chrome-1")


def test_batch_requires_one_answer_per_query_and_preserves_partial_failure(service):
    request = prepare(service, queries=["túi đi làm", "túi laptop"])
    payload = answer(request)
    second = request["queries"][1]
    payload["answers"].append(dict(query_id=second["query_id"], query=second["query"],
                                 page_url=second["search_url"], captured_at=datetime.now(timezone.utc).isoformat(),
                                 search_verified=False, empty_state_visible=False, status="DEGRADED", records=[]))
    service.stage(request["request_id"], payload)
    result = service.submit(request["request_id"], "task-1", "chrome-1")
    assert [outcome["status"] for outcome in result["outcomes"]] == ["HEALTHY", "DEGRADED"]
    assert len(result["observations"]) == 1


def test_host_excerpt_loses_the_poster_attribution_before_the_receipt(service):
    """The 26/10/2026 trial returned twelve excerpts that each ended in the poster's name (FR-012)."""
    request = prepare(service)
    payload = answer(request)
    payload["answers"][0]["records"][0]["excerpt"] = (
        "Túi đi làm siêu gọn #tuidilam do Fixture Poster tạo với bản nhạc âm thanh gốc - Fixture Poster"
    )
    service.stage(request["request_id"], payload)
    assert "Fixture Poster" not in repr(service.instance._tickets[request["request_id"]])
    receipt = service.submit(request["request_id"], "task-1", "chrome-1")
    assert receipt["observations"][0]["excerpt"] == "Túi đi làm siêu gọn #tuidilam"


def test_a_label_that_was_only_attribution_is_not_content(service):
    request = prepare(service)
    payload = answer(request)
    payload["answers"][0]["records"][0]["excerpt"] = "do Fixture Poster tạo với bản nhạc âm thanh gốc"
    service.stage(request["request_id"], payload)
    receipt = service.submit(request["request_id"], "task-1", "chrome-1")
    assert receipt["observations"] == []
    assert receipt["outcomes"][0]["status"] == "DEGRADED"
    assert receipt["outcomes"][0]["signals_collected"] == 0


def test_preparation_without_attribution_vocabulary_fails_closed():
    service = service_type()(attribution_templates=())
    try:
        with pytest.raises(ValueError, match="attribution"):
            prepare(service)
    finally:
        service.close()


def test_preparation_returns_the_relay_tab_script(service):
    """Browser tooling may refuse to read the script back from the page, so preparation hands it over."""
    import html
    from urllib.request import urlopen

    request = prepare(service)
    with urlopen(request["relay_url"], timeout=3) as response:
        page = response.read().decode()
    shown = page.split('<textarea id="tab-script" readonly rows="5">', 1)[1].split("</textarea>", 1)[0]
    assert request["tab_script"]
    assert html.unescape(shown) == request["tab_script"]
    assert request["relay_url"].rstrip("/").rsplit("/", 1)[0] in request["tab_script"]


def test_a_batch_cannot_repeat_a_query(service):
    """The tab script binds a tab to its query by text, so a repeated query could never stage."""
    with pytest.raises(ValueError, match="once"):
        prepare(service, queries=["túi đi làm", "túi đi làm"])


def test_threads_tactical_ticket_checks_original_caller_and_expiry(service, monkeypatch):
    from datetime import timedelta
    from ignis.application.use_cases import host_browser_search as module
    from ignis.infrastructure.caller_storage import current_caller_storage
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    token = current_caller_storage.set(object())
    try:
        original = current_caller_storage.get()
        request = prepare(service, source="threads")
        service.stage(request["request_id"], host_answer(request))
        current_caller_storage.set(object())
        with pytest.raises(ValueError, match="caller"):
            service.submit(request["request_id"], "task-1", "chrome-1")
        current_caller_storage.set(original)
        class Clock(datetime):
            @classmethod
            def now(cls, zone=None):
                return datetime.fromisoformat(request["expires_at"]) + timedelta(seconds=1)
        monkeypatch.setattr(module, "datetime", Clock)
        with pytest.raises(ValueError, match="expired"):
            service.submit(request["request_id"], "task-1", "chrome-1")
        assert service.instance._tickets[request["request_id"]]["receipt"] is None
    finally:
        current_caller_storage.reset(token)
