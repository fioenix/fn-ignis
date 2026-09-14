# Tasks: E2E Scheduler, Dockerization & Documentation

## Phase 1: Background Scheduler
- [x] T001 Cài đặt `src/ignis/interfaces/cli/scheduler.py`
- [x] T002 [P] Viết unit tests cho scheduler trong `tests/unit/test_scheduler.py`

## Phase 2: E2E Integration Test
- [x] T003 Viết test luồng hoàn chỉnh (Ingress -> Clustering -> Artifacts) trong `tests/integration/test_end_to_end.py`

## Phase 3: Dockerization & Documentation
- [x] T004 Tạo `Dockerfile` và cập nhật `docker-compose.yml`
- [x] T005 Cập nhật `README.md` với đầy đủ kiến trúc, hướng dẫn deploy và MCP client config

## Phase 4: As-Built Runtime and Migration Boundary (2026-09-13)

- [x] T006 Keep the unattended worker image browser-free and register only HTTP-capable connectors
- [x] T007 Add fail-closed repository and pruner guards for the schema-created/backfill-missing state
- [x] T008 Document the production activation boundary and canonical cutover procedure

Production execution is owned once, by T020 in
`specs/001-core-storage-stable-ingress/tasks.md`; this feature depends on that task and does not
duplicate it here.
