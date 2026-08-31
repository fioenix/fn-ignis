# Implementation Plan: E2E Scheduler, Dockerization & Production Documentation

**Feature Directory**: `specs/005-e2e-scheduler-and-docker`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Technical Context

- **Scheduler**: Async loop với `asyncio.sleep` / cron interval, graceful shutdown
- **Containerization**: Multi-stage Dockerfile dựa trên `python:3.12-slim` + `uv`
- **Docker Compose**: `timescale`, `ignis-worker`, `ignis-mcp`

---

## Structure

```text
├── Dockerfile
├── docker-compose.yml
├── src/ignis/interfaces/cli/scheduler.py
└── tests/integration/test_end_to_end.py
```
