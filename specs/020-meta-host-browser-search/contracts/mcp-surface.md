# MCP Contract: Threads Source Extension (Proposed)

Owner Gates OG-1/2 pending. **53 → 53 tools**. Existing Spec 012 task, expiry, writer, replay,
caller, stale-frame and failure contracts remain. No implementation or API grant is claimed.

## prepare_host_browser_search

Retain parameters/defaults; add only optional `source: str = "tiktok"` restricted to `tiktok` or
`threads`. Invalid source returns existing `BLOCKED/INVALID_HOST_SEARCH_SCOPE`. Store source in
the immutable ticket. Do not infer source from query text or overload task/session references.

TACTICAL retains finite explicit queries, no mission. MISSION retains confirmed mission_id,
queries=[], result_limit=20, full query union including falsifiers, manifest resource/authority/
quota checks. Browser execution requires browser-session authority; external API execution requires
separate approved MCP authorization. `authorized=true` alone proves neither ownership nor grant.

Output adds source and typed path descriptors, source-specific packaged version/instructions;
retains IDs/expiry/relay URL and browser tab_script. Threads exact search URL is
`https://www.threads.com/search?q=<encoded query>`, Top only. Absent source preserves existing
TikTok defaults/URLs/version/behavior. Missing source vocabulary returns
`BLOCKED/AUTHOR_ATTRIBUTION_VOCABULARY_MISSING` before creating relay/run.

## submit_host_browser_search / cancel_host_browser_search

Signatures unchanged: request_id, host_task_ref, session_ref; submit consumes validated staged
answers, not raw MCP record arguments. Cancel stops task transport, not the owner's browser.
Staged JSON extension is itself an interface proposal requiring OG-2 review.

Strict browser/API variants share exact identity/query set, source/path/version, finite capture
lifetime/limits and sanitized records. Wrong/missing/extra query, mixed paths, stale source/version
or malformed URL rejects whole answer before writes. Legacy TikTok payload accepted only for TikTok.

- Browser Threads uses `threads-search-top-v1`, exact page and verified public-card sample. Current
  version cannot attest EMPTY_NO_DATA: G2 established no no-results signature.
- API Threads uses `threads-mcp-keyword-v1`, provider `fioenix/threads-mcp`, actual keyword operation,
  approved public-search verification, exact executed query/capture and returned scope/cursor/limit.
  Raw provider dictionaries are not accepted. Bind actual provider fields before activation; no
  assumed operation name or auth schema. Exclude SELF_ONLY/NOT_PERMITTED/missing approval.
  API empty requires successful scoped keyword execution with no items or partial failure; capped
  results never imply platform exhaustion.
- Strip author fields, attribution, profile/avatar links and handle segments before outward
  receipt/log/journal/store; sanitize metadata and error reasons too. Publication/counters retain
  knownness and precision. No content reference means separately counted context, not claim support.
- Structural failure uses `BLOCKED/HOST_SEARCH_NOT_ACCEPTABLE`. Channel failures retain existing
  DEGRADED/auth/rate states and identity-free reason. Zero collected on unavailable is not absence.
  Mission failure retains `FAILED/HOST_MISSION_INGESTION_FAILED` and uncertain-run readback.

## Precedence, transport and multi-source composition

Host selects one path before collection: approved public Threads MCP first; today no grant exists,
so authorized host browser or unavailable. API failure never silently retries browser. Browser after
approval requires separately selected owner authority. Ignis's OAuth/cookie/legacy paths do not collect.

Reuse the same-origin relay form with supported structured tool-value transfer. Preserve Host/Origin,
nonce CSP, bounds, ticket lifetime and one-shot validation; no public POST endpoint, third-party CORS,
credential JS bridge, shell/CDP browser connection or LLM transcription. Browser postMessage policy
remains source-specific and cannot be used to spoof API transport. If real host-value transfer cannot
be demonstrated, keep API activation pending; new tool/submit payload parameter requires FR-005
amendment and owner approval, not an implicit fallback.

For missions requiring TikTok plus Threads host results, prepare sibling source tickets bound to
same mission/caller/frame, stage every required source, then submit either member to execute one
merged authorized run. Reject incomplete/duplicate/stale groups before writes. Cache shared receipt
for members; cancellation/expiry invalidates group. Test actual supported composition before
activation; never execute the first ticket and let the registry collect the missing sibling.

## Other public tools and period responses

No signature removal/change to Threads authenticate/status/clear/trending/suggestions. Retained auth
is compatibility, not public-search readiness; unsupported collection returns explicit unavailable.
Reels remains flag-free Playwright; login/checkpoint/challenge/unusable page returns unavailable
with reason, never measured zero.

`get_watchlist_period_snapshot` parameters unchanged. Both labelled axes gain per-channel path sets/
basis and `collection_path_changed`, `collection_path_mixed`, `collection_path_unknown` reasons;
status=not_comparable, no comparison delta when refused. Retain existing coverage/cadence/unjudged
reasons and unrelated-channel behavior. Counters keep display/precision; no false exact summary.

Implementation regenerates `hermes_manifest.json`/`.hermes/tools.json` with the prescribed generator
and proves exact count 53, only prepare parameter delta, TikTok default parity; see research R9.

## T058 current behavior amendment (28/10/2026)

The accepted implementation uses threads-search-top-v2. New default TikTok tickets/answers use
`tiktok-public-grid-v2` and the locale gate in [tiktok-search.md](tiktok-search.md), superseding the
legacy TikTok version/answer-parity statements above. No MCP tool signature or tier changes.
Reels keyword browser attestations require matching requested hashtag GET tag web_info provenance,
an admitted response and exact landed `/explore/tags/<hashtag>/` path. Other or unbound responses
are unavailable, not EMPTY/HEALTHY; login/challenge/HTTP/JSON/settlement failures remain unavailable.
The no-keyword OWN_PROFILE path retains its separate behavior and never attests a keyword search.
