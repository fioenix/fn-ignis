# TikTok host answer and comment navigation (T058)

## Host-browser answer v2

`extractor_version=tiktok-public-grid-v2` replaces v1 for new tickets/answers. Identity, exact query,
page URL, lifetime, bounds, status/verification and sanitation checks remain. V1 answers cannot
satisfy a v2 ticket; historical observations/path facts remain unchanged.

Each query reports `locale` from `document.documentElement.lang`: validate the language tag,
extract its primary subtag and lowercase it (`[a-z]{2,8}`), else `unsupported`. Missing, malformed,
unsupported and unseeded locale answers yield no observations or mission author sidecar, status
DEGRADED, search_verified=false and an explicit unmeasured note, including a claimed EMPTY_NO_DATA.
No failure is measured absence. Otherwise only the matching locale templates strip attribution.

Vocabulary lives in `market_lexicons`, domain `tiktok_attribution_<locale>`, category `ui_attribution`.
038 adds observed vi wording without changing 034 or stored evidence. MISSION snapshots caller
rows; TACTICAL snapshots packaged seed rows read through isolated in-memory SQLite. These domains
are machinery excluded from market relevance. A ticket's snapshot cannot change after preparation.
Locale coverage does not prove every wording in that locale; additions require observed wording.
Free-text names retain Spec 015 FR-012's limit.

Only visible canonical video cards with visible linked images carrying usable alt labels emit
records. No whole-card innerText fallback. Excerpts retain the 2000-character bound; when nothing
remains the extractor reports DEGRADED, never EMPTY. No counters/window are inferred.

## Opener limitation

TikTok keeps its opener-based postMessage handoff and relay opened-window binding. Unlike Threads
(noopener plus encrypted fragment), it cannot adopt noopener without changing that transport.
Accepted residual for T058: content executing in the TikTok tab may navigate its relay opener
(reverse-tabnabbing). No live exploit was established. Relay COOP headers stay unchanged because
same-origin-allow-popups compatibility with this TikTok opener has not been verified in a browser.

## get_tiktok_video_comments

Public MCP signature is unchanged. Validate before authentication or browser launch: HTTPS,
netloc exactly `www.tiktok.com`, no userinfo/port, and full path `/@<ASCII handle>/video/<ASCII id>`,
`/video/<ASCII id>` or `/share/video/<ASCII id>` (optional trailing slash). Bare tiktok.com,
off-origin URLs, nonnumeric IDs, extra path segments and malformed/control-character URLs reject
with the existing `{status: ERROR, message: ...}` tool shape. Query/fragment tracking is discarded.

Navigate only `https://www.tiktok.com/share/video/<validated id>`, returned as response video_url.
Abort document navigation outside that same validated video; verify landed URL before API
execution. API evaluation checks TikTok origin and fetches the fixed HTTPS comment endpoint with
redirect:error. No live navigation or session readiness is established by mocked tests.

T058 review hardening: reject TikTok alt labels longer than 2000 before extraction; truncating an
attribution tail before sanitation could leave the poster name. This conservative card drop is
covered by a synthetic long-vi-label test; live label length reachability remains unverified.
Matching-tag malformed Reels responses poison the capture even if another bound response is empty.
