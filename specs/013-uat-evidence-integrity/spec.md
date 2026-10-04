# Feature Specification: UAT Evidence Integrity

**Feature Branch**: `release/v0.8.0` (existing branch retained)
**Created**: 2026-10-04
**Status**: Approved scope; acceptance incomplete
**Input**: Owner delegates the complete UAT, lessons/issues, planning, implementation and a second complete UAT loop.

## User Scenarios & Testing

### User Story 1 - Trust the exact public search (Priority: P1)

The researcher can distinguish answers to the assigned query from unrelated platform activity.
**Independent Test**: Two distinct public queries produce separately attributable responses, or explicit unavailable outcomes, without unrelated background data becoming evidence.
**Acceptance Scenarios**:
1. Given unrelated background responses, when a keyword probe runs, then none of those responses proves execution or measured absence.
2. Given a public search response bound to the exact query, when results are read, then only its public records enter the evidence frame.
3. Given an authenticated page that does not execute the search, when the probe ends, then it reports degraded measurement rather than healthy or measured-empty success.

### User Story 2 - Make an evidence-grounded decision (Priority: P1)

The founder researching online retail with at most VND 200 million can inspect supporting and contradictory evidence without being steered toward their initial idea.
**Independent Test**: A confirmed Market frame either admits individually supported claims or exports a Gap Report; Attention cannot manufacture commercial advice.
**Acceptance Scenarios**:
1. Given unqualified topic counts, when Attention renders, then no saturation, demand-gap or capital-allocation recommendation appears.
2. Given competing hypotheses and qualified evidence, when a claim is submitted, then its exact current-frame binding and permission are readable.
3. Given missing metrics, old posts or insufficient sources, when analysis renders, then limitations and withheld conclusions remain explicit.
4. Given stale or foreign evidence, when claims are submitted, then no invalid current finding is rendered.

### User Story 3 - Learn and repeat the real user journey (Priority: P2)

The owner receives reproducible issues, lessons and a complete second UAT, not merely a green unit suite.
**Independent Test**: Every UAT case has an attributable baseline result, remediation task and final real-runtime result or an explicit unresolved failure.
**Acceptance Scenarios**:
1. Given a defect found during UAT, when triaged, then reproduction, root-cause confidence and a tracking issue are recorded without secrets.
2. Given implementation changes, when the second UAT executes, then setup, collection, readback, qualification, claims, export, cancellation and error cases are rechecked.
3. Given skipped backend or live tests, when reporting completion, then those skips cannot count as passed acceptance.

### Edge Cases

Empty search versus missing response; query redirects; wrong response query; stale cached GraphQL signatures; duplicate posts across queries; background notification traffic; expired authentication; unknown timestamps and engagement; partial/cancelled runs; stale claim frames; inaccessible visual preview; accidental client configuration writes.

## Requirements

### Functional Requirements

- **FR-001**: Collection MUST admit only public search responses attributable to the exact assigned query and requested result surface.
- **FR-002**: Unrelated or missing responses MUST NOT attest search execution or measured absence.
- **FR-003**: Public records MUST retain query provenance, source identity, scope and unmeasured facts honestly; cross-query overlap MUST remain inspectable.
- **FR-004**: Stored authentication MUST be validated through actual assigned collection, not status labels alone.
- **FR-005**: Attention MUST NOT infer commercial saturation or positioning from topic counts.
- **FR-006**: Market UAT MUST exercise hypothesis alternatives/null/falsifiers, semantic qualification, current-frame claims, withholding, stale and foreign binding rejection, and maintained report export.
- **FR-007**: Diagnostics MUST NOT persist credentials, raw private response bodies or unrelated account content.
- **FR-008**: Each observed defect MUST have an evidence-backed issue, lesson and independently verifiable remediation task.
- **FR-009**: A second complete UAT MUST cover every baseline case after all remediation, including real runtime and visual artifact inspection where supported.
- **FR-010**: Existing owner edits, normal client configurations and original research data MUST remain intact; no unapproved release or destructive evidence transformation is included.
- **FR-011**: Complete acceptance MUST distinguish implementation, integrated delivery and public activation; failures and unavailable surfaces MUST remain visible.

