"""Validate transient browser records and destroy identity before staging any receipt."""

import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from ignis.infrastructure.connectors.host_browser.action_labels import seeded_action_labels
from ignis.domain.host_browser_search import HostSearchAnswer, HostSearchRequest
from ignis.domain.self_content import is_self_authored
from ignis.domain.source_identity import identity_free_source_url
from ignis.infrastructure.security.pii_sanitizer import mask_author_identity_text, sanitize_pii_text, strip_platform_attribution


def collection_path(source, version, limit):
    """Normalized measurement facts, independent of random task ids and capture time."""
    return dict(collection_path="host_browser:" + version, connector_revision=version,
                sampling=dict(limit=limit, ordering="top_visible_sample" if source == "threads" else "visible_grid"))


def _content_url(source, raw):
    if raw is None:
        return None
    url = urlsplit(raw)
    expected = "www.threads.com" if source == "threads" else "www.tiktok.com"
    if url.scheme != "https" or url.netloc != expected or url.query or url.fragment:
        raise ValueError("Expected canonical public content URL")
    pattern = (r"/(?:@[A-Za-z0-9_.]+/post/|t/)([A-Za-z0-9_-]+)(?:/media)?/?" if source == "threads"
               else r"/(?:@[A-Za-z0-9_.]+/video/|share/video/)[0-9]+")
    match = re.fullmatch(pattern, url.path)
    if not match:
        raise ValueError("Expected canonical public content URL")
    if source == "threads":
        return "https://www.threads.com/t/" + match.group(1)
    return identity_free_source_url(source, raw, {})


def _counters(components, labels):
    result = []
    for counter in components:
        raw = counter.raw_display.strip()
        label = labels.get(counter.kind)
        if label and raw.lower().startswith(label.lower()):
            raw = raw[len(label):].strip()
        if not label:
            expected, precision = None, "unknown"
        elif re.fullmatch(r"[0-9]+", raw):
            expected, precision = int(raw), "exact"
        elif re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?[KM]", raw):
            multiplier = 1000000 if raw.endswith("M") else 1000
            expected = int((Decimal(raw[:-1].replace(",", ".")) * multiplier).to_integral_value(rounding=ROUND_HALF_UP))
            precision = "rounded"
        else:
            expected, precision = None, "unknown"
        if expected is not None and expected > 9007199254740991:
            expected, precision = None, "unknown"
        if (counter.value, counter.precision) != (expected, precision):
            raise ValueError("Counter does not preserve displayed precision")
        value = counter.model_dump(mode="json")
        value["raw_display"] = mask_author_identity_text(sanitize_pii_text(value["raw_display"]))
        result.append(value)
    return result


def validate_answer(request: HostSearchRequest, payload: dict, now: datetime,
                    attribution_templates: tuple[str, ...] = (), self_identities=(), *, author_records=None, action_labels=None) -> dict:
    action_labels = seeded_action_labels() if action_labels is None else action_labels
    answer = HostSearchAnswer.model_validate(payload, context={"request": request})
    if not attribution_templates:
        raise ValueError("Source attribution vocabulary is unavailable")
    if (answer.request_id, answer.host_task_ref, answer.session_ref) != (
        request.request_id, request.host_task_ref, request.session_ref
    ):
        raise ValueError("Answer identity does not match the task")
    if now >= request.expires_at:
        raise ValueError("Task expired")
    expected = {query.query_id: query for query in request.queries}
    if len(answer.answers) != len(expected) or {item.query_id for item in answer.answers} != set(expected):
        raise ValueError("Every approved query requires exactly one answer")
    observations, outcomes = [], []
    origin = "www.threads.com" if request.source == "threads" else "www.tiktok.com"
    for item in answer.answers:
        query = expected[item.query_id]
        page = urlsplit(item.page_url)
        if (page.scheme != "https" or page.netloc != origin or page.path != "/search" or page.fragment
                or parse_qs(page.query, keep_blank_values=True) != {"q": [query.query]} or item.query != query.query):
            raise ValueError("Search page does not match the approved query")
        if request.source == "threads":
            if not re.fullmatch(r"[a-z]{2,8}|unsupported", item.locale or "") or item.status == "EMPTY_NO_DATA":
                raise ValueError("Unsupported Threads locale or unproved empty state")
            if item.locale == "unsupported" and (item.status != "DEGRADED" or item.records or item.search_verified):
                raise ValueError("Unsupported Threads locale cannot provide verified observations")
        if not request.issued_at <= item.captured_at <= min(now, request.expires_at):
            raise ValueError("Capture is outside the task lifetime")
        if len(item.records) > query.result_limit:
            raise ValueError("Answer exceeds approved record limit")
        if item.status == "HEALTHY" and (not item.search_verified or not item.records):
            raise ValueError("Healthy search requires verified records")
        if item.status == "EMPTY_NO_DATA" and (not item.search_verified or not item.empty_state_visible or item.records):
            raise ValueError("Empty search requires explicit matching no-results evidence")
        if item.records and not item.search_verified:
            raise ValueError("Unverified page cannot provide observations")
        seen, count = set(), 0
        path = collection_path(request.source, request.extractor_version, query.result_limit)
        for record in item.records:
            cleaned_url = _content_url(request.source, record.source_url)
            if record.published_at and record.published_at > item.captured_at:
                raise ValueError("Publication cannot follow capture")
            # Match the transient author-bearing URL before destroying it. Never stage it.
            if is_self_authored(SimpleNamespace(platform=request.source, source_url=record.source_url, metadata={}), self_identities):
                continue
            policy_excerpt = sanitize_pii_text(strip_platform_attribution(record.excerpt, attribution_templates))
            excerpt = mask_author_identity_text(policy_excerpt)
            if not excerpt.strip():
                continue
            identity = cleaned_url or excerpt
            if identity in seen:
                continue
            seen.add(identity)
            count += 1
            observation = dict(source_url=cleaned_url, excerpt=excerpt, query=query.query, query_id=query.query_id,
                request_id=request.request_id, captured_at=item.captured_at.isoformat(),
                published_at=record.published_at.isoformat() if record.published_at else None,
                metric_value=None, metric_kind=None, metric_known=False, collection_path=path["collection_path"])
            if request.source == "threads":
                observation.update(source=request.source, source_verifiable=cleaned_url is not None,
                                   counters=_counters(record.counters, action_labels.get(item.locale, {})), **path)
            observations.append(observation)
            if author_records is not None:
                # This private in-memory input reaches canonical author policy, never a receipt/store.
                author_records.append({**observation, "source_url": record.source_url, "excerpt": policy_excerpt})
        status = "DEGRADED" if item.status == "HEALTHY" and not count else item.status
        outcome = dict(query_id=query.query_id, query=query.query, status=status, signals_collected=count,
                       queried_window=None, search_verified=item.search_verified,
                       note="Bounded visible public video grid; window and counters unmeasured")
        if request.source == "threads":
            outcome.update(**path, note=("Threads page locale is unsupported; no observations collected"
                                         if item.locale == "unsupported" else
                                         ("Bounded visible Top sample; counters unmeasured for locale " + item.locale
                                          if not action_labels.get(item.locale) else
                                          "Bounded visible Top sample; rounded and unknown counters retained")))
        outcomes.append(outcome)
    receipt = dict(status="ACCEPTED", mode=request.mode, request_id=request.request_id,
                   observations=observations, outcomes=outcomes)
    if request.source == "threads":
        receipt["source"] = request.source
    return receipt
