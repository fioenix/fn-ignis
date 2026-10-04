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
    assert record["source_url"] == "https://www.tiktok.com/@fixture/video/7417820067028536584"
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
