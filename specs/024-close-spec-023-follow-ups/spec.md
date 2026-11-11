# Feature Specification: Close Spec 023 Follow-ups

**Feature Branch**: `024-close-spec-023-follow-ups`

**Created**: 2026-11-11

**Status**: Draft

**Input**: Owner request (11/11/2026): "Xử lý hết đi", covering the items left open after v0.10.0.

## Outcome and why

Spec 023 left three things open. Guidance still describes market vocabulary as synonyms and as search
queries, which stopped being true. The two backends disagree on who owns a re-registered lexicon term. And
`ConnectorRegistry.fetch_from_all`, the untargeted two-stage ingress pass, has no caller left in `src/`: live
collection goes through `search_with_outcomes`. Keeping it implies a discovery path that Constitution
Principle I forbids.

The observable proof: guidance matches the code, both backends give the same row ownership, and the
untargeted pass is gone while every gate that protects live collection is still proved on the live path.

## Clarifications

### Session 2026-11-11

- Q: Which backend's upsert is right? → A: SQLite's `DO UPDATE`: a term an operator registers again is a deliberate choice, as `sql/020` records, so it must stop being a `system` row (agent decided; basis: `sql/020` header, Spec 023 "operator rows stay").
- Q: Does removing `fetch_from_all` need a release? → A: No. It has no caller and no tool reaches it; no version bump in this feature (agent decided; basis: AGENTS.md section 4).
- Q: Does the connector port lose its untargeted feed method? → A: Only members left with no reader after the removal go, and only if no live path or connector contract needs them; planning maps each one (agent decided; basis: Proportion).

- Q: Which port members remain after removing untargeted ingress? → A: Remove `feed_yields_candidate_topics` and `default_feed_scope` with their overrides because only the retired pass and its diagram-routing tests read them. Keep `fetch_signals` and all implementations because the abstract port and default `search_signals` still require them; keep the live scope/search helpers unchanged (agent decided; basis: source and test reader trace).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Guidance and backends agree with the code (Priority: P1)

**Independent Test**: Register a term that a `system` row already holds, on each backend, then read its owner.

**Acceptance Scenarios**:

1. **Given** a `system` row on either backend, **When** an operator registers the same domain and term, **Then** the row's `created_by` and `category` take the new values on both backends.
2. **Given** `AGENTS.md` and the `list_domain_lexicons` description, **When** they are read, **Then** neither claims market terms act as synonyms, search queries, or loaded engine vocabulary.

---

### User Story 2 - No untargeted ingress pass (Priority: P2)

**Independent Test**: Search the repository for the pass; run the gate tests against `search_with_outcomes`.

**Acceptance Scenarios**:

1. **Given** the repository, **When** it is searched, **Then** `fetch_from_all` and the helpers only it used are gone from `src/`.
2. **Given** the self-content guard, the regional-script behaviour, the daily ceiling, error isolation and retired-source refusal, **When** their tests run, **Then** each is proved through `search_with_outcomes` wherever that path has the gate.
3. **Given** a gate that existed only in the untargeted pass, **When** it is removed, **Then** the commit body names it and why no live path needs it.

### Edge Cases

- A test proves behaviour only the untargeted pass had: it is deleted, and its disposition recorded.
- A connector's untargeted method is also used by a health probe or another live path: it stays.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `PostgresTrendRepository.register_lexicon_terms` MUST update `category` and `created_by` on conflict, as SQLite does.
- **FR-002**: `AGENTS.md` and the `list_domain_lexicons` description MUST match the behaviour after Spec 023; the Hermes catalogs MUST be regenerated.
- **FR-003**: `ConnectorRegistry.fetch_from_all` and helpers with no other caller MUST be removed.
- **FR-004**: Every gate on the live path MUST keep a test through the live path.
- **FR-005**: Every MCP tool MUST keep its name and parameters; the catalog stays at 41.
- **FR-006**: No migration; no persisted evidence changes.

## Success Criteria *(mandatory)*

- **SC-001**: A backend-parity test shows the same `created_by` after a re-registration on SQLite and PostgreSQL.
- **SC-002**: `git grep fetch_from_all -- src` returns nothing.
- **SC-003**: The full suite passes in CI, including the PostgreSQL cases.

## Assumptions

- No production environment exists. The historical `docs/PROJECT_REVIEW_CONTEXT.md` and earlier specs stay as dated history.
