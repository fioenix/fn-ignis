# Tasks: Close Spec 023 Follow-ups

**Input**: [spec.md](spec.md), [plan.md](plan.md). Observe each RED before the change.

## Phase 1: User Story 1 — guidance and backends agree (P1)

- [x] T001 [US1] Correct `AGENTS.md` section 3 so `market_lexicons` is not described as synonyms or as search queries.
- [x] T002 [US1] Add a two-backend parity test: re-registering a `system` row's domain and term leaves the same `created_by` and `category` on SQLite and PostgreSQL. Observe it fail for PostgreSQL if a local DSN exists; otherwise state that the RED is unobserved and CI proves the GREEN.
- [x] T003 [US1] Change the PostgreSQL upsert to `DO UPDATE` as the plan says.
- [x] T004 [US1] Correct the `list_domain_lexicons` description and regenerate both Hermes catalogs; `tests/unit/test_tool_manifests_drift.py` and `tests/unit/test_public_mcp_contract.py` green.

Local parity evidence: SQLite passes; PostgreSQL RED and GREEN are unobserved locally and reserved for CI (no local PostgreSQL run).

## Phase 2: User Story 2 — no untargeted ingress pass (P2)

- [x] T005 [US2] Re-point each test listed in the plan to `search_with_outcomes` where the gate exists on that path, keeping it green before any code is removed. Tests proving only the untargeted pass wait for T006.
- [x] T006 [US2] Remove `fetch_from_all`, helpers left with no caller, and port members left with no reader. Delete the tests that proved only that code. The commit body lists each test's disposition and each kept or removed port member with its reason.

## Phase 3: Acceptance

- [x] T007 Run every touched module, `tests/unit/test_public_mcp_contract.py`, `tests/unit/test_repo_conventions.py`, `tests/unit/test_tool_manifests_drift.py`, and `ruff check src/ tests/`; record results in `.handoff/024-verification.md`.
- [x] T008 Close the `fetch_from_all` debt in `BACKLOG.md`, keeping full Vietnamese diacritics and the released banner wording unchanged.
