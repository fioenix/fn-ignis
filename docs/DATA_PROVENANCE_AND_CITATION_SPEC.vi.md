# 📑 PRD & ARCHITECTURAL SPECIFICATION
## Epic 2: Data Provenance, Ingress Health Audit & Citation Attribution Engine

- **Mã Epic:** `EPIC-PROVENANCE-01`
- **Mục tiêu:** Xóa bỏ hoàn toàn hiện tượng nhận định mơ hồ (vague insights) và ảo giác (hallucination) trong các báo cáo nghiên cứu thị trường của AI Agent; cung cấp khả năng kiểm toán nguồn gốc dữ liệu (Data Provenance) và giám sát sức khỏe từng kênh ingress (Channel Health Observability).
- **Trạng thái:** `PARTIALLY IMPLEMENTED` — health cấp platform và citation cho strategic insight
  đã chạy; exact observation reference và hai consumer của report còn mở
- **Người lập:** Antigravity (Product Manager)
- **Implementer dự kiến:** Claude Code (Tech Lead)

---

## 🎯 1. Bối cảnh & Vấn đề Cần Giải Quyết (Problem Statement)

Trong quá trình AI Agent phân tích và xuất báo cáo nghiên cứu thị trường (Market Research Dossier) cho người dùng, hệ thống hiện tại đang gặp **2 lỗ hổng nghiêm trọng về UX và tính trung thực dữ liệu**:

1. **Thiếu Dẫn Chứng Nguồn Cụ Thể (Missing Evidence Citations)**:
   - Các nhận định chiến lược thường mang tính chung chung (ví dụ: *"Người dùng phản hồi nhiều về giá cao và khó tích hợp"*, *"Chỉ số Cơ hội đạt 85 điểm"*).
   - Người dùng và nhà đầu tư không thể biết nhận định này rút ra từ video nào, bao nhiêu bình luận, hay do LLM tự suy diễn.
2. **Không Thể Phát Hiện Kênh Thu Thập Bị Hỏng Âm Thầm (Silent Ingress Failures)**:
   - Nếu một kênh bị lỗi (ví dụ: Threads bị lỗi token 0 posts, TikTok bị captcha 0 videos, YouTube hết quota), hệ thống vẫn tổng hợp báo cáo dựa trên số ít tín hiệu còn lại của Google RSS mà **không cảnh báo cho người dùng biết kênh đó đã bị trống**.
   - Người dùng lầm tưởng báo cáo đã bao quát toàn diện đa kênh (Omni-channel), trong khi thực tế 80% kênh dữ liệu bị thiếu hụt.

---

## 🏛️ 2. Mục tiêu Nghiệp vụ & Kỹ thuật (Goals & Non-Goals)

### Goals
- **Tính Minh Bạch Tuyệt Đối (100% Provenance Auditability)**: Mọi nhận định (`strategic_insights`), hành động đề xuất (`actionable_takeaways`) và cơ hội thị trường (`market_opportunities`) phải gắn liền với ít nhất 1 citation có nguồn gốc rõ ràng.
- **Bảng Kiểm Toán Dữ Liệu Toàn Kênh (Ingress Health Summary Table)**: Hiển thị ngay đầu báo cáo tình trạng từng kênh (Google Trends, YouTube, TikTok, Threads, Instagram Reels), số lượng tín hiệu thu thập, và tín hiệu tiêu biểu.
- **Phát Hiện & Cảnh Báo Kênh Rỗng/Lỗi (Honest Observability)**: Nếu kênh nào có 0 tín hiệu, hệ thống phải giải thích rõ nguyên nhân (chưa authenticate, hết hạn token, hay không có thảo luận về từ khóa).
- **Nâng Cấp Giao Diện HTML Dashboard & Markdown Chat**: Trực quan hóa bảng tóm tắt và các huy hiệu Citation (Pill Badges) trong cả báo cáo HTML lẫn phản hồi chat của Agent.

### Non-Goals
- Không thay đổi thuật toán tính toán `Opportunity Index` cốt lõi (chỉ bổ sung tham số damping nếu số kênh khả dụng < 50%).
- Không lưu trữ toàn bộ nội dung video/audio thô (chỉ lưu trữ metadata, trích đoạn bình luận, và chỉ số tương tác).

---

## 🧱 3. Kiến Trúc & Đặc Tả Chi Tiết (Technical Specifications)

### A. Tầng Domain Models (`src/ignis/domain/harness_models.py`)

