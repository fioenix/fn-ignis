# Specification Quality Checklist: Ignis Relay

**Purpose**: Review written scope before technical planning, not certify runtime acceptance.
**Created**: 2026-10-04
**Feature**: [spec.md](../spec.md), review revision R1

## Content Quality

- [x] User outcome, intended audience and assumptions are explicit.
- [x] Requirements describe behavior rather than selecting libraries or backend implementation.
- [x] Mandatory user stories, edge cases, requirements and measurable outcomes are present.
- [x] Approved visual direction is distinguished from proposed runtime behavior and illustrative mock data.

## Requirement Completeness

- [x] No unresolved requirement placeholder remains; expanded written scope is presented for owner review, not inferred approved.
- [x] Mission authority plus five visual columns preserve all six evidence responsibilities and failure/withholding paths.
- [x] Requirements preserve source lineage, role separation, unknown values and critical thinking.
- [x] Keyboard, reduced-motion, responsive and actual visual acceptance are specified.
- [x] Live viewer cannot start a collector, fabricate stage progress or silently promote stale claims.
- [x] Current-run coherence, duplicate/reordered reads, freshness, terminal collection versus later analysis and finite viewing boundaries are defined.
- [x] Existing signatures, sessions, persisted evidence and release scope are protected.
- [x] Collection completion, research termination and viewer expiry have distinct behavior.
- [x] Motion-only pause, refresh pause and mission execution have distinct behavior.
- [x] Actual concurrent work, sequential fallback and unavailable capacity are distinguished.
- [x] Evidence-bearing handoffs, shared-source identity, findings history and obsolete-result rejection are specified.
- [x] Provisional strategic claims still require current-frame permission.
- [x] Follow-up scope, budget, authority and stopping conditions are specified.
- [x] Access and masking cover events, handoffs and findings as well as observations.

## Acceptance Traceability

These references identify required future acceptance evidence, not results already achieved.

| Requirements | Acceptance coverage |
|---|---|
| FR-001, FR-003 | US1 independent test; SC-001: all six responsibilities inspectable |
| FR-002, FR-024 | US1 scenario 2; SC-008, SC-011: recorded arrivals and zero duplicated/fabricated activity |
| FR-004, FR-018 | US1 scenario 3; US3 scenario 3; SC-004, SC-006: role separation and withheld verdict |
| FR-005, FR-009, FR-014, FR-015, FR-025 | US3 scenarios 1–2 and edge cases; SC-008, SC-010: scope/freshness, incomplete or changed frames and missing facts |
| FR-006, FR-012, FR-017, FR-028 | US1 scenario 1; SC-009, SC-016: real read-only mission, no writes/collection and protected inspection surfaces |
| FR-007, FR-008, FR-016 | US2 scenarios 1–3; SC-002, SC-003, SC-006, SC-009: separate controls, keyboard, reduced motion and viewer lifecycle |
| FR-010, FR-022 | US3 scenario 3; US4 scenarios 3–4; SC-010, SC-013: findings revisions and current claim permission |
| FR-011, FR-026 | SC-007, SC-015: rendered light hierarchy, maintained tokens and non-color cues |
| FR-013, FR-027 | Boundary review: no signature/tier/legacy-evidence/client-setting/release changes solely for presentation; no independent agent platform |
| FR-019, FR-020, FR-021 | US4 scenarios 1–2 and independent test; SC-011, SC-012: work receipts, actual concurrency and evidence identity |
| FR-023, FR-029 | US5 scenarios 1–3; SC-014, SC-017: traceable feedback, authority exhaustion and qualified terminal states |
| All visual motion requirements | SC-005, SC-007: measured reference-machine motion and actual browser walkthrough, not mock approval alone |

## Feature Readiness

- [x] Owner selects FR-006's scope: real mission dashboard.
- [x] Owner approved the light-mode mock direction.
- [x] Five user stories and 29 requirements have reviewable acceptance coverage.
- [x] Self-review resolves pause/lifecycle wording conflicts without narrowing the research-team scope.
- [x] Owner explicitly approves written scope R1, including observable research work, findings revisions and bounded follow-up: "Duyệt written scope R1" on 2026-10-04.
- [x] Owner approval is recorded in spec and canonical backlog.
- [x] Completion audit verifies both approval records and unchanged no-plan/no-runtime boundary.

## Notes

Self-review is documentation review, not independent security review or executed UAT.
Structural checks cover required sections, identifier continuity, acceptance references, unresolved
placeholders, local mock identity and the limited changed-file set. `git diff --check` covers
whitespace only. No Spec 014 runtime, performance, accessibility, live collection or deployed-system
acceptance has been performed.

No `.specify/extensions.yml` exists in this checkout; before/after specification hooks are absent.
The selected feature remains `specs/014-evidence-factory`; no feature or branch was created.
Plan/tasks, product implementation, social sessions, database and release work remain outside this
Goal. The owner approved R1 on 2026-10-04; this closes the specification Goal, not product
implementation or release. The documentation remains local and uncommitted at this checkpoint.
