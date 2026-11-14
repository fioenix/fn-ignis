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
                   extractor_version="tiktok-public-grid-v4", answers=[dict(
                       query_id=query["query_id"], query=query["query"], page_url=query["search_url"],
                       captured_at=datetime.now(timezone.utc).isoformat(), search_verified=True,
                       empty_state_visible=False, status="HEALTHY", locale="vi", records=[dict(
                           source_url="https://www.tiktok.com/@fixture/video/7417820067028536584",
                           excerpt="Túi đi làm", published_at=None,
                       )],
                   )])
    payload.update(overrides)
    return payload


def test_preparation_binds_exact_query_and_refuses_unbounded_or_unauthorized_scope(service):
    request = prepare(service)
    assert request["queries"][0]["search_url"] == "https://www.tiktok.com/search/video?q=t%C3%BAi%20%C4%91i%20l%C3%A0m"
    assert request["mode"] == "TACTICAL"
    for overrides in [dict(queries=[]), dict(result_limit=0), dict(lifetime_seconds=0), dict(authorized=False),
                      dict(result_limit=101), dict(lifetime_seconds=3601),
                      dict(queries=[f"query {index}" for index in range(33)])]:
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
    # FR-007: the TikTok video id carries the publish second; metrics stay unknown.
    assert record["published_at"] == "2024-09-23T12:50:20+00:00"
    assert record["metric_value"] is None
    assert record["query"] == "túi đi làm"
    assert record["collection_path"] == "host_browser:tiktok-public-grid-v4"
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
        payload["answers"][0]["page_url"] = "https://www.tiktok.com/search/video?q=wrong"
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


def test_t058_tactical_missing_locale_vocabulary_refuses_before_relay(monkeypatch):
    from unittest.mock import Mock
    from ignis.application.use_cases import host_browser_search as module

    relay = Mock(side_effect=AssertionError("Missing locales must refuse before relay creation"))
    monkeypatch.setattr(module, "LoopbackRelay", relay)
    service = module.HostBrowserSearchService()
    try:
        with pytest.raises(module.AttributionVocabularyMissing, match="attribution"):
            prepare(service, attribution_locales={})
        relay.assert_not_called()
        assert service._tickets == {}
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


@pytest.mark.parametrize("locale", [None, "en", "unsupported", "VI", "vi_VN"])
def test_v3_locale_never_gates_records(locale):
    from datetime import timedelta
    from ignis.domain.host_browser_search import HostSearchRequest, HostSearchQuery
    from ignis.infrastructure.connectors.host_browser.validator import validate_answer
    now = datetime.now(timezone.utc)
    request = HostSearchRequest(request_id="fixture", host_task_ref="task-1", session_ref="chrome-1",
        issued_at=now - timedelta(seconds=1), expires_at=now + timedelta(seconds=60),
        queries=(HostSearchQuery(query_id="q", query="test", search_url="https://www.tiktok.com/search/video?q=test", result_limit=3),))
    payload = answer({"request_id": "fixture", "queries": [{"query_id": "q", "query": "test", "search_url": "https://www.tiktok.com/search/video?q=test"}]})
    item = payload["answers"][0]
    item.update(locale=locale, status="HEALTHY", empty_state_visible=False)
    item["records"][0]["excerpt"] = "Caption"
    sidecar = []
    result = validate_answer(request, payload, datetime.now(timezone.utc), ("do {author} tạo với",), author_records=sidecar)
    assert [item["excerpt"] for item in result["observations"]] == [item["excerpt"] for item in sidecar] == ["Caption"]
    [outcome] = result["outcomes"]
    assert outcome["status"] == "HEALTHY"


