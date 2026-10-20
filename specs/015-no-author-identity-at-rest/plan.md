# Implementation Plan: No Author Identity at Rest

**Branch**: `codex/no-author-identity-at-rest` | **Date**: 2026-10-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/015-no-author-identity-at-rest/spec.md`

## Summary

Ignis must keep and return no content-author identity, except accounts the user declares per
mission. One domain policy strips identity where collected data enters a mission. That point is
before clustering and persistence, and a fail-closed repository guard backs it.

The policy replaces identity with three things:
- a per-mission HMAC author marker, keyed by a Fernet-encrypted per-mission key;
- an identity-free content reference;
- placeholder tokens for `@mentions`.

Declared accounts live in a mutable per-mission table. Observations without a content reference
are kept as context that cannot support a permitted claim. A runtime conformance test over every
connector enforces the invariant. A read-only script inventories legacy data. Details:
[research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastMCP and `cryptography` (Fernet), both existing; no new dependency.

**Storage**: SQLite (default) and PostgreSQL 16; additive migration `sql/031` with SQLite parity.

**Testing**: pytest; dual-backend integration fixture (`IGNIS_TEST_POSTGRES_DSN` for PostgreSQL).

**Target Platform**: Local MCP server (stdio) on macOS and Linux.

**Project Type**: Single Python project (MCP server, library, CLI scripts).

**Performance Goals**: The policy adds one HMAC and one regular-expression pass per observation.
That is negligible next to network collection; no stated target is affected.

**Constraints**:
- no identity in any durable store, response, report or log;
- exactly one new MCP tool, `set_mission_declared_accounts` (OG-1 approved);
- no change to legacy data without an owner disposition.

**Scale/Scope**:
- 8 connector paths;
- 2 repositories;
- 5 MCP response shapes;
- 1 report template;
- 1 migration.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment |
|---|---|
| I. Mission-bound autonomy | PASS. No background work. The inventory is a manual, read-only script. |
| II. User-controlled connectors | PASS. Connectors keep their port. Live link probes (R5) use public pages without a session. Missing channels stay visible. |
| III. Evidence-first, both backends | PASS. Both backends change together. Markers sit on `mission_evidence`, keeping the source, observation and association separation. Removing handle-URL fallback stops a second identity policy from living in URLs. Unverifiable content fails closed and cannot support a claim. |
| IV. Deterministic report builders | PASS. Changes go through the maintained template and builder only. |
| V. Simplicity and data-driven vocabulary | PASS with notes. The author field list is a structural payload schema, not market vocabulary (R2). The mention regex is a character-class exception and is commented. One new table for declarations is needed because the manifest is immutable (R8). |
| VI. Evidence-gated migration | PASS. `031` is additive and transforms no persisted evidence. Legacy rewrites are gated on the owner (FR-015). |
| Product reasoning | PASS. The outcome is stated in the spec. The cost and friction of declarations are exposed, and limitations stay visible: link unavailable, markers unavailable, names in free text. |

Post-design re-check: PASS. The design introduced no further deviation.

## Owner Gates

| Gate | Decision needed | Blocks |
|---|---|---|
| OG-1 | **Approved 2026-10-20 by the owner**: new MCP tool `set_mission_declared_accounts` (one more tool: 47 → 48 after PR #51; 44 on today's `main`) per [contracts/mcp-surface.md](contracts/mcp-surface.md) | User Story 1 scenario on declared accounts, FR-018, FR-019, SC-009 |
| OG-2 | **Approved 2026-10-20 by the owner**. Merge order: implement after PR #51 (Spec 014) merges, rebased on `main`, so migration `031` follows `030` and Spec 014's snapshot rows fall under FR-002 and FR-016 | Migration numbering and Spec 014 snapshot coverage |
| OG-3 | Disposition of legacy identity found by the inventory (dev PostgreSQL, caller SQLite) | FR-015 apply step only; the inventory itself is not gated |

## Project Structure

### Documentation (this feature)

```text
specs/015-no-author-identity-at-rest/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── mcp-surface.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks output, not created here
```

### Source Code (repository root)

```text
src/ignis/
├── domain/
│   ├── author_identity.py          # new: field list, policy, marker, mention tokens, concentration
│   ├── self_content.py             # reused key lists
│   ├── source_identity.py          # handle-URL fallback refused; unverifiable_content identity
│   ├── research_workspace.py       # CONTEXT_ONLY forced for unverifiable content
│   └── harness_models.py           # author_or_channel only for declared accounts
├── application/use_cases/
│   ├── execute_mission.py          # policy before save_clusters/save_signals
│   ├── host_browser_mission.py     # self-content exclusion before policy
│   ├── get_mission_analysis.py     # author_concentration replaces top_creators
│   └── get_evidence_qualification_batch.py
├── infrastructure/
│   ├── auth/crypto.py              # reused Fernet for mission keys
│   ├── connectors/tiktok/tiktok_plugin.py     # fixed-salt pseudonymization and log line removed
│   ├── connectors/threads/threads_plugin.py   # operator username log line removed
│   ├── harness/strategic_reasoner.py
│   ├── persistence/sqlite_repository.py       # DDL parity, guard, key and declaration storage
│   ├── persistence/postgres_repository.py     # guard, key and declaration storage
│   ├── security/pii_sanitizer.py              # mention tokenisation helper
│   └── templates/html/mission_report.html
└── interfaces/mcp/server.py        # response shapes; new tool (OG-1 approved)

sql/031_author_identity_at_rest.sql
scripts/inventory_author_identity.py

tests/
├── unit/test_author_marker.py
├── unit/test_unverifiable_source.py
├── integration/test_author_identity_conformance.py
├── integration/test_declared_accounts.py
└── integration/test_author_identity_parity.py
```

**Structure Decision**: The existing single-project layout. New behaviour sits in one domain module
(`author_identity.py`) called from the application layer. The repositories only store and guard.

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
|---|---|---|
| `mission_author_keys` table with encrypted keys | Markers must resist a dictionary attack by anyone holding the database (FR-008) | A stored plain salt makes the database alone sufficient to reverse a known handle |
| `mission_declared_accounts` table | Declarations must be withdrawable (FR-018) | The mission manifest is frozen and digest-bound |
| Placeholder tokens in stored text | Withdrawal must remove declared mentions from immutable observations | Rewriting observations breaks immutability and frame digests |
