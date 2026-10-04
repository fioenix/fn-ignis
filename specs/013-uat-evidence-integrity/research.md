# Research

## Evidence

TikTok UAT: 47 mission observations, unknown window/reach/publication dates. Threads first UAT: ten first-query-labeled records despite four-query attestation. Two-query diagnostic: 35.87 seconds, 27/22 parsed background responses, no exact query proof or extracted posts. Earlier record provenance is not retroactively established.

Offline actual Threads fetch reproduction attests an unrelated data.custom_feeds payload as completed search. Attention saturation advice has a RED→GREEN regression, fresh MCP/export verification and default suite 1927 passed/374 skipped/two warnings; not live or backend proof.

## Decisions and alternatives

- Decision: exact request-query plus public-result envelope proof before both extraction and attestation. Reject relevance/popularity/login/API-traffic heuristics: they cannot prove measurement.
- Decision: preserve shared collector defaults; optional search restriction only. Reject global marker edits without consumer parity.
- Decision: valid direct empty search must not fall back merely because records are empty. Unknown envelopes remain degraded, not measured absence.
- Decision: initial UAT may fail, but every missing baseline case remains required; final full UAT is mandatory.
- Decision: controlled positive Claim Ledger fixtures remain explicitly test-only, separate from real-market Gap Reports.

## Read-only consumer research

Spec Kit research agent audited meta_browser_ingress.py, threads_plugin.py, Reels callers, registry and tests. Shared browser capture serves Threads posts/trending and Reels; direct fetch serves posts/trending/suggestions. Registry classifies nonempty returned records HEALTHY independently of attestation, so merely removing executed() is insufficient. Known fixture shape is data.searchResults.edges; keyword_search.keywords is autocomplete, not post-search proof. No live-verified current public post envelope is present in the repository. Tests must cover query request metadata, malformed/foreign/background siblings, valid empty, direct/browser parity and shared consumers. Query-specific live navigation remains an execution investigation, not a resolved assumption.

## Actual server-render investigation — 2026-10-04

The corrected connector honestly rejected background traffic, but that alone did not restore results. Repeated isolated navigation showed the exact public query in the URL and populated visible search input; submitting Enter still yielded no query-specific XHR. Structural-only DOM inspection then found server-rendered Relay JSON: an expected preloader has variables.query exactly matching the assigned keyword, and a separate RelayPrefetchedStreamCache result carries data.searchResults.edges with thread/thread_items/post shape. Five public post links were rendered. This disproves the blanket assumption that the page did not execute search: the collector's XHR-only observation boundary misses server-rendered results. No cookies, raw script/body, post text or private account contents were logged.

Subsequent actual structural readback verified the association: expectedPreloaders identifies queryName=BarcelonaSearchResultsQuery, exact variables.query and a preloaderID; RelayPrefetchedStreamCache.next carries that identical preloaderID and a complete result with data.searchResults.edges. Another viewer-data preloader does not match the query and must not be admitted. The recorded public result has one edge, despite no matching XHR and sometimes no hydrated input/post DOM yet. Root cause is the XHR-only observation boundary, not proof of an invalid login or absent search execution. A query-matching page URL alone must not authorize arbitrary embedded JSON. Remediation must admit only the matched public-search preloader result on a successful exact navigation request, preserve the existing tier, and include malformed/wrong-query/background/empty regressions. A second query and final full UAT remain required.
