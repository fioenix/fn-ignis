# Implementation Plan: Threads Through the Host Browser, Without Evasion Flags

**Branch**: `claude/meta-host-browser-spec` | **Date**: 2026-10-27 | **Spec**: [spec.md](spec.md)

**Status**: Plan accepted with owner gate decisions of 27/10/2026 (see "Owner decision" below).
Settled Clarifications are preserved. G1 is accepted; G2 supplies bounded surface evidence, not
extractor or channel readiness. No routine activation, session use, migration application to a live
store or release is authorized by this document.

## Summary

Feed the existing `threads` channel through Spec 012's host relay, then remove its Playwright
collection and all eight automation-hiding flags. Keep Reels on flag-free Playwright, reporting
blocked pages as unavailable with the reason. Prefer the owner's Threads MCP once it holds an
approved public keyword-search grant. Reuse existing staging/submission rather than adding a tool.
Preserve identity-free content references, exact clocks, counter display precision and path lineage;
refuse period comparisons across method changes.

## Technical Context

**Language/Version**: Python 3.11+ (CI 3.12), Pydantic 2; packaged deterministic JavaScript.
**Primary Dependencies**: Existing FastMCP/MCP, Playwright for retained paths, standard-library
loopback relay; no dependency or credential store added.
**Storage**: Existing SQLite/PostgreSQL observations and mission associations; JSON metadata and
probe `scope_attestation` carry path facts. Proposed `sql/036_threads_attribution.sql` seeds
vocabulary only, after current endpoint 035; recheck numbering before implementation. No schema
change, historical rewrite or evidence backfill.
**Testing**: Targeted pytest, deterministic DOM fixtures, relay security, both-backend parity,
installed-wheel resource/schema smoke and separately authorized live run/readback.
**Target Platform/Project Type**: Local MCP evidence service and supported host browser; external
Threads MCP remains host-owned, outside Ignis's auth stores.
**Performance/Scale**: Preserve existing bounds: 32 queries, 1–100 results/query, one-hour maximum
lifetime, 32 retained tickets; mission limits remain derived (currently 20 results/query), including
full query union and daily ceilings. No unbounded DOM polling/scrolling.
**Constraints**: No cookie export, CDP/debugging port, fallback browser, LLM extraction, account
interaction, scheduler, Instagram extractor or G3 routine change. Rounded counts stay rounded.
Threads has no validated healthy-empty signature from G2.

## Constitution Check

Checked against **2.3.0** before research and again after Phase 1 design.

| Principle | Pre-design | Post-design constraints and proof obligation |
|---|---|---|
| I. Mission-bound autonomy and zero-token collection | Pass in design | Explicit finite tickets and per-firing authority; deterministic DOM/API adaptation; no model reconstruction of raw records, recurring loop or routine widening. |
| II. Pluggable/user-controlled connectors | Pass in design | One channel, explicit per-query failure/path; host verifies grant/session authority. Cookies and installed tooling are not readiness. Unrelated channels remain isolated. |
| III. Evidence-first/falsification | Pass in design | Reuse canonical source/observation/association and qualification; keep ingestion, capture and publication separate; unknown counts/windows explicit. Both seen and created refuse changed/mixed/unknown paths while retaining coverage, cadence and judgment rules. |
| IV. Deterministic report builders | Pass in design | No new research report surface; existing period response gains path reasons. Relay remains transport. |
| V. Simplicity/surgical changes/type safety | Pass in design, OG-1/2 pending | Reuse prepare/submit/cancel, strict typed staging, one extractor and SQL vocabulary. Trace shared Reels consumers; prove default TikTok parity. |
| VI. Evidence-gated migration/release | Pass in design | Seed-only migration transforms no evidence; no provenance backfill. Backend, wheel and live gates remain before delivery. |
| VII. No author identity at rest | Pass in design, conformance pending | Exclude headers/avatar/profile content, strip seeded attribution, mask mentions and rebuild Spec 015 links before receipts/writes/logs. Missing reference stays context; unknown author marker when none collected. |

No amendment or exception is proposed. Post-design result: **design compliant subject to owner
gates and implementation proof**; no runtime acceptance is claimed.

## Owner Gates

### Owner decision (27/10/2026)

The owner's words: "Duyệt OG-1, OG-3, OG-4, OG-5; OG-2 hoãn phần Threads MCP tới khi App Review
được duyệt, giữ phần ghép TikTok và Threads trong một lượt chạy (spike trước)."

- **OG-1 approved**: optional `source` (`tiktok` | `threads`, default `tiktok`) on
  `prepare_host_browser_search`; Threads collection moves to host submission.
- **OG-2 split**: the Threads MCP submission path (API variant of the staged answer, structured
  value transport, `threads-mcp-keyword-v1`) is **deferred** until Meta approves
  `threads_keyword_search` for the owner's app; it is out of this implementation and returns as a
  spec amendment then. Spec story 3 and FR-008 stay as the target but are not implemented now; until
  then Threads uses the host browser only. The **single-run composition** of TikTok and Threads host
  tickets in one mission run is **kept**, with a spike first; if the spike shows unchanged tools
  cannot express it safely, that seam stops for owner review.
