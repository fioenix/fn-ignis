# Feature Specification: End-to-End Orchestration, Background Scheduler & Dockerization

**Feature Directory**: `specs/005-e2e-scheduler-and-docker`
**Created**: 2026-08-31
**Status**: Ready for Implementation
**Input**: Pha 5 (E2E Scheduler, Docker & Documentation)

---

## User Scenarios & Testing

### User Story 1 - Self-Hosted Automated Ingress Scheduler (Priority: P1)

Là người vận hành hệ thống self-host, tôi cần một background daemon chạy định kỳ (mỗi 15 phút) tự động cào tín hiệu đa kênh và gom cụm chủ đề vào TimescaleDB mà không cần can thiệp thủ công (Zero-Token Ingress).

**Acceptance Scenarios**:
1. **Given** Scheduler khởi động, **When** đến chu kỳ cron, **Then** tự động kích hoạt Ingest & Cluster pipeline và ghi nhận log rõ ràng.
2. **Given** Nhận tín hiệu SIGINT hoặc SIGTERM, **When** dừng tiến trình, **Then** hoàn thành batch hiện tại và ngắt kết nối an toàn.

---

### User Story 2 - One-Command Self-Hosted Deployment (Priority: P2)

Là CTO/DevOps, tôi cần triển khai toàn bộ hệ thống (TimescaleDB + Background Worker + FastMCP Server) chỉ với `docker compose up -d`.

---

## Requirements

- **FR-001**: Scheduler daemon PHẢI hỗ trợ cấu hình chu kỳ và xử lý tín hiệu ngắt OS.
- **FR-002**: `Dockerfile` và `docker-compose.yml` PHẢI tối ưu hóa image size và cấu hình network an toàn.
- **FR-003**: Cung cấp tài liệu kết nối FastMCP cấu hình JSON cho Claude Desktop và Antigravity.
