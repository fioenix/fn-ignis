# Feature Specification: Semantic Clustering Engine & Cross-Platform Scorer

**Feature Directory**: `specs/003-semantic-clustering-engine`
**Created**: 2026-08-31
**Status**: Implemented; as-built scoring contract amended 2026-09-13
**Input**: Pha 3 (Semantic Clustering & Cross-Platform Scoring)

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Semantic Topic Clustering (Priority: P1)

Là hệ thống tổng hợp thông tin, tôi cần tự động gom cụm các `TrendSignal` từ nhiều nền tảng khác nhau (YouTube, Google Trends, TikTok, Threads, Reels) có cùng chủ đề ngữ nghĩa lại thành một `TopicCluster` duy nhất.

**Why this priority**: Người dùng và AI Agent không muốn xem danh sách rời rạc từng bài đăng, mà cần nhìn thấy "Chủ đề xu hướng" hợp nhất trên toàn cõi mạng xã hội.

**Acceptance Scenarios**:
1. **Given** Danh sách các signals từ YouTube ("Giá vàng 9999 tăng"), Google Trends ("Giá vàng hôm nay"), Threads ("Biến động giá vàng thế giới"), **When** chạy Clustering Engine, **Then** tất cả được nhóm vào 1 `TopicCluster` có tên đại diện chính xác.

---

### User Story 2 - Cross-Platform Momentum Scoring (Priority: P2)

As a strategic analyst, I need each `TopicCluster` to have one reproducible
`cross_platform_score` (0–100) whose result does not increase merely because the same source was
polled more often.

**Acceptance Scenarios**:
1. **Given** a topic appears on at least three independent platforms with high normalized metric
   volume and velocity, **When** it is scored, **Then** it can reach
   `cross_platform_score >= 80` (`MomentumCategory.BREAKOUT`).
2. **Given** one source was observed repeatedly in the same cluster, **When** it is scored in an
   analysis window, **Then** only its latest exact-ingestion observation contributes.
3. **Given** one source has observations in two clusters, **When** both clusters are read, **Then**
   the source contributes once to each cluster; latest selection is partitioned by
   `(cluster_id, source_id)`, not by source globally.

---

## Requirements

- **FR-001**: Hệ thống PHẢI định nghĩa `IClusteringEngine` port trong `src/ignis/application/ports/clustering_port.py`.
- **FR-002**: `SemanticClusterer` PHẢI hỗ trợ nhóm các signals dựa trên embedding / cosine similarity và đặt tên canonical cho cụm.
- **FR-003**: The system MUST compute `cross_platform_score` through the single implementation in
  `src/ignis/domain/cross_platform_score.py`: platform bands `1 → 0`, `2 → 20`, `3+ → 40`, metric
  volume up to 40 points, and average velocity up to 20 points.
- **FR-004**: `ClusterSignalsUseCase` and autonomous discovery MUST persist clusters and assign
  `cluster_id` to the already-recorded observation. `save_clusters()` MUST NOT create sources or
  observations.
- **FR-005**: Persisted readers and the in-memory clusterer MUST produce the same score inputs: one
  latest observation per source per cluster. Time-window queries MUST use only observations whose
  `time_provenance` is `exact_ingestion` and whose `observed_at` lies in the window.
- **FR-006**: Cluster membership belongs to observations, not canonical sources. One source MAY
  participate in multiple clusters through different observations.