- **OG-3 approved**: seed-only `sql/036_threads_attribution.sql` (recheck numbering at
  implementation).
- **OG-4 approved**: no constitution amendment.
- **OG-5 approved**: no G3 routine change in this feature; live runs and routine change need separate
  approval.

### Owner decision (28/10/2026): T055 Threads same-tab handoff

The owner amends the Threads-only opener-loss rule: the packaged Threads handoff navigates the
same task-created tab to the ticket's exact loopback receiver with an encrypted answer fragment.
FR-013 remains: the host agent sees status and counts only. TikTok keeps its opener postMessage
transport unchanged. This is an approved contract amendment, not a constitution or MCP signature
change, and grants no live-session, routine, release or commit authority.

Prepare generates a random per-ticket 256-bit AES-GCM key, embedded only in `tab_script` and the
main relay's data (never URLs, logs, other response fields or the receiver). Encrypt message JSON
`{kind, request_id, answer}` using a fresh 96-bit IV; base64url encode `iv||ciphertext` into a
fragment capped at 1,000,000 characters. Refuse oversize/check/encryption failures before navigation.
After a 100 ms timer, `location.replace` navigates to `<token path>receive#<ciphertext>`.
The static nonce-CSP receiver clears the hash immediately with `history.replaceState`, broadcasts
only the raw fragment on `ignis-host-answer:<request_id>`, and shows neutral close-tab guidance.
It has no key, decryption, external resources or record display; use no-store and no-referrer.

The main relay decrypts and checks kind, request/query id and text, result limit, first answer per
query and no answers after submission, then reuses the answers map and full-envelope form submit.
Invalid ciphertext/messages leave state unchanged. Only Threads GET admits the exact receiver
path; TikTok, other paths/methods, Host/Origin checks, validator, single-use staging, rejection
closure, lifetime and shutdown retain their existing behavior. The agent closes the receiver as a
task-created tab. Keys and decrypted data are transient; history holds ciphertext only. Browser
cleanup and the ticket lifetime bound the key's usefulness; relay shutdown drops its key-bearing
page/script copies. No durable key store is introduced.

Execution resumes accepted Spec Kit tasks/implement at T055 (NORMAL, privacy/transport scrutiny),
using `.handoff/spec020-skill/coding-workflow.vault-read.md`, explicitly supplied as canonical.
Its review-by 2026-10-21 is overdue; owner-supplied copy is retained. Requirements checklist: 16/16.
No extension hooks are configured. Tests precede implementation; socket-free Node Web Crypto and
handler probes cover this seam. Real loopback binding and live Chrome remain separately reported
limits. No semantic activity-selection ambiguity remains after the owner's explicit design.
Full skill replacement is delivered under `.handoff/spec020-skill/ignis-collect/SKILL.md` for
coordinator integration; the installed skill is unchanged. See research R11 and the Threads contract.

### Proposals as written before the decision

- **OG-1 — MCP prepare signature / Threads tier**: propose only optional `source: str = "tiktok"`
  (`tiktok` or `threads`) on `prepare_host_browser_search`; source is frozen in the ticket. Includes
  replacing Threads internal collection with host submission. Section 8 requires exact interface/
  tier approval despite settled scope direction. Alternative: keep signature, leave Threads
  unavailable until approved; never overload queries or session refs.
- **OG-2 — Threads MCP submission surface**: propose an API variant of the existing staged JSON
  answer with public-search grant attestation; unchanged submit/cancel signatures, **53 → 53 tools**.
  Host calls the external MCP and uses supported structured value transport into the same-origin
  relay form. No public ingestion endpoint, relaxed CORS or model transcription. Alternative:
  defer API activation if transport cannot be proved. A dedicated tool or new submit payload
  argument needs a spec amendment (FR-005) and explicit owner approval; neither is adopted here.
  The single-run composition of multiple host-source tickets is part of this proposal.
- **OG-3 — migration**: propose `sql/036_threads_attribution.sql`, seed-only `threads_attribution`
  with observed English `Photo by {author} on` wording; tactical packaged seed and mission repository
  load like 034. Alternative: defer Threads acceptance with vocabulary-missing outcome. No schema
  or evidence migration. Although section 8 permits agent-decided vocabulary, this request leaves
  the proposal pending owner review. See research for migration/package consumers.
- **OG-4 — constitution impact**: propose no amendment; enforce 2.3.0 I–VII. Alternative if an
  exception becomes necessary: stop dependent work for documented owner disposition, cost and
  expiry, rather than silently changing the constitution.
- **OG-5 — routine / live activation**: propose **no G3 routine change** (FR-009). Alternative:
  separately approved routine update after readiness. FR-011/SC-001 require an actual Ignis-to-host
  G3 run; SC-006 requires live flag-free Reels. Obtain bounded live session/run authority later;
  G1/manual G2 does not authorize this planning run. API live validation waits for actual grant.

