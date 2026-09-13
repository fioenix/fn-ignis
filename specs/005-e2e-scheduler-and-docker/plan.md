# Implementation Plan: E2E Scheduler, Dockerization & Production Documentation

**Feature Directory**: `specs/005-e2e-scheduler-and-docker`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Technical Context

- **Scheduler**: Async loop với `asyncio.sleep` / cron interval, graceful shutdown
- **Containerization**: Multi-stage Dockerfile dựa trên `python:3.12-slim` + `uv`
- **Zero-config path**: SQLite plus on-demand MCP; no worker or database service required
- **Docker Compose**: optional TimescaleDB and `ignis-worker` services; local MCP remains an
  independently launched standard-input/output process
- **Worker boundary**: HTTP-capable connector runtimes only; browser probes remain operator-side
- **Hosted boundary**: authenticated remote MCP is a separate runtime owned by feature 006, not an
  implicit mode of the scheduler container
- **Migration activation boundary**: artifact staging may happen early, but the new runtime starts
  only after the quiesced-snapshot baseline, `sql/016`, backfill, and verifier status `VERIFIED`

---

## Structure

```text
├── Dockerfile
├── docker-compose.yml
├── src/ignis/interfaces/cli/scheduler.py
└── tests/integration/test_end_to_end.py
```

The canonical production procedure is maintained in
[`docs/migrations/2026-09-10-source-observation-baseline.md`](../../docs/migrations/2026-09-10-source-observation-baseline.md#production-cutover-runbook).
