"""Spec 020 foundation: source-bound browser envelopes and honest counter components."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ignis.domain.host_browser_search import HostPublicRecord, HostSearchAnswer, HostSearchRequest

CLOCK = "2026-10-28T01:02:03.123456Z"


def request_data(**overrides):
    data = dict(request_id="request", host_task_ref="task", session_ref="session",
                issued_at="2026-10-28T01:00:00+00:00", expires_at="2026-10-28T01:30:00+00:00",
                queries=[dict(query_id="q1", query="synthetic query",
                              search_url="https://www.tiktok.com/search?q=synthetic%20query", result_limit=20)])
    data.update(overrides)
    return data


def record_data(**overrides):
    data = dict(source_url="https://www.threads.com/t/Synthetic020", excerpt="Synthetic body",
                published_at=CLOCK)
    data.update(overrides)
    return data


def answer_data(source=None, **overrides):
    data = dict(request_id="request", host_task_ref="task", session_ref="session",
                extractor_version="tiktok-public-grid-v1" if source is None else "threads-search-top-v2",
                answers=[dict(query_id="q1", query="synthetic query", page_url="https://www.threads.com/search?q=synthetic%20query",
                              captured_at=CLOCK, search_verified=True, empty_state_visible=False,
                              status="HEALTHY", records=[record_data()])])
    if source is not None:
        data["source"] = source
    data.update(overrides)
    return data


def counter(**overrides):
    data = dict(kind="likes", unit="count", raw_display="12", value=12, precision="exact")
    data.update(overrides)
    return data


def test_legacy_tiktok_envelopes_keep_their_default_source_and_wire_shape():
    request = HostSearchRequest.model_validate(request_data())
    legacy = answer_data()
    answer = HostSearchAnswer.model_validate(legacy)
    assert request.source == answer.source == "tiktok"
    assert request.extractor_version == answer.extractor_version == "tiktok-public-grid-v1"
    assert "source" not in request.model_dump(mode="json")
    assert answer.model_dump(mode="json") == legacy


def test_threads_request_and_answer_freeze_matching_source_and_version():
    request = HostSearchRequest.model_validate(request_data(source="threads"))
    answer = HostSearchAnswer.model_validate(answer_data("threads"), context={"request": request})
    assert request.source == answer.source == "threads"
    assert request.extractor_version == answer.extractor_version == "threads-search-top-v2"
    assert request.model_dump(mode="json")["source"] == "threads"
    for envelope in (request, answer):
        for field, value in (("source", "tiktok"), ("extractor_version", "tiktok-public-grid-v1")):
            with pytest.raises(ValidationError, match="frozen"):
                setattr(envelope, field, value)


@pytest.mark.parametrize("source,version", [
    ("instagram", "threads-search-top-v2"), ("threads", "tiktok-public-grid-v1"),
    ("tiktok", "threads-search-top-v2"), ("threads", "threads-mcp-keyword-v1"),
    ("threads", "threads-search-top-v1"),
])
def test_unsupported_or_cross_source_versions_are_not_browser_envelopes(source, version):
    with pytest.raises(ValidationError):
        HostSearchRequest.model_validate(request_data(source=source, extractor_version=version))
    with pytest.raises(ValidationError):
        HostSearchAnswer.model_validate(answer_data(source, extractor_version=version))


@pytest.mark.parametrize("request_source,answer_source", [("threads", None), ("tiktok", "threads")])
def test_answer_context_refuses_legacy_or_other_source_on_the_wrong_ticket(request_source, answer_source):
    request = HostSearchRequest.model_validate(request_data(source=request_source))
    with pytest.raises(ValidationError, match="source"):
        HostSearchAnswer.model_validate(answer_data(answer_source), context={"request": request})


def test_exact_publication_clock_round_trips_without_capture_substitution():
    record = HostPublicRecord.model_validate(record_data(counters=[counter()]))
    assert record.published_at == datetime(2026, 10, 28, 1, 2, 3, 123456, tzinfo=timezone.utc)
    assert record.model_dump(mode="json")["published_at"] == "2026-10-28T01:02:03.123456Z"
    assert HostPublicRecord.model_validate(record_data(published_at=None)).published_at is None
    with pytest.raises(ValidationError):
        HostPublicRecord.model_validate(record_data(published_at="2026-10-28T01:02:03"))
    with pytest.raises(ValidationError):
        HostPublicRecord.model_validate(record_data(published_at="2 hours ago"))


def test_components_preserve_raw_display_unit_precision_and_shares_without_quotes_alias():
    record = HostPublicRecord.model_validate(record_data(counters=[
        counter(), counter(kind="replies", raw_display="1.4K", value=1400, precision="rounded"),
        counter(kind="reposts", raw_display="", value=None, precision="unknown"),
        counter(kind="shares", raw_display="0", value=0),
    ]))
    assert record.model_dump(mode="json")["counters"] == [
        counter(), counter(kind="replies", raw_display="1.4K", value=1400, precision="rounded"),
        counter(kind="reposts", raw_display="", value=None, precision="unknown"),
        counter(kind="shares", raw_display="0", value=0),
    ]
    assert {component.kind for component in record.counters} == {"likes", "replies", "reposts", "shares"}
    assert record.counters[2].value is None and record.counters[3].value == 0


@pytest.mark.parametrize("changes", [
    {"kind": "quotes"}, {"kind": "views"}, {"unit": "percent"}, {"precision": "estimated"},
    {"value": -1}, {"value": True}, {"value": 1.5}, {"value": "12"}, {"value": float("inf")},
    {"value": None}, {"precision": "unknown"}, {"raw_display": ""},
])
def test_malformed_or_falsely_exact_counters_are_rejected(changes):
    with pytest.raises(ValidationError):
        HostPublicRecord.model_validate(record_data(counters=[counter(**changes)]))


def test_unknown_unrecognized_display_is_retained_without_a_numeric_claim():
    record = HostPublicRecord.model_validate(record_data(counters=[counter(raw_display="unrecognized",
                                                                         value=None, precision="unknown")]))
    assert record.counters[0].raw_display == "unrecognized"
    assert record.counters[0].value is None


def test_duplicate_components_and_unknown_record_fields_are_refused():
    with pytest.raises(ValidationError):
        HostPublicRecord.model_validate(record_data(counters=[counter(), counter()]))
    with pytest.raises(ValidationError):
        HostPublicRecord.model_validate(record_data(author="Synthetic Sentinel"))
    with pytest.raises(ValidationError):
        HostPublicRecord.model_validate(record_data(counters=[counter(author="Synthetic Sentinel")]))


@pytest.mark.parametrize("count", [0, 33])
def test_request_query_bounds_apply_to_both_sources(count):
    queries = request_data()["queries"] * count
    for source in ("tiktok", "threads"):
        with pytest.raises(ValidationError):
            HostSearchRequest.model_validate(request_data(source=source, queries=queries))


def test_record_and_per_query_bounds_remain_finite_for_threads():
    data = request_data(source="threads")
    data["queries"][0]["result_limit"] = 101
    with pytest.raises(ValidationError):
        HostSearchRequest.model_validate(data)
    payload = answer_data("threads")
    payload["answers"][0]["records"] *= 101
    with pytest.raises(ValidationError):
        HostSearchAnswer.model_validate(payload)
    with pytest.raises(ValidationError):
        HostPublicRecord.model_validate(record_data(excerpt="x" * 2001))


def test_current_validator_rejects_a_threads_header_on_a_tiktok_ticket():
    from ignis.infrastructure.connectors.host_browser.validator import validate_answer

    request = HostSearchRequest.model_validate(request_data())
    payload = answer_data("threads")
    payload["answers"][0]["page_url"] = request.queries[0].search_url
    payload["answers"][0]["records"][0]["source_url"] = "https://www.tiktok.com/@synthetic/video/7417820067028536584"
    with pytest.raises(ValidationError, match="source"):
        validate_answer(request, payload, datetime(2026, 10, 28, 1, 3, tzinfo=timezone.utc))


@pytest.fixture
def threads_service(monkeypatch):
    from ignis.application.use_cases import host_browser_search as module
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    service = module.HostBrowserSearchService()
    yield service
    service.close()


def threads_request(service, **overrides):
    inputs = dict(host_task_ref="task", session_ref="session", queries=["synthetic query"], result_limit=3,
                  lifetime_seconds=60, authorized=True, source="threads")
    inputs.update(overrides)
    return service.prepare(**inputs)


def test_threads_staging_removes_identity_and_keeps_exact_clock_counters_and_path(threads_service):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service)
    assert request["queries"][0]["search_url"] == "https://www.threads.com/search?q=synthetic%20query"
    threads_service.stage(request["request_id"], host_answer(request))
    assert "synthetic.header" not in repr(threads_service._tickets)
    assert "Synthetic Other Person" not in repr(threads_service._tickets)
    receipt = threads_service.submit(request["request_id"], "task", "session")
    assert threads_service.submit(request["request_id"], "task", "session") == receipt
    record = receipt["observations"][0]
    assert record["source_url"] == "https://www.threads.com/t/Synthetic020Q0"
    assert "synthetic.mention" not in record["excerpt"]
    assert record["published_at"] == "2026-10-27T01:02:03.123456+00:00"
    assert record["counters"][0]["precision"] == "rounded" and record["counters"][1]["value"] is None
    assert record["collection_path"] == "host_browser:threads-search-top-v2"
    assert receipt["outcomes"][0]["sampling"]["limit"] == 3


@pytest.mark.parametrize("mutation", ["origin", "port", "route", "filter", "fragment", "missing", "extra", "duplicate",
                                       "oversize", "past", "future", "locale", "empty", "record-route", "version"])
def test_threads_bad_scope_refuses_entire_batch_without_collectible_receipt(threads_service, mutation):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service, queries=["synthetic query", "falsifier"])
    payload = host_answer(request)
    answer = payload["answers"][0]
    if mutation == "origin":
        answer["page_url"] = answer["page_url"].replace("www.threads.com", "threads.net")
    elif mutation == "port":
        answer["page_url"] = answer["page_url"].replace("www.threads.com", "www.threads.com:443")
    elif mutation == "route":
        answer["page_url"] = answer["page_url"].replace("/search?", "/profile?")
    elif mutation == "filter":
        answer["page_url"] += "&filter=recent"
    elif mutation == "fragment":
        answer["page_url"] += "#fragment"
    elif mutation == "missing":
        payload["answers"].pop()
    elif mutation == "extra":
        payload["answers"].append(answer)
    elif mutation == "duplicate":
        payload["answers"][1] = answer
    elif mutation == "oversize":
        answer["records"] *= 4
    elif mutation == "past":
        answer["captured_at"] = "2000-01-01T00:00:00Z"
    elif mutation == "future":
        answer["captured_at"] = "2099-01-01T00:00:00Z"
    elif mutation == "locale":
        answer["locale"] = "en-US"
    elif mutation == "empty":
        answer.update(status="EMPTY_NO_DATA", records=[], empty_state_visible=True)
    elif mutation == "record-route":
        answer["records"][0]["source_url"] = "https://www.threads.com/@synthetic.header"
    else:
        payload["extractor_version"] = "threads-mcp-keyword-v1"
    with pytest.raises(ValueError):
        threads_service.stage(request["request_id"], payload)
    with pytest.raises(ValueError):
        threads_service.submit(request["request_id"], "task", "session")


def test_threads_all_attribution_dropped_is_degraded_not_empty(threads_service):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service)
    payload = host_answer(request)
    payload["answers"][0]["records"][0]["excerpt"] = "Photo by Synthetic Other Person on October 27"
    threads_service.stage(request["request_id"], payload)
    receipt = threads_service.submit(request["request_id"], "task", "session")
    assert receipt["observations"] == [] and receipt["outcomes"][0]["status"] == "DEGRADED"


def test_threads_missing_vocabulary_never_opens_a_relay(threads_service, monkeypatch):
    from ignis.application.use_cases import host_browser_search as module
    threads_service.register_attribution_templates([], source="threads")
    monkeypatch.setattr(module, "LoopbackRelay", lambda *args: pytest.fail("Relay opened without vocabulary"))
    with pytest.raises(module.AttributionVocabularyMissing):
        threads_request(threads_service)


def test_threads_missing_content_reference_is_explicit_context(threads_service):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service)
    threads_service.stage(request["request_id"], host_answer(request, context=True))
    receipt = threads_service.submit(request["request_id"], "task", "session")
    assert receipt["observations"][0]["source_url"] is None
    assert receipt["observations"][0]["source_verifiable"] is False


@pytest.mark.parametrize("mixed", [False, True])
def test_unsupported_threads_locale_is_recorded_as_degraded(threads_service, mixed):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service, queries=["synthetic query", "falsifier"] if mixed else ["synthetic query"])
    payload = host_answer(request)
    payload["answers"][0].update(locale="unsupported", status="DEGRADED", search_verified=False, records=[])
    threads_service.stage(request["request_id"], payload)
    receipt = threads_service.submit(request["request_id"], "task", "session")
    assert receipt["status"] == "ACCEPTED"
    outcome = receipt["outcomes"][0]
    assert outcome["status"] == "DEGRADED" and outcome["signals_collected"] == 0
    assert outcome["search_verified"] is False
    assert "page locale is unsupported" in outcome["note"].lower()
    assert outcome["collection_path"] == "host_browser:threads-search-top-v2"
    assert len(receipt["observations"]) == int(mixed)
    if mixed:
        assert receipt["outcomes"][1]["status"] == "HEALTHY"
        assert receipt["outcomes"][1]["note"] == "Bounded visible Top sample; rounded and unknown counters retained"
    assert threads_service.submit(request["request_id"], "task", "session") == receipt


@pytest.mark.parametrize("changes", [
    {"status": "HEALTHY"}, {"status": "EMPTY_NO_DATA", "empty_state_visible": True},
    {"search_verified": True}, {"records": [record_data()]},
    {"status": "HEALTHY", "search_verified": True, "records": [record_data()]},
    {"search_verified": True, "records": [record_data()]},
    {"locale": "en-US"}, {"locale": ""}, {"locale": None},
])
def test_unsupported_threads_locale_cannot_claim_measurement(threads_service, changes):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service)
    payload = host_answer(request, degraded=True)
    payload["answers"][0].update(locale="unsupported")
    payload["answers"][0].update(changes)
    with pytest.raises(ValueError):
        threads_service.stage(request["request_id"], payload)
    with pytest.raises(ValueError):
        threads_service.submit(request["request_id"], "task", "session")


@pytest.mark.parametrize("source", ["threads", "tiktok"])
@pytest.mark.parametrize("status", ["HEALTHY", "DEGRADED", "EMPTY_NO_DATA"])
def test_english_threads_and_legacy_tiktok_outcomes_keep_their_contract(threads_service, source, status):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service, source=source)
    payload = host_answer(request, empty=status == "EMPTY_NO_DATA", degraded=status == "DEGRADED")
    if source == "threads" and status == "EMPTY_NO_DATA":
        with pytest.raises(ValueError):
            threads_service.stage(request["request_id"], payload)
        return
    threads_service.stage(request["request_id"], payload)
    receipt = threads_service.submit(request["request_id"], "task", "session")
    outcome = receipt["outcomes"][0]
    assert outcome["status"] == status
    assert outcome["signals_collected"] == (1 if status == "HEALTHY" else 0)
    assert len(receipt["observations"]) == (1 if status == "HEALTHY" else 0)
    assert outcome["note"] == ("Bounded visible Top sample; rounded and unknown counters retained"
                               if source == "threads" else
                               "Bounded visible public video grid; window and counters unmeasured")
    if source == "tiktok":
        assert "source" not in receipt and "collection_path" not in outcome


@pytest.mark.parametrize("locale,raw,value,precision", [
    ("vi", "Thích1,4K", 1400, "rounded"), ("en", "Like4.1K", 4100, "rounded"),
    ("vi", "Thích1,25M", 1250000, "rounded"), ("vi", "Thích1.2345K", 1235, "rounded"),
    ("vi", "Thích", None, "unknown"), ("th", "123", None, "unknown"),
    ("vi", "Thích" + "9" * 40 + "M", None, "unknown"),
])
def test_locale_labels_validate_measurements_and_unknown_locale_notes(threads_service, locale, raw, value, precision):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service)
    payload = host_answer(request)
    payload["answers"][0]["locale"] = locale
    payload["answers"][0]["records"][0]["counters"] = [counter(raw_display=raw, value=value, precision=precision)]
    threads_service.stage(request["request_id"], payload)
    receipt = threads_service.submit(request["request_id"], "task", "session")
    assert receipt["observations"][0]["counters"][0]["value"] == value
    if locale == "th":
        assert "unmeasured" in receipt["outcomes"][0]["note"]


@pytest.mark.parametrize("locale,raw,value,precision", [
    ("th", "12", 12, "exact"), ("vi", "Thích1,4K", 1400, "exact"),
    ("vi", "Thích1,4K", 1401, "rounded"), ("vi", "Reply12", 12, "exact"),
])
def test_locale_cannot_promote_unknown_or_rounded_measurements(threads_service, locale, raw, value, precision):
    from tests.fixtures.meta_host_browser_answers import host_answer
    request = threads_request(threads_service)
    payload = host_answer(request)
    payload["answers"][0]["locale"] = locale
    payload["answers"][0]["records"][0]["counters"] = [counter(raw_display=raw, value=value, precision=precision)]
    with pytest.raises(ValueError):
        threads_service.stage(request["request_id"], payload)


def test_ticket_freezes_caller_action_labels_for_validation(threads_service):
    from tests.fixtures.meta_host_browser_answers import host_answer
    labels = {"th": {"likes": "Synthetic Thai Action"}}
    request = threads_request(threads_service, action_labels=labels)
    labels["th"]["likes"] = "Changed after preparation"
    payload = host_answer(request)
    payload["answers"][0]["locale"] = "th"
    payload["answers"][0]["records"][0]["counters"] = [counter(raw_display="Synthetic Thai Action12")]
    threads_service.stage(request["request_id"], payload)
    receipt = threads_service.submit(request["request_id"], "task", "session")
    assert receipt["observations"][0]["counters"][0]["value"] == 12
