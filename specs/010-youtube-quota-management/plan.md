# Implementation Plan: YouTube Quota Management

**Branch**: `codex/010-youtube-quota-management` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/010-youtube-quota-management/spec.md`

## Summary

Add a persistent, backend-parity YouTube quota ledger that atomically admits every outbound API
call before it occurs. Inject one quota manager into the YouTube connector in both worker and MCP
composition roots, propagate the existing ingress trigger to keyword searches, preserve cache hits
as zero-cost, and expose the current quota state through the existing connector diagnostic. The
ledger uses Pacific-Time quota days, a 70-call scheduled search cap inside the 100-call default
search allocation, and a separate 10,000-unit bucket for other endpoints.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastMCP, httpx, pydantic-settings, psycopg/psycopg-pool, Python stdlib `zoneinfo`, SQLite

**Storage**: SQLite default; PostgreSQL 16 production; migration `sql/024_youtube_quota_ledger.sql`

**Testing**: pytest, pytest-asyncio, backend parity tests, repository convention and secret-scanning gates

**Target Platform**: Local MCP hosts and Linux Docker worker

**Project Type**: Python agent harness with FastMCP interface and background worker

**Performance Goals**: One bounded database transaction per uncached YouTube request; no provider call after local refusal

**Constraints**: Atomic across processes sharing one database; fail closed; no API key in storage or output; cache hit remains zero-cost; identical SQLite/PostgreSQL behavior

**Scale/Scope**: At most two rows per Pacific-Time quota day and low double-digit writes per worker cycle; no new MCP tool or scheduler

## Constitution Check

*GATE: Passed before research and re-checked after design.*

- **Zero-token ingress**: PASS. Admission control is deterministic and introduces no LLM call.
- **Connector isolation**: PASS. The quota manager is injected only into YouTube; registry error isolation remains intact.
- **Storage parity**: PASS by design. The repository port and acceptance tests cover both SQLite and PostgreSQL implementations.
- **Time semantics**: PASS. Quota-day identity is explicitly Pacific Time and reset instants are reported in UTC.
- **Simplicity and surgical scope**: PASS. One table, one manager, three operator settings, existing diagnostic surface; no scheduler or cache replacement.
- **Migration and release evidence**: PASS for implementation. Migration 024 is additive and public migration references will be updated; no production migration or release occurs in this task.

## Project Structure

### Documentation (this feature)

```text
specs/010-youtube-quota-management/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── quota-diagnostics.md
└── tasks.md
```

### Source Code (repository root)

```text
src/ignis/
├── application/
│   ├── ports/repository_port.py
│   ├── use_cases/autonomous_discovery.py
│   ├── use_cases/ingest_trends.py
│   └── youtube_quota.py
├── domain/
│   ├── exceptions.py
│   └── youtube_quota.py
├── infrastructure/
│   ├── connectors/registry.py
│   ├── connectors/youtube/youtube_plugin.py
│   └── persistence/{sqlite_repository.py,postgres_repository.py}
└── interfaces/{cli/scheduler.py,mcp/server.py}

sql/
└── 024_youtube_quota_ledger.sql

tests/unit/
├── test_youtube_quota.py
├── test_youtube_plugin.py
├── test_scheduler.py
└── test_sql_packaging.py
```

**Structure Decision**: Keep policy and time calculations in domain/application modules, atomic
storage operations behind the existing repository port, and HTTP admission at the YouTube
connector boundary. Composition roots construct the quota manager from the same repository already
shared by their registry.

## Complexity Tracking

No constitution violations.