@pytest.mark.parametrize("page,accepted", [
    ("https://www.tiktok.com/search/video?q=test", True),
    ("https://www.tiktok.com/search?q=test", False),
])
def test_t060_tiktok_answers_must_come_from_the_video_results_page(page, accepted):
    from datetime import timedelta
    from ignis.domain.host_browser_search import HostSearchRequest, HostSearchQuery
    from ignis.infrastructure.connectors.host_browser.validator import validate_answer
    now = datetime.now(timezone.utc)
    url = "https://www.tiktok.com/search/video?q=test"
    request = HostSearchRequest(request_id="fixture", host_task_ref="task-1", session_ref="chrome-1",
        issued_at=now - timedelta(seconds=1), expires_at=now + timedelta(seconds=60),
        queries=(HostSearchQuery(query_id="q", query="test", search_url=url, result_limit=3),))
    payload = answer({"request_id": "fixture", "queries": [{"query_id": "q", "query": "test", "search_url": url, "result_limit": 3}]})
    payload["answers"][0]["page_url"] = page
    if accepted:
        assert validate_answer(request, payload, datetime.now(timezone.utc), ("do {author} tạo với",))["outcomes"]
    else:
        with pytest.raises(ValueError, match="does not match"):
            validate_answer(request, payload, datetime.now(timezone.utc), ("do {author} tạo với",))


def test_tiktok_publication_stays_unknown_when_the_record_has_no_video_id(service):
    request = prepare(service)
    payload = answer(request)
    payload["answers"][0]["records"][0]["source_url"] = None
    service.stage(request["request_id"], payload)
    record = service.submit(request["request_id"], "task-1", "chrome-1")["observations"][0]
    assert record["published_at"] is None


def test_a_host_supplied_tiktok_publication_time_is_kept_over_the_id(service):
    request = prepare(service)
    payload = answer(request)
    payload["answers"][0]["records"][0]["published_at"] = "2024-09-24T00:00:00+00:00"
    service.stage(request["request_id"], payload)
    record = service.submit(request["request_id"], "task-1", "chrome-1")["observations"][0]
    assert record["published_at"] == "2024-09-24T00:00:00+00:00"


@pytest.mark.parametrize("source", ["tiktok", "threads", "instagram"])
def test_tab_script_is_compacted_because_agents_retype_it(service, source):
    """The host agent copies tab_script verbatim, so indentation and comment lines cost wall time."""
    from importlib.resources import files

    script = prepare(service, source=source)["tab_script"]
    packaged = files("ignis.infrastructure.connectors.host_browser")
    raw = sum(len(packaged.joinpath(source + suffix).read_text()) for suffix in ("_search.js", "_handoff.js"))
    lines = script.split("\n")
    assert all(line == line.strip() for line in lines)
    assert not any(line.startswith("//") for line in lines)
    assert len(script) < raw


def test_packaged_scripts_stay_safe_to_compact():
    """Compaction strips each line, so a template literal or a line continuation would change meaning."""
    from importlib.resources import files

    for script in files("ignis.infrastructure.connectors.host_browser").iterdir():
        if script.name.endswith(".js"):
            text = script.read_text()
            assert "`" not in text, script.name
            assert not any(line.rstrip().endswith("\\") for line in text.splitlines()), script.name
            assert "/*" not in text, script.name
            assert not set(text) & set("\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"), script.name


# --- ENG-6: restart expiry and attribution-locale health ---


def _restarted(service):
    """A new service instance is what a restarted MCP server holds: an empty ticket table."""
    service.close()
    restarted = service_type()()
    return restarted


def test_a_ticket_left_pending_across_restart_expires_on_access(service):
    request = prepare(service)
    restarted = _restarted(service)
    try:
        for call in (restarted.submit, restarted.cancel, restarted.mode):
            with pytest.raises(ValueError, match="EXPIRED_ON_RESTART") as error:
                call(request["request_id"], "task-1", "chrome-1")
            failure = error.value.host_search_failure
            assert failure["status"] == "EXPIRED_ON_RESTART"
            assert failure["request_id"] == request["request_id"]
            assert "observations" not in failure
    finally:
        restarted.close()


def test_restart_expiry_never_claims_an_id_this_process_could_not_have_issued(service):
    from uuid import uuid4
    for request_id in (str(uuid4()), "not-a-uuid", ""):
        with pytest.raises(ValueError, match="UNKNOWN_REQUEST"):
            service.submit(request_id, "task-1", "chrome-1")