### Key Entities

- Query response proof: exact assigned query, public result surface, measurement state and public-record identity.
- UAT case: required outcome, baseline evidence, issue, remediation and final evidence.
- Research evidence frame: existing mission/Brief/observations/qualifications/outcomes and claim identities.
- Lesson: observed failure, root cause, correction and prevention.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Zero unrelated background responses authorize evidence or measured-empty outcomes in deterministic regression cases.
- **SC-002**: Every assigned live query has separately inspectable proof or an explicit unavailable state; no query is silently credited from another query's results.
- **SC-003**: Zero unqualified Attention observations produce commercial positioning recommendations in UAT exports.
- **SC-004**: Every rendered Market claim is bound to current permitted evidence; stale/foreign/insufficient cases render zero prohibited claims.
- **SC-005**: Every UAT case in the acceptance ledger is re-executed after remediation, with no missing or indirect proof counted as complete.
- **SC-006**: All confirmed UAT defects have tracked issues and prevention lessons, and final delivery status is verified or explicitly parked.

## Assumptions

- This is a finite assigned task, not background monitoring. Existing approved public social accounts may be used in bounded runs for this goal; posting, messaging and purchased data are excluded.
- SQLite UAT remains separate from normal research. No copied owner credentials or purchased datasets become evidence.
- The founder's budget, online-only channel, Gen Z office audience and lack of suppliers/customers are research constraints, not a preselected winning category.
- A useful business conclusion may be a Gap Report. Full UAT includes a positive Claim Ledger contract path, separately labeled controlled evidence when real market sufficiency is unavailable.
- New findings extend this ledger before implementation; scope does not shrink to the tests already passing.

## Clarifications

### Session 2026-10-04

- Q: May Goal 1 be integrated before Goal 2? → A: Owner explicitly decided "Tao chốt, tạo PR và merge đi, để xong rồi qua Goal 2". Accept the documented historical test-first-order deviation and unavailable independent report-pixel proof as PO acceptance exceptions, not verified tests. Create and merge the reviewed PR into main after fresh gates; do not infer a version bump, tag, publication or Supabase migration from this integration request.

- Q: Does Attention UAT require every insight to be empty? → A: No. The exact missing-reach/maturity refusal and separately authorized follow-up suggestion are allowed; commercial positioning remains prohibited. Correct only the ignored harness and require ATTENTION_CONTEXT/unmeasured citations, no opportunities and no commercial takeaway (agent decided; basis: FR-005/SC-003, actual final output and decision check found no recorded contradiction).

- Q: How should blocked report pixel inspection be completed? → A: Ask the owner directly for screenshots of the maintained report's header, channel status, failed evidence gates and citations. Keep visual acceptance open and do not bypass browser or application safety denial (agent decided; basis: FR-009, Constitution III/IV and decision gate supported fail-closed acceptance).

- Q: May the UAT-50 constraint migration be written and rehearsed? → A: Owner approved the pending scoped request with "tao duyệt": preserve all evidence rows and IDs, correct partial DEGRADED persistence and test isolated UAT SQLite plus disposable PostgreSQL only. Do not apply to Supabase or rewrite historical missions.

