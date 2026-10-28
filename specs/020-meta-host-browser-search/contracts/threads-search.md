# Extractor Contract: Threads Top Search v2

Proposed packaged `threads_search.js`, `threads-search-top-v2`, with source-specific handoff.
Grounding: Threads section of [g2-surfaces.md](../g2-surfaces.md). No Instagram extractor.

## Page and bounded extraction

HTTPS www.threads.com, path /search, one q exactly equal to approved query, no fragment/additional
filters. Recent, Profiles, foreign origin, profile/detail routes or redirects refuse. Use only the
connected authorized session and relay-opened task tab. No page clicks/typing, account/challenge/
consent interaction, storage/cookie read, debugging port, fetch or remote script.

Bound the visible DOM sample by approved result/time limit. Repeated permitted reads deduplicate
in memory before virtualization removes cards; no unapproved scrolling or unbounded loading loop.
The initial version supports visible sample, not search exhaustion. No HTML/transcript transfer.

1. Verify exact page/query/public-result envelope. Initial empty shell, Loading and sidebar
   suggestions cannot establish healthy or empty search.
2. Anchor canonical `/@<author>/post/<post-id>` timestamp links containing `time[datetime]`.
   Walk to the nearest ancestor containing at least four visible SVG-bearing buttons (`button`
   or `role=button`), independently of title language; overlapping/nested ambiguity is skipped/
   degraded, never broadened to whole feed. No opaque classes, invented test IDs or article hook.
3. Deduplicate shortcode including /media links. Text/image/carousel is allowed only with verified
   body/envelope. Image-node count, panorama button and `1 / 2` are not post counts. No unobserved
   video behavior. Quotes/reposts cannot merge inner authors/body/action counters into outer card.
4. Read isolated body, excluding header/profile/avatar, timestamp/actions/Translate and sidebars.
   Exclude media alt/enclosing accessible names, including attribution that can name another author.
   If body cannot be isolated, drop card; never whole-card innerText or alt-only fallback.
5. Read exact ISO time[datetime], not relative text or title. Invalid/future publication is rejected
   or unknown; never capture-time substitution.
6. Read the primary language subtag from `document.documentElement.lang`, normalized lowercase
   (`vi-VN` → `vi`). Missing/malformed language yields `locale=unsupported`, DEGRADED, unverified,
   zero records (T054). Any well-formed primary locale may collect records by structure.
   Prepare freezes `market_lexicons` domain `threads_action_labels_<locale>`, category `<kind>`,
   term matching the SVG title case-insensitively (`toLowerCase()` / `.lower()`). Migration 037
   seeds en/vi observed titles. Tactical reads the packaged seed in an isolated in-memory SQLite table without opening caller storage; mission
   reads its caller repository. Both inject the frozen table as data into the packaged extractor
   and validate against that same snapshot. New locales require rows, not source changes.
   Match counters only by SVG title, never by button position; absent/ambiguous title is unknown.
   No labels for the locale means all counters unknown/null, records still allowed, and an outcome
   note saying counters are unmeasured for that locale. A partial label map measures only its kinds.
   Strip the matched leading label case-insensitively from button text for parsing only; preserve
   `raw_display`.
   Plain digits are exact; K/M suffixes accept dot/comma decimal and round half up to an integer
   (`Thích1,4K` → rounded 1400, `4.1K` → rounded 4100). Empty/label-only/unrecognized/unsafe integer
   displays stay unknown/null. Never promote rounded precision to exact or Share to quotes.
7. Emit allowlisted records only; content shortcode builds identity-free /t/ link. Validator also
   applies Spec 015 link policy, seeded attribution stripping and PII/mention cleanup before output/
   persistence. Errors contain reason codes/counts, no identities or raw payload.

## Handoff and outcomes

Owner amendment, **28/10/2026 (T055)**: opener loss no longer blocks the Threads handoff.
The Threads tab navigates the **same tab** to the ticket's exact loopback `receive` page with an
**encrypted** fragment. TikTok retains its opener postMessage path unchanged. FR-013 remains:
the host sees only `{posted, status, records}` or `{posted: false, reason}`, never record content.

