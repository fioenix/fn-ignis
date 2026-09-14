# Feature Specification: End-to-End Orchestration, Background Scheduler & Dockerization

**Feature Directory**: `specs/005-e2e-scheduler-and-docker`
**Created**: 2026-08-31
**Status**: Implemented; production source/observation cutover pending
**Input**: Pha 5 (E2E Scheduler, Docker & Documentation)
**As-built amendment**: 2026-09-13 — optional worker runtime and fail-closed production cutover

**Scope boundary**: This feature owns the optional unattended scheduler and self-hosted deployment.
It does not define the authenticated hosted MCP service, which is owned by
[`specs/006-hosted-mcp-access`](../006-hosted-mcp-access/spec.md).

---

## User Scenarios & Testing

### User Story 1 - Self-Hosted Automated Ingress Scheduler (Priority: P1)

As a self-hosted operator, I need an optional background daemon to run deterministic scheduled
ingress through the HTTP-capable connectors available in its image, persist observations, and
cluster them without requiring an agent or consuming LLM tokens.

**Acceptance Scenarios**:
1. **Given** Scheduler khởi động, **When** đến chu kỳ cron, **Then** tự động kích hoạt Ingest & Cluster pipeline và ghi nhận log rõ ràng.
2. **Given** Nhận tín hiệu SIGINT hoặc SIGTERM, **When** dừng tiến trình, **Then** hoàn thành batch hiện tại và ngắt kết nối an toàn.
3. **Given** a scheduled Vietnamese-market pass, **When** ingress runs, **Then** only scheduled
   ingress applies the regional-script gate; requested and mission probes keep what they find.

---

### User Story 2 - One-Command Self-Hosted Deployment (Priority: P2)

As an operator, I need zero-configuration SQLite for on-demand use and an optional Docker deployment
for the worker and PostgreSQL/TimescaleDB backend. Deploying an artifact and activating a new runtime
are separate operations during a data-model migration.

**Acceptance Scenarios**:
1. **Given** a fresh install, **When** bootstrap completes, **Then** MCP tools work against SQLite
   without a PostgreSQL service or background worker.
2. **Given** a legacy PostgreSQL production corpus and the released `v0.4.0` runtime, **When** the
   operator upgrades that deployment, **Then** the old runtime is quiesced before the snapshot and
   the new runtime starts only after the migration verifier returns `VERIFIED` against a baseline
   generated from that exact snapshot.

---

## Requirements

- **FR-001**: Scheduler daemon PHẢI hỗ trợ cấu hình chu kỳ và xử lý tín hiệu ngắt OS.
- **FR-002**: `Dockerfile` and `docker-compose.yml` MUST keep browser-only connectors out of the
  unattended worker image and register only connector runtimes available there.
- **FR-003**: Documentation MUST cover local standard-input/output MCP configuration for supported
  self-hosted clients. Remote connector onboarding belongs to feature 006.
- **FR-004**: Production source/observation migration MUST follow the canonical runbook in
  `docs/migrations/2026-09-10-source-observation-baseline.md`. Runtime and pruner guards are
  fail-closed backstops and MUST NOT be treated as permission to reorder the procedure.
- **FR-005**: The unattended worker process MUST remain independent from hosted MCP client sessions
  and hosted identity-provider availability.