## Architecture and Lifecycle

1. Host chooses approved public Threads MCP first; today its grant is absent, so use authorized
   host browser or unavailable. SELF_ONLY/NOT_PERMITTED never provide market evidence. No browser
   downgrade after API failure without separate authority; no Ignis-owned Threads OAuth collection.
2. Prepare freezes source, queries, exact URLs, versions, templates and mission/frame/caller
   bindings. Threads tickets accept a strict browser or API answer; host selects one path before
   collection and stage freezes it for the complete batch. A browser authorization does not grant
   API access. No mixing paths to fill query gaps.
3. Extract Threads from G2 timestamp/post-link/action-row structure, body text separated from
   headers. Top route only, bounded visible sample, no clicks/typing/post details. Virtualization
   means a final DOM snapshot is not exhaustion. See [extractor contract](contracts/threads-search.md).
4. Relay enforces source-specific origin/opened-window/query, nonce CSP, Host/Origin, size, expiry,
   one-shot and cancellation checks. Browser handoff returns only counts/status to the host.
   External MCP uses supported structured transport into the existing form, never forged browser
   messages or model-built record JSON. Prove that transport before activating API submission.
5. Sanitize before outward receipts/durable writes. Mission ingestion retains writer/stale guards,
   self-exclusion, full manifest outcomes and qualification. Skip submitted surfaces in registry
   execution. A run requiring TikTok and Threads must prepare/stage sibling tickets against the
   same mission/frame, then execute **one writer/run** over their merged validated results plus
   remaining channels. Submit of one group member consumes the staged group and caches its receipt
   for all members; reject duplicate sources, incomplete/stale groups before writes. Cancel/expiry
   of a member invalidates the group. No new MCP argument, implicit second run or terminal restart.
6. Persist normalized path in observation metadata and probe attestation, including empty probes.
   Period assembly propagates it before source merging. Per the delegated coordinator decision
   (28/10/2026), both axes preserve legacy comparison when both sides are wholly unknown and compare
   identical proven identities. Different proven identities, proven-versus-unknown, or a mixture
   of proven identities or proven/unknown within one side refuse with the respective path reason.
   Do not change placement, cadence, coverage or the unknown-versus-unknown response shape.
7. After host readiness proof, retire Threads internal collection; remove all eight flags. Keep
   shared Reels helpers flag-free. Reels blocked/unusable pages are unavailable with reason, never
   measured empty. Retain legacy public signatures with unavailable compatibility behavior.

Transport and multi-source single-run composition require a spike before dependent implementation.
If unchanged tools cannot express them safely, stop that seam for owner review; do not weaken FR-005.

## Execution path (Spec Kit depth gate)

After plan acceptance: `speckit-tasks` then `speckit-implement`. Privacy, relay security, MCP
signature, connector tier, migration and ordered multi-source integration rule out a direct pass.
No `tasks.md` or implementation in this planning phase; settled Clarifications stay untouched.

## Project Structure

### Documentation (this feature)

```text
specs/020-meta-host-browser-search/
  spec.md, g2-surfaces.md                              # unchanged inputs
  plan.md, research.md, data-model.md, quickstart.md
  contracts/mcp-surface.md, contracts/threads-search.md
```

### Source Code (planned; unchanged here)

```text
src/ignis/domain/host_browser_search.py
src/ignis/application/use_cases/host_browser_search.py, host_browser_mission.py
src/ignis/infrastructure/connectors/host_browser/       # threads_search.js and handoff resource
src/ignis/infrastructure/templates/html/host_browser_relay.html
src/ignis/infrastructure/connectors/threads/threads_plugin.py
src/ignis/infrastructure/connectors/meta_browser_ingress.py
src/ignis/infrastructure/auth/{meta_browser_auth,tiktok_auth}.py
src/ignis/infrastructure/connectors/tiktok/{tiktok_plugin,creative_center_plugin}.py
src/ignis/interfaces/mcp/server.py
src/ignis/infrastructure/config/vocabulary_loader.py
src/ignis/infrastructure/persistence/sqlite_repository.py
src/ignis/application/use_cases/{execute_mission,watchlist_period}.py
src/ignis/domain/watchlist_period.py
sql/036_threads_attribution.sql                       # seed-only proposal
```

Complete consumer/test inventory: [research.md](research.md). PostgreSQL JSON storage needs parity
proof, no new column. Package JS/SQL resources and regenerate manifests during implementation.
All agent-context files (`.agents/`, `AGENTS.md`, `CLAUDE.md` and equivalents) are excluded from
this planning run; any later guidance sync requires separately scoped work.

## Complexity Tracking

No constitutional violation proposed. Existing process-local lifecycle intentionally has no durable
resume: restart invalidates tickets/groups. Reuse avoids another public tool but leaves transport
and multi-source writer proof as explicit implementation gates, not claimed capabilities.