Prepare creates a random 256-bit AES-GCM key per Threads ticket, embedded in `tab_script` and main
relay data only. Never include it in URLs, logs, other MCP response fields or the receiver page.
After exact page/query checks and packaged extraction, encrypt message JSON
`{kind: "ignis-host-answer", request_id, answer}` with a fresh 96-bit IV and base64url encode
`iv||ciphertext` (including the GCM tag). Refuse fragments exceeding **1,000,000 characters**, any
failed check or encryption error without navigation. Otherwise schedule `location.replace` after
100 ms to `<relay URL>receive#<payload>` and return status/counts. No opener requirement for Threads.

Only Threads tickets serve GET at the exact token-bound receiver path. The static nonce-CSP page
uses `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and no external resources. It reads
and immediately clears the hash through `history.replaceState`, then posts only a base64url fragment
of 39 through 1,000,000 characters to BroadcastChannel `ignis-host-answer:<request_id>`. It has no key or decryption and shows only
"Answer sent to the relay; close this tab". Invalid fragments post nothing. Close task-created
tabs only after the relay shows `STAGED` or after submit; `posted: true` alone precedes navigation.
All other methods/paths and every TikTok receiver request retain today's behavior.

The main Threads relay listens on that channel, requires decoded input longer than 28 bytes
(12-byte IV + 16-byte tag + nonempty ciphertext) before decrypting, checks kind, request id, query id/text,
record limit, one answer per query and nothing after submission. Ignore failed decryption/checks
without state change. Reuse the answers map, status line and `requestSubmit` of the full envelope.
Preserve nonce CSP/query escaping, Host/Origin, no CORS, server validation, single-use staging,
rejection closure, lifetime and shutdown. No CORS/fetch, popup, window.name or default manual
transport is authorized by this amendment. History contains ciphertext only; tab cleanup bounds
transient key retention. The configured size ceiling still requires live browser verification.

| Surface state | Outcome |
|---|---|
| Verified cleaned body sample | HEALTHY, explicit visible-sample/precision limitations |
| Initial shell/loading/unchanged count/suggestions only | DEGRADED, no absence claim |
| Login/checkpoint/challenge/unusable | DEGRADED or precise existing unavailable/auth state with reason; no bypass |
| No cards without validated no-results signature | DEGRADED; this version never emits healthy empty |
| Missing/unusable page language | DEGRADED, unverified, no records |
| Well-formed locale without seeded labels | Records allowed; every counter unknown/null, explicit unmeasured note |
| Every card removed by sanitation | DEGRADED, not EMPTY_NO_DATA |
| Wrong page/query/source/version or malformed answer | Whole-answer rejection before writes |

Synthetic fixture identities only. Scan receipts, metadata, journal, responses, reports and logs;
zero header/attribution/profile leakage. Spec 015's free-text-name limitation stays documented.


## Accepted v0.9.0 limitation — structural card detection follow-up

Independent review finding 2, accepted by the owner for v0.9.0 on 28/10/2026 (T057): media with SVG
buttons inside a card can satisfy structural detection below the action row, leaving counters
unknown. A quoted post with two timestamps in one card blocks that card and marks the whole query
`DEGRADED` while retaining other valid records. Follow up on structural card/action-row ownership
and quoted-post isolation; these remain conservative limitations, not complete counter/quote support.

## T058 bounds and opener isolation

Threads query controls open search tabs with `noopener`; encrypted-fragment handoff and receiver
BroadcastChannel need no opener. TikTok retains its required opener and accepted reverse-tabnabbing
residual (see [tiktok-search.md](tiktok-search.md)); COOP headers remain unchanged without browser
compatibility proof. Normalize each Threads body excerpt then cap at 2000 characters before sample
caching. Locale action labels that collide under casefold across kinds are invalid vocabulary.
Relay form Content-Length must contain ASCII digits only; other digit scripts are a 400 error.
