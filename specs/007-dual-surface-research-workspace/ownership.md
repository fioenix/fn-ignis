# Dual-Surface Delivery Ownership

This document separates product decisions owned by Codex from implementation work delegated to
Claude Code. The product contract is authoritative; Engineering must not invent behavior that is
not stated here or in `spec.md`, `plan.md`, `data-model.md`, and `contracts/`.

## Product Owner work — Codex

The following decisions are complete and are recorded in the feature artifacts:

| ID | Decision | Evidence location |
|---|---|---|
| P-001 | P1 ships the workspace boundary plus `ATTENTION` and direct `MARKET`; handoff/revision and concurrency hardening follow as P2. | `spec.md`, `plan.md` |
| P-002 | The host Agent owns one-question-at-a-time Q&A, editing, and requester confirmation. fn-ignis receives only the complete confirmed Brief and stores no abandoned draft or transcript. | `spec.md:FR-010`, `spec.md:FR-013`, `spec.md:FR-025`, `contracts/workspace-and-mission.md` |
| P-003 | Market evidence is observation-addressable. `observation_id` is canonical; display URL/title is not an identity key. | `spec.md:FR-026`, `data-model.md`, `contracts/workspace-and-mission.md` |
| P-004 | P1 channel health is keyed by connector surface, not only by top-level platform. | `spec.md:FR-027`, `plan.md` |
| P-005 | SQLite-local is the default shared Ignis database; PostgreSQL is an optional equivalent backend. A schema migration is not shipped without the existing evidence-gated migration rehearsal and verification. | `spec.md`, `plan.md`, `quickstart.md` |

Codex owns the acceptance review for each slice, the decision to promote P2 work, and the release
scope/version. Claude Code does not publish a release or run a production migration as part of
the P1 implementation prompt.

## Engineering work — Claude Code

The P1 implementation scope is T001-T023 in `tasks.md`, including the observation-addressable
citation work required by P-003. T024-T033 are P2 hardening and are intentionally excluded from
the first Claude Code handoff. T034-T037 are final documentation, provenance, and release-gate
work after the selected stories are green.

Every Engineering task must end with targeted tests and must preserve the existing
source/observation/mission-evidence model. Any discovered product ambiguity is returned to Codex
as a decision; it is not resolved by adding a speculative abstraction.