def test_a_staged_answer_lost_to_restart_is_not_accepted(service):
    request = prepare(service)
    service.stage(request["request_id"], answer(request))
    restarted = _restarted(service)
    try:
        with pytest.raises(ValueError, match="EXPIRED_ON_RESTART"):
            restarted.submit(request["request_id"], "task-1", "chrome-1")
    finally:
        restarted.close()


@pytest.mark.asyncio
async def test_mcp_handlers_return_the_typed_restart_status(service, monkeypatch):
    from ignis.interfaces.mcp import server
    request = prepare(service)
    restarted = _restarted(service)
    monkeypatch.setattr(server, "_host_browser_search_service", restarted)
    try:
        submitted = await server.handle_submit_host_browser_search(request["request_id"], "task-1", "chrome-1")
        cancelled = await server.handle_cancel_host_browser_search(request["request_id"], "task-1", "chrome-1")
        assert submitted["status"] == cancelled["status"] == "EXPIRED_ON_RESTART"
        assert submitted["reason_code"] == "HOST_SEARCH_EXPIRED_ON_RESTART"
    finally:
        restarted.close()


def test_a_staged_answer_records_the_page_locale_it_observed(service):
    assert service.observed_page_locales() == {}
    request = prepare(service)
    payload = answer(request)
    payload["answers"][0]["locale"] = "en"
    service.stage(request["request_id"], payload)
    observed = service.observed_page_locales()["tiktok"]
    assert observed["locales"] == ["en"]
    assert datetime.fromisoformat(observed["observed_at"]).tzinfo is not None


def test_a_rejected_answer_records_no_page_locale(service):
    request = prepare(service)
    payload = answer(request, host_task_ref="other-task")
    with pytest.raises(ValueError):
        service.stage(request["request_id"], payload)
    assert service.observed_page_locales() == {}


def test_locale_report_compares_seeded_vocabulary_with_the_observed_page_locale(service):
    rows = [dict(domain="tiktok_attribution_vi", term="do {author} tạo với", category="ui_attribution"),
            dict(domain="instagram_attribution_vi", term="Ảnh của {author} vào", category="ui_attribution")]
    observed = {"instagram": {"locales": ["en", "unsupported"], "observed_at": "2026-11-14T00:00:00+00:00"}}
    report = service.attribution_locale_report(rows, observed)
    assert report["tiktok"] == dict(seeded=["vi"], observed=[], observed_at=None, unseeded=[])
    assert report["instagram"] == dict(seeded=["vi"], observed=["en", "unsupported"],
                                       observed_at="2026-11-14T00:00:00+00:00", unseeded=["en"])
    assert "threads" not in report


def test_locale_report_flags_malformed_vocabulary_instead_of_failing(service):
    rows = [dict(domain="instagram_attribution_vi", term="no placeholder", category="ui_attribution")]
    report = service.attribution_locale_report(rows, {})
    assert report["instagram"] == dict(error="INVALID_ATTRIBUTION_VOCABULARY")
    assert report["tiktok"]["seeded"] == []


@pytest.mark.asyncio
async def test_health_reports_seeded_and_observed_attribution_locales(service, monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from ignis.interfaces.mcp import server
    repo = Mock()
    repo.get_recent_logs = AsyncMock(return_value=[])
    repo.get_domain_lexicons = AsyncMock(return_value=[
        dict(domain="instagram_attribution_vi", term="Ảnh của {author} vào", category="ui_attribution")])
    registry = Mock()
    registry.get_health_status.return_value = {}
    monkeypatch.setattr(server, "get_components", lambda: {"registry": registry, "repository": repo})
    monkeypatch.setattr(server, "_host_browser_search_service", service)
    service._observed_locales["instagram"] = {"locales": ["en"], "observed_at": "2026-11-14T00:00:00+00:00"}
    import json
    diagnostics = json.loads(await server.handle_diagnose_system_health())
    assert diagnostics["status"] == "HEALTHY"
    assert diagnostics["host_browser_attribution_locales"]["instagram"]["unseeded"] == ["en"]
    assert any("Instagram" in item and "'en'" in item for item in diagnostics["recommendations"])