Thêm 2 cấu trúc dữ liệu mới:

```python
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
from ignis.domain.value_objects import PlatformType

class ChannelHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"              # Thu thập thành công tín hiệu (>= 1 signals)
    EMPTY_NO_DATA = "EMPTY_NO_DATA"  # Kênh chạy bình thường nhưng không có kết quả cho từ khóa
    AUTH_REQUIRED = "AUTH_REQUIRED"  # Kênh chưa được kết nối tài khoản / token
    RATE_LIMITED = "RATE_LIMITED"    # Kênh bị chạm trần hạn mức (429) hoặc quota
    DEGRADED = "DEGRADED"            # Kênh gặp lỗi mạng / soft-block (Circuit Breaker TRIP)

@dataclass
class CitationEvidence:
    """Bằng chứng trích dẫn cụ thể làm căn cứ cho nhận định."""
    citation_id: str                 # Định danh: 'CIT-01', 'CIT-02'
    observation_id: str              # Observation chính xác trong mission_evidence
    platform: PlatformType           # GOOGLE, YOUTUBE, TIKTOK, THREADS, REELS
    title_or_query: str              # Tiêu đề bài viết / video / từ khóa tìm kiếm
    metric_highlight: str            # '120K views', '+180% velocity', '45 comments'
    author_or_channel: Optional[str] = None
    url: Optional[str] = None        # Đường dẫn trực tiếp (nếu có)
    excerpt: Optional[str] = None    # Trích đoạn bình luận / luận điểm đại diện

@dataclass
class ChannelDataSummary:
    """Tổng hợp dữ liệu và trạng thái kiểm toán của từng kênh kết nối."""
    platform: PlatformType
    status: ChannelHealthStatus
    signals_count: int
    timeframe_used: str              # e.g., '30d (VN)'
    top_citation: Optional[CitationEvidence] = None
    notes: Optional[str] = None      # Ghi chú cảnh báo nếu lỗi / rỗng

@dataclass
class StrategicInsight:
    """Nhận định chiến lược kèm bằng chứng trích dẫn."""
    statement: str                   # Nội dung nhận định
    citations: List[CitationEvidence] = field(default_factory=list)
```

`observation_id` là identity của citation. URL và title chỉ là payload hiển thị, không được dùng
làm một identity key thứ hai. Citation phải trỏ tới observation thuộc mission qua
`mission_evidence`; không deduplicate bằng `platform + source_url/title`.

### Ranh giới implementation hiện tại — kiểm ngày 13/09/2026

- Đã có: năm `ChannelDataSummary` cấp platform với đủ năm status, top citation cho platform khỏe,
  typed citation trên `StrategicInsight`, bảng audit và citation pills trong HTML, cùng payload
  FastMCP tương ứng.
- Chưa có: health riêng cho TikTok Video Grid và TikTok Comments. Cả hai đang gộp dưới
  `PlatformType.TIKTOK`, nên một surface khỏe có thể che surface kia hỏng.
- Chưa có: typed citation trên `MarketOpportunity` và `ActionableTakeaway`; hai model này vẫn giữ
  chuỗi.
- Chưa có: `CitationEvidence.observation_id`. Registry hiện key theo platform cộng URL-hoặc-title,
  nên có thể lệch canonical source identity và không chứng minh được observation nào đã đỡ claim.

