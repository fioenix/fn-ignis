"""Validate trusted-host observations; identifiers bind scope, not authenticity."""

import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from ignis.domain.host_browser_search import HostSearchAnswer, HostSearchRequest
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text, strip_platform_attribution


def validate_answer(request: HostSearchRequest, payload: dict, now: datetime,
                    attribution_templates: tuple[str, ...] = ()) -> dict:
    answer = HostSearchAnswer.model_validate(payload, context={"request": request})
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
    for item in answer.answers:
        query = expected[item.query_id]
        page = urlsplit(item.page_url)
        if (page.scheme != "https" or page.netloc != "www.tiktok.com" or page.path != "/search"
                or page.fragment or parse_qs(page.query) != {"q": [query.query]} or item.query != query.query):
            raise ValueError("Search page does not match the approved query")
        if not request.issued_at <= item.captured_at <= min(now, request.expires_at):
            raise ValueError("Capture is outside the task lifetime")
        if len(item.records) > query.result_limit:
            raise ValueError("Answer exceeds approved record limit")
        if item.status == "HEALTHY" and (not item.search_verified or not item.records):
            raise ValueError("Healthy search requires verified records")
        if item.status == "EMPTY_NO_DATA" and (
            not item.search_verified or not item.empty_state_visible or item.records
        ):
            raise ValueError("Empty search requires explicit matching no-results evidence")
        if item.records and not item.search_verified:
            raise ValueError("Unverified page cannot provide observations")
        seen = set()
        count = 0
        for record in item.records:
            source = urlsplit(record.source_url)
            if (source.scheme != "https" or source.netloc != "www.tiktok.com" or source.query
                    or source.fragment or not re.fullmatch(r"/@[A-Za-z0-9_.]+/video/[0-9]+", source.path)):
                raise ValueError("Expected canonical public TikTok video URL")
            if record.published_at and record.published_at > item.captured_at:
                raise ValueError("Publication cannot follow capture")
            if record.source_url in seen:
                continue
            # The image label ends by naming the poster; that sentence is not content (FR-012).
            excerpt = strip_platform_attribution(record.excerpt, attribution_templates)
            if not excerpt.strip():
                continue
            seen.add(record.source_url)
            count += 1
            observations.append(dict(
                source_url=record.source_url, excerpt=sanitize_pii_text(excerpt), query=query.query,
                query_id=query.query_id, request_id=request.request_id,
                captured_at=item.captured_at.isoformat(),
                published_at=record.published_at.isoformat() if record.published_at else None,
                metric_value=None, metric_kind=None, metric_known=False,
                collection_path="host_browser:" + answer.extractor_version,
            ))
        # A healthy answer whose every label was only attribution measured no content.
        status = "DEGRADED" if item.status == "HEALTHY" and not count else item.status
        outcomes.append(dict(query_id=query.query_id, query=query.query, status=status,
                             signals_collected=count, queried_window=None,
                             search_verified=item.search_verified,
                             note="Bounded visible public video grid; window and counters unmeasured"))
    return dict(status="ACCEPTED", mode=request.mode, request_id=request.request_id,
                observations=observations, outcomes=outcomes)
