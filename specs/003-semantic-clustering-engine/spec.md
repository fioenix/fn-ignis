# Feature Specification: Semantic Clustering Engine & Cross-Platform Scorer

**Feature Directory**: `specs/003-semantic-clustering-engine`
**Created**: 2026-08-31
**Status**: Ready for Implementation
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

Là nhà phân tích chiến lược, tôi cần mỗi `TopicCluster` có một điểm số đa kênh `cross_platform_score` (0-100) và `MomentumCategory` phản ánh độ lan tỏa và tốc độ tăng trưởng.

**Acceptance Scenarios**:
1. **Given** Chủ đề xuất hiện trên >= 3 nền tảng với lượng tương tác cao, **When** tính điểm, **Then** `cross_platform_score` >= 80 (MomentumCategory.BREAKOUT).

---

## Requirements

- **FR-001**: Hệ thống PHẢI định nghĩa `IClusteringEngine` port trong `src/ignis/application/ports/clustering_port.py`.
- **FR-002**: `SemanticClusterer` PHẢI hỗ trợ nhóm các signals dựa trên embedding / cosine similarity và đặt tên canonical cho cụm.
- **FR-003**: Hệ thống PHẢI tính toán `cross_platform_score` dựa trên entropy nền tảng và metric volume.
- **FR-004**: `ClusterSignalsUseCase` PHẢI persist clusters và cập nhật `cluster_id` cho signals vào database.