- Q: Where should an installed wheel write report output? → A: Use repository reports only when the executing server resides in that exact src checkout; otherwise retain the existing user-home .ignis/reports and temporary fallback behavior. Do not infer a checkout from a fixed parent depth inside site-packages, move existing outputs or alter client configuration (agent decided; basis: actual installed-wheel export into Python's library directory, existing artifact ownership rules and decision check found no recorded contradiction).

- Q: How should mixed successful and failed host search queries be persisted? → A: Permit DEGRADED outcomes to retain a nonnegative partial observation count and the provided query attestation. Keep all unavailable/empty states at zero and HEALTHY nonzero; DEGRADED never measures absence or satisfies a required-channel strategic gate. Preserve the failed historical UAT mission and test storage/readback before a new finite run (agent decided; basis: actual installed-wheel failure, Constitution II error isolation and existing partial-collection contract; decision check found no recorded contradiction).

- Q: Does an unlabeled numeric DOM counter establish TikTok views? → A: No. Keep DOM view measurements unknown even for 0 or 1.2K; only typed JSON playCount establishes views, including a genuine measured zero (agent decided; basis: independent re-review reproduction, Spec 012 ambiguous-counter invariant and decision check found no recorded contradiction).

- Q: How should the reviewed nested-quote defect be corrected? → A: After the architecture checkpoint, enumerate only admitted root public-search posts for direct/browser search, deduplicate and limit that list, and preserve generic recursive trending/suggestion consumers. Track native TikTok query proof and missing measurement separately; no signature, tier, identity, historical evidence or version changes (agent decided; basis: three controlled reviewer reproductions, full owner delegation and decision check found no recorded contradiction).

- Q: Where should the final PostgreSQL contracts run? → A: Run existing dual-backend and Compose initialization contracts on a new labeled disposable localhost TimescaleDB fixture with generated redacted credentials. Preserve Supabase and all owner containers; clean up only this run's owned fixtures (agent decided; basis: delegated complete UAT, no persisted owner evidence touched, decision check found no recorded contradiction).

- Q: How should overlapping Threads query hits be represented? → A: Keep one post and the legacy first-query `matched_keyword`, add an ordered `matched_keywords` list of observed hits, and expose it as additive `probe_keywords` in qualification batches. Do not infer semantic roles, backfill historical evidence, migrate storage or change MCP signatures (agent decided; basis: reproduced #49, owner-authorized remediation and decision check found no recorded contradiction).

- Q: How should reproduced cross-query attribution loss be handled before Goal 2? → A: Track and remediate it within Spec 013's existing FR-003/T013 scope; keep final UAT and visual acceptance open, preserve historical evidence and do not bypass the native app inspection denial (agent decided; basis: owner delegated full UAT defect tracking/remediation, actual two-query synthetic reproduction, no recorded contradiction).

- Q: How should the ignored MCP UAT client bound a host-browser MISSION submission? → A: Use the same 240-second response deadline as native mission ingress, because submission also collects the other authorized channels. Keep the approved 15-minute task lifetime and product timeouts unchanged; read the interrupted canonical journal before a fresh run (agent decided; basis: actual 45-second client timeout terminated the server, journal FAILED and zero mission evidence; owner delegated complete UAT).
- Q: Which TikTok resource identifier should the real Market UAT manifest authorize? → A: Use the existing exact surface `tiktok_video`, not the platform alias `tiktok`. Preserve the initially blocked brief revision and create an immutable corrected revision; do not relax the host-browser admission gate (agent decided; basis: current tool contract and resource validation).

- Q: May the agent complete the UAT, lessons/issues, planning, implementation and final UAT autonomously? → A: Owner explicitly delegated the entire loop in the active goal; no repeated approval for ordinary in-scope fixes is needed.
- Q: Where does this follow-up belong? → A: New sequential Spec 013; preserve Spec 012 and the existing branch (agent decided; basis: distinct complete-UAT remediation objective and no recorded contradiction).
- Q: Does this approval authorize version/tag/release, private activity or paid collection? → A: No; those materially different actions remain separately gated (agent decided; basis: existing release and account boundaries).
- Q: Can isolated query-proof regression and remediation proceed before the missing baseline qualification/claim cases? → A: Yes, as independent offline work; all missing baseline and final cases remain mandatory (agent decided; basis: no persisted evidence or session changes, and the decision check found no recorded contradiction).
- Q: How are real TikTok UAT excerpts qualified? → A: Use TypeSafe as a narrow advisor, then independently review every excerpt before typed immutable submission; seller promotions cannot establish demand, and query wording alone cannot establish counterevidence (agent decided; basis: semantic-judgment routing and evidence-first constraints).
- Q: How may the collector recover the verified server-rendered search result? → A: Extend the existing browser capture boundary only: successful exact navigation, exact BarcelonaSearchResultsQuery expected preloader, identical complete stream preloaderID, no errors and validated public envelope; return only admitted public data (agent decided; basis: actual structural proof, existing tier and constitution, decision check found no recorded contradiction).
