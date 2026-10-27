# Data Model: Meta Host Search

Proposed extension of Spec 012; no new table or persisted-evidence transformation.

## Source-bound request and ticket

- Add frozen `source=tiktok|threads`, default TikTok, mapping to `tiktok_video`/`threads` surface.
  Retain task/session/request IDs, mode, exact finite query IDs/text/limits, issue/expiry and caller.
- Browser descriptor: exact origin/route, packaged extractor/handoff; Threads `threads-search-top-v1`,
  TikTok unchanged. API descriptor: `threads-mcp-keyword-v1`, task-authorized approved external MCP;
  not an Ignis API client or credential. Both are strict allowed variants for Threads only.
- Freeze source-specific attribution templates; tactical uses packaged seed, mission its repository.
  Missing Threads vocabulary never falls back to TikTok templates. Unsupported locale fails closed.
- Mission retains manifest/Brief/plan/frame revisions. Sibling source tickets share those bindings;
  stage all required host surfaces before a single writer executes. Group by mission/caller/frame
  and reject duplicate sources. No new persistent queue, tool argument or second run.

## Staged answer

Common identity/source/path/version, one answer per exact approved query, current capture time,
status/reason and bounded records. Strict union: browser variant uses page URL/search verification;
API variant uses provider operation, executed keyword, public grant evidence and scope/limits, not
pretend DOM attestation. Legacy TikTok answers remain valid only on TikTok tickets.

Host API attestation: provider `fioenix/threads-mcp`, keyword-search operation class,
`APPROVED_PUBLIC_KEYWORD_SEARCH`, verification time and non-secret verification reference without
account identity. Actual provider operation/fields must be bound from its supported contract before
activation. SELF_ONLY/NOT_PERMITTED/unverified approval cannot yield evidence. Host is trusted
collector; a JSON attestation is not cryptographic proof. One selected path per ticket/batch;
no filling query gaps with another path. Source authorization alone is not grant authorization.

## Public record and content reference

| Field | Rule |
|---|---|
| Content reference | Platform and permalink shortcode; API numeric ID only when actually supplied. Distinct namespaces; existing alias ledger only on same-record co-witness. |
| Source URL | Validate public post route, rebuild `/t/<shortcode>` via existing Spec 015 helper before receipt/store. Drop `/@<author>`, profiles, avatar links and tracking. |
| Excerpt | Isolated body only; seeded attribution stripping, then PII/mention cleanup before first output/write. No alt-only/body fallback to whole card. |
| Publication | Exact aware `time[datetime]` or API publication field; null if unknown. Never relative-time/capture substitution or impossible future publication. |
| Query/capture | Exact executed query and IDs with capture in ticket lifetime; preserve multi-query lineage. Exact ingestion clock remains separate. |
| Counters | Typed components below; no invented view count or Share-to-quotes mapping. |
| Path | Immutable collection family/revision/sampling identity at observation level. |

One record per canonical post, not per image/media/quote link. Ambiguous nested cards are dropped
or degraded. Missing ID/link becomes separately counted `source_verifiable=false` context excluded
from permitted claims (Spec 015 FR-006). Numeric content ID without verified link displays `link
unavailable`. Unknown author marker when author not collected; no identity fetched just for counting.

## CounterMeasurement

Kind/unit, `raw_display`, nullable numeric `value`, `precision=exact|rounded|unknown`.
Observed browser kinds: likes/replies/reposts/shares. API quotes/views only if reported. `12` is an
exact displayed integer; `1.4K` is rounded 1400 with its raw display preserved; blank is unknown.
Unobserved number syntax stays unknown. Rounded/missing components never populate an exact-looking
legacy total. Periods retain precision/sample limits and known components; incompatible aggregates
are unknown with uncounted items. Free-text personal names remain Spec 015 FR-012's documented limit.

## CollectionPathIdentity and probe attestation

- Legacy `playwright:threads_session` only with explicit stored proof.
- `host_browser:threads-search-top-v1`, Top visible-sample semantics.
- `threads_mcp:threads-mcp-keyword-v1`, actual API ordering/limits recorded.
- Other channels retain established paths/revisions, including flag-free Reels.

Identity includes method family, revision and measurement-affecting sampling/order; excludes random
request IDs, capture time, relay port, session/account identity. Persist proposed `collection_path`,
`connector_revision`, `sampling` in existing immutable observation metadata and probe
`scope_attestation` JSON, preserving existing keys. Observation metadata already supports path but
is not normalized on every legacy Threads row; in-memory registry connector fields do not by
themselves prove persisted probe provenance. Empty probes need attestation because no observation exists.

Read-time legacy classification uses explicit metadata or matching persisted plan, records its
basis, never writes history or infers from dates/cookies. Missing/conflicting path is unknown.
Extend internal PeriodCoverage/SeenSnapshot and PeriodItem inputs before merge; per topic/channel/
axis apply the coordinator's delegated acceptance decision (28/10/2026), preserving the existing
coverage/cadence/judgment gates: both sides wholly unknown retain legacy comparability and response
shape, without a path reason; one proven identical identity on both sides is comparable; different
proven identities refuse with `collection_path_changed`; one proven side versus one wholly unknown
side refuses with `collection_path_unknown`. A side with two or more proven identities, or with a
proven identity and an unknown observation/probe, refuses with `collection_path_mixed`, even if both
periods contain the same mixture. These path reasons suppress deltas; do not discard measurements,
alter placement or infer missing provenance. This supersedes the earlier blanket unknown refusal
in research R6 and preserves unchanged Spec 016/018 legacy channels.

## Lifecycle

Existing PREPARED → STAGED → SUBMITTING (mission) → ACCEPTED or terminal REJECTED/EXPIRED/CANCELLED/
FAILED. Stage freezes path; invalid input rejects whole payload before writes. All required sibling
sources staged/fresh before submit enters one writer; incomplete group refuses without writes.
Group cancellation/expiry invalidates siblings; successful receipt caches for each member. Replay,
caller isolation, lifetime, cancellation drain and uncertain-persistence journal/readback remain.
Restart invalidates process-local tickets/groups; no durable resume or automatic resubmit.

Tactical returns sanitized observations, no mission persistence. Mission reuses canonical sources,
immutable observations, associations and qualification. Store allowlisted cleaned JSON only, never
raw API payload/errors, HTML, author identity or credentials. SQLite/PostgreSQL parity is required;
036 adds vocabulary rows idempotently, no schema/evidence/marker rewrite.
