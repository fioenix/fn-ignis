# Feature Specification: Dynamic Ingress Connectors (TikTok, Threads, Instagram Reels)

**Feature Directory**: `specs/002-dynamic-ingress-connectors`
**Created**: 2026-08-31
**Status**: Implemented; cross-route alias reconciliation remains open
**Input**: Pha 2 (Dynamic & Headless Scraping Ingress Feeds) - Triển khai TikTok Plugin, Threads Plugin, và Instagram Reels Plugin.
**As-built amendment**: 2026-09-13 — dual HTTP/browser runtimes and canonical source identity

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - TikTok Trending Ingress Plugin (Priority: P1)

Là hệ thống thu thập xu hướng mạng xã hội, tôi cần một Plugin thu thập các hashtag / video thịnh hành trên TikTok (Việt Nam & Toàn cầu) mà không phụ thuộc vào LLM tokens (Zero-Token Ingress), trích xuất lượt xem, tác giả, hashtag và velocity.

**Why this priority**: TikTok là một trong những nền tảng tạo trend mạnh nhất về video ngắn và âm nhạc tại Việt Nam.

**Independent Test**:
- Khởi tạo `TikTokPlugin`.
- Thực hiện `fetch_signals(geo=GeoCode.VN)`.
- Xác nhận danh sách trả về là các `TrendSignal` có `platform=TIKTOK`, metric_value là play count/view count, metadata chứa hashtags, author info.

**Acceptance Scenarios**:
1. **Given** Nguồn dữ liệu TikTok Trending Web/API khả dụng, **When** plugin thực thi `fetch_signals()`, **Then** trích xuất danh sách `TrendSignal` chuẩn hóa với `platform=TIKTOK`.
2. **Given** TikTok áp dụng rate-limit hoặc chặn request, **When** plugin gặp lỗi, **Then** ngoại lệ được cô lập, Circuit Breaker chuyển trạng thái thích hợp và không ảnh hưởng đến các connector khác.

---

### User Story 2 - Threads Ingress Plugin (Priority: P2)

Là hệ thống thu thập xu hướng thảo luận văn bản và quan điểm xã hội, tôi cần một Plugin thu thập các chủ đề thảo luận nóng trên Meta Threads mà không phụ thuộc vào LLM.

**Why this priority**: Threads là nền tảng thảo luận thời gian thực tăng trưởng nhanh nhất tại Việt Nam hiện nay cho các chủ đề bàn luận, quan điểm và tin nhanh.

**Independent Test**:
- Khởi tạo `ThreadsPlugin`.
- Thực hiện `fetch_signals(geo=GeoCode.VN)`.
- Xác nhận danh sách trả về là `TrendSignal` có `platform=THREADS`, metric_value là reply/like count, metadata chứa username, post url.

**Acceptance Scenarios**:
1. **Given** Endpoint Threads Web / Public Feed khả dụng, **When** gọi `fetch_signals()`, **Then** parse danh sách post thịnh hành sang `TrendSignal`.
2. **Given** Kết nối mạng bị ngắt, **When** gọi plugin, **Then** ném `ConnectorExecutionException` và ghi log an toàn.

---

### User Story 3 - Instagram Reels Ingress Plugin (Priority: P3)

Là hệ thống đo lường xu hướng thị giác và lối sống, tôi cần một Plugin thu thập các Reels thịnh hành / trending audio trên Instagram.

**Why this priority**: Instagram Reels phản ánh xu hướng lối sống, thời trang, F&B và âm nhạc của giới trẻ.

**Independent Test**:
- Khởi tạo `ReelsPlugin`.
- Thực hiện `fetch_signals(geo=GeoCode.VN)`.
- Xác nhận danh sách trả về là `TrendSignal` có `platform=REELS`, metric_value là view/play count, metadata chứa sound/audio title, creator.

---

## Requirements

- **FR-001**: `TikTokPlugin` PHẢI tuân thủ `IConnectorPlugin`, hỗ trợ cào trending hashtags / videos qua public endpoints / fallback parser.
- **FR-002**: `ThreadsPlugin` PHẢI tuân thủ `IConnectorPlugin`, hỗ trợ trích xuất bài viết nóng trên Threads.
- **FR-003**: `ReelsPlugin` PHẢI tuân thủ `IConnectorPlugin`, hỗ trợ trích xuất Reels xu hướng.
- **FR-004**: Tất cả plugins PHẢI tương thích hoàn toàn với `ConnectorPluginRegistry` và `CircuitBreaker`.
- **FR-005**: 100% quá trình thu thập PHẢI là Zero-Token Ingress.
- **FR-006**: Each connector MUST preserve the strongest platform object identifier available in
  metadata and a resolvable permalink. Source identity is decided by
  `src/ignis/domain/source_identity.py`, not by title or raw URL equality.
- **FR-007**: TikTok hashtag/video and Google keyword routes MUST converge on their object
  namespaces. Threads and Reels numeric primary keys MUST remain separate from permalink
  shortcodes until a connector supplies both values or an explicit alias ledger can reconcile
  them; merging those namespaces by string equality can silently join different objects.

---

## Success Criteria

- **SC-001**: Đảm bảo 100% 3 plugins mới đăng ký thành công vào `ConnectorPluginRegistry`.
- **SC-002**: Unit tests & mock tests đạt tỷ lệ vượt qua 100%.
- **SC-003**: Bất kỳ lỗi mạng / parsing nào từ TikTok, Threads hoặc Reels đều bị cô lập hoàn toàn.