Cập nhật `HarnessResearchReport`:
```python
@dataclass
class HarnessResearchReport:
    mission_id: str
    title: str
    scorecard: QualityScorecard
    maturity_stage: TrendMaturityStage
    channel_summaries: List[ChannelDataSummary] = field(default_factory=list)  # [MỚI]
    verified_cross_platform_trends: List[Dict[str, Any]] = field(default_factory=list)
    market_opportunities: List[MarketOpportunity] = field(default_factory=list)
    strategic_insights: List[StrategicInsight] = field(default_factory=list)   # [NÂNG CẤP]
    actionable_takeaways: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

---

### B. Tầng Phân Tích Logic (`StrategicMarketReasoner`)

1. **Tổng Hợp Sức Khỏe Kênh (`summarize_channel_ingress`)**:
   - Duyệt qua toàn bộ danh sách `target_platforms` trong mission:
     - Nếu số `signals > 0`: Gán trạng thái `HEALTHY`.
     - Tìm signal có độ tương tác cao nhất (highest `engagement_rate` hoặc `velocity`) làm `top_citation`.
     - Nếu số `signals == 0`:
       - Kiểm tra registry/auth_manager tương ứng:
         - Nếu chưa authenticate (Threads/Instagram/TikTok) -> `AUTH_REQUIRED` với lưu ý: *"Chưa cấu hình token hoặc phiên trình duyệt"*.
         - Nếu Circuit Breaker đang OPEN -> `RATE_LIMITED` hoặc `DEGRADED`.
         - Nếu mọi thứ bình thường -> `EMPTY_NO_DATA` với lưu ý: *"Không có tín hiệu khớp từ khóa trong timeframe"*.

2. **Tự Động Gắn Citation Vào Nhận Định (`attribute_citations`)**:
   - Khi phát hiện một cụm vấn đề (Pain Point) từ bình luận: Bắt buộc gắn Citation của video và trích đoạn comment cụ thể (`[TikTok Comments: video @creator, 35 phản hồi]`).
   - Khi phát hiện sự chênh lệch Nhu cầu vs Nguồn cung: Bắt buộc gắn Citation của Google Trends (`[Google Trends: +150% velocity]`) và đối chiếu với số lượng video hiện có trên YouTube/TikTok.

---

### C. Tầng Trình Diễn HTML Dashboard (`html_builder.py`)

1. **Section "Data Ingress & Provenance Audit"**:
   - Đặt ngay bên dưới khối Campaign Header và Quality Scorecard.
   - Bảng Responsive giao diện Light Mode:
     - Cột 1: Nền tảng (Platform Icon + Name).
     - Cột 2: Trạng thái (Pill badge màu: Xanh lá cho HEALTHY, Vàng cam cho EMPTY_NO_DATA, Đỏ cho AUTH_REQUIRED/ERROR).
     - Cột 3: Số lượng tín hiệu (`signals_count`).
     - Cột 4: Timeframe & Vùng địa lý.
     - Cột 5: Bằng chứng tiêu biểu (Title + Metric highlight).
2. **Interactive Citation Badges**:
   - Dưới mỗi Strategic Insight và Actionable Takeaway, render danh sách các Pill Badges:
     - Cú pháp: `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">📌 [Nguồn: YouTube] Tên video (Views)</span>`

---

### D. Quy Chuẩn Agent & FastMCP Server (`AGENTS.md` & `server.py`)

1. Cập nhật `get_mission_analysis(mission_id)`:
   - JSON response trả về thêm trường `channel_summaries` và các đối tượng `strategic_insights` có chứa `citations`.
2. Cập nhật **AGENTS.md (Operating Guidelines)**:
   - **MANDATORY**: Mọi báo cáo của Agent xuất ra màn hình chat bắt buộc phải tuân theo cấu trúc:
     1. Campaign Identification Banner.
     2. **Bảng Tóm Tắt Kênh Thu Thập (Data Ingress Summary Table)**.
     3. Quality Scorecard.
     4. Single-Source 4-Lens Breakdown (Có trích dẫn nguồn cho từng lens).
     5. Cơ Hội Thị Trường & Ma Trận Cung Cầu (Có dẫn chứng số liệu).
     6. Kế Hoạch MVP Hành Động.

---

## 🧪 4. Tiêu Chuẩn Nghiệm Thu & Kiểm Thử (Acceptance Criteria)

1. **Unit Tests**:
   - `test_channel_summary_generation`: Kiểm tra tạo đúng summary cho cả 5 nền tảng khi có dữ liệu và khi rỗng 0 signals.
   - `test_connector_surface_health`: Chứng minh TikTok Video Grid và TikTok Comments không che
     trạng thái của nhau.
   - `test_citation_attribution_binding`: Kiểm tra các insights được sinh ra đều có danh sách citations hợp lệ.
   - `test_citation_observation_binding`: Mọi citation trỏ tới một observation thuộc
     `mission_evidence` của mission đang báo cáo.
   - `test_opportunity_and_actionable_citations`: Opportunity và actionable đều mang typed
     citations, không phải chuỗi display rời.
   - `test_report_serialization_backward_compat`: Đảm bảo các mission cũ trước phiên bản này khi deserialize vẫn không bị crash (fallback an toàn).
2. **HTML Generation Test**:
   - Kiểm tra `html_builder.py` render ra HTML chứa đầy đủ bảng Data Ingress và các thẻ Citation pills mà không bị lỗi layout.
3. **Linter & Test Coverage**:
   - Toàn bộ test suite giữ vững 100% pass; không hard-code một test-count snapshot vào spec.
   - `ruff check src/ tests/` không có warning/error.
