# Extractor Contract: Threads Top Search v1

Proposed packaged `threads_search.js`, `threads-search-top-v1`, with source-specific handoff.
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
   Walk to smallest ancestor with that post's action row; overlapping/nested ambiguity is skipped/
   degraded, never broadened to whole feed. No opaque classes, invented test IDs or article hook.
3. Deduplicate shortcode including /media links. Text/image/carousel is allowed only with verified
   body/envelope. Image-node count, panorama button and `1 / 2` are not post counts. No unobserved
   video behavior. Quotes/reposts cannot merge inner authors/body/action counters into outer card.
4. Read isolated body, excluding header/profile/avatar, timestamp/actions/Translate and sidebars.
   Exclude media alt/enclosing accessible names, including attribution that can name another author.
   If body cannot be isolated, drop card; never whole-card innerText or alt-only fallback.
5. Read exact ISO time[datetime], not relative text or title. Invalid/future publication is rejected
   or unknown; never capture-time substitution.
6. Match SVG title Like/Reply/Repost/Share and adjacent numeric text within the action row. G2 found
   no wrapper aria-label. Emit separate raw displays/units/precision; support observed integers and
   decimal-dot K, retain unrecognized syntax as unknown. Blank is unknown; no views or Share=quotes.
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
and immediately clears the hash through `history.replaceState`, then posts the raw fragment to
BroadcastChannel `ignis-host-answer:<request_id>`. It has no key or decryption and shows only
"Answer sent to the relay; close this tab". Close this task-created tab in host cleanup.
All other methods/paths and every TikTok receiver request retain today's behavior.

The main Threads relay listens on that channel, decrypts, checks kind, request id, query id/text,
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
| Every card removed by sanitation | DEGRADED, not EMPTY_NO_DATA |
| Wrong page/query/source/version or malformed answer | Whole-answer rejection before writes |

Synthetic fixture identities only. Scan receipts, metadata, journal, responses, reports and logs;
zero header/attribution/profile leakage. Spec 015's free-text-name limitation stays documented.
