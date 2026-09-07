# fnIgnis 🔥 — Cẩm nang Tích hợp Meta (Threads & Instagram Reels)
## Kiến trúc Dual-UX: Trải nghiệm 1-Chạm cho Non-Tech & Deep Graph API cho Chuyên gia

Tài liệu này định nghĩa chi tiết kiến trúc tích hợp, hướng dẫn từng bước (Step-by-step Guide) và **Kịch bản Tự động hóa Thực thi dành cho AI Agent (Agent-Operable Runbook)** để kết nối hai nền tảng thảo luận và nội dung ngắn hàng đầu của Meta: **Threads** và **Instagram Reels**.

---

## 📑 Mục lục
1. [Mô hình Dual-UX: Lựa chọn Phù hợp với Bạn](#1-mô-hình-dual-ux-lựa-chọn-phù-hợp-với-bạn)
2. [Tier 1: Trải nghiệm 1-Chạm cho Non-Tech User (Zero-Setup Onboarding)](#2-tier-1-trải-nghiệm-1-chạm-cho-non-tech-user-zero-setup-onboarding)
   - [Cách thức hoạt động](#cách-thức-hoạt-động-tier-1)
   - [Dữ liệu thu được & Giới hạn chấp nhận](#dữ-liệu-thu-được--giới-hạn-chấp-nhận)
3. [Tier 2: Tích hợp Sâu Meta Graph API cho Chuyên gia (Deep API & Enterprise)](#3-tier-2-tích-hợp-sâu-meta-graph-api-cho-chuyên-gia-deep-api--enterprise)
   - [Đăng ký ứng dụng trên Meta Developer Portal](#bước-1-đăng-ký-ứng-dụng-trên-meta-developer-portal)
   - [Phân quyền Scopes & Cấu hình Redirect URI](#bước-2-phân-quyền-scopes--cấu-hình-redirect-uri)
   - [Thiết lập Credentials vào file .env](#bước-3-thiết-lập-credentials-vào-file-env)
   - [Thực thi OAuth 2.0 Flow qua FastMCP Tools](#bước-4-thực-thi-oauth-20-flow-qua-fastmcp-tools)
4. [🤖 Kịch bản Tự Động Hóa Dành Riêng Cho AI Agent (Agent Runbook)](#4--kịch-bản-tự-động-hóa-dành-riêng-cho-ai-agent-agent-runbook)
5. [Kiến trúc Bảo mật Credentials & Vòng đời Token](#5-kiến-trúc-bảo-mật-credentials--vòng-đời-token)
6. [Xử lý Sự cố & Câu hỏi Thường gặp (FAQ)](#6-xử-lý-sự-cố--câu-hỏi-thường-gặp-faq)

---

## 1. Mô hình Dual-UX: Lựa chọn Phù hợp với Bạn

Để cân bằng giữa **sự tiện lợi tối đa khi bắt đầu** và **chiều sâu dữ liệu ở quy mô doanh nghiệp**, `fn-ignis` phân chia thành 2 cấp độ trải nghiệm:

| Đặc tính so sánh | Tier 1: Non-Tech ("Just Works") | Tier 2: Deep Graph API (Pro / Enterprise) |
|---|---|---|
| **Đối tượng phù hợp** | Marketer, Founder, Chiến lược gia, Người mới bắt đầu | Data Engineer, Growth Agency, CTO, AI Agent tự động |
| **Yêu cầu kỹ thuật** | **Không cần** Meta Developer Account, không cần tạo App | Cần Meta Developer Account, App ID & Secret |
| **Phương thức xác thực** | 1-Click Browser Session Capture (tương tự TikTok) | OAuth 2.0 Authorization Code $\rightarrow$ Long-Lived Token |
| **Thời hạn Token** | Theo phiên đăng nhập trình duyệt web | **60 ngày** (Tự động refresh khi còn $\le 10$ ngày) |
| **Dữ liệu Threads** | Text bài viết, lượt likes, replies công khai, hashtag search | Full text, views/impressions, exact replies, quotes, reposts |
| **Dữ liệu Reels** | Video công khai, plays, likes, comment count, caption | Video plays, reach, interactions, hashtag top media |
| **Rào cản vận hành** | Có thể bị Meta yêu cầu giải captcha nếu quét dày đặc | Cần Meta App Review nếu muốn tìm kiếm từ khóa rộng ngoài tài khoản |

---

## 2. Tier 1: Trải nghiệm 1-Chạm cho Non-Tech User (Zero-Setup Onboarding)

### Cách thức hoạt động Tier 1
Tương tự như cơ chế của TikTok Ingress trong `fn-ignis`, người dùng chỉ cần sử dụng tài khoản cá nhân có sẵn:

1. **Khởi chạy lệnh xác thực**:
   - Trong giao diện chat với AI Agent (Claude, Antigravity, Codex) hoặc FastMCP, gọi tool tương ứng mà **không truyền tham số nào**:
     ```
     authenticate_threads()
     authenticate_instagram()
     ```
   - Khi không có `auth_code`, hệ thống mặc định chạy luồng Tier 1. Nếu bạn đã cấu hình OAuth nhưng vẫn muốn ép chạy Tier 1, truyền `browser_login=true`.
2. **Xác nhận đăng nhập trên trình duyệt**:
   - `fn-ignis` khởi động một phiên Playwright Chromium biệt lập.
   - Người dùng đăng nhập tài khoản Threads hoặc Instagram trên màn hình trình duyệt.
   - Ngay khi đăng nhập thành công, `fn-ignis` tự động bóc tách session token an toàn, đóng cửa sổ trình duyệt và mã hóa AES-256 vào cơ sở dữ liệu (`platform_credentials`).
3. **Phiên Tier 1 và token Tier 2 tồn tại song song**:
   - Session trình duyệt được lưu dưới khóa riêng (`threads_browser`, `instagram_browser`), tách biệt hoàn toàn với bản ghi OAuth (`threads`, `instagram`). Kết nối Tier 1 không ghi đè token Tier 2 và ngược lại.
   - `ThreadsPlugin` và `ReelsPlugin` chọn đường ingress theo thứ tự ưu tiên: Graph API khi còn token hợp lệ → session trình duyệt → endpoint công khai legacy. Nhờ vậy, người dùng phổ thông cào được bài viết và hashtag công khai mà không vướng rào cản Meta App Review.
   - Kiểm tra cả hai tier bằng `get_threads_auth_status()` hoặc `get_instagram_auth_status()`: trường `browser_session` mô tả trạng thái phiên trình duyệt.

### Dữ liệu thu được & Giới hạn chấp nhận
- **Dữ liệu thu được**:
  - Toàn bộ bài thảo luận Threads công khai theo từ khóa chiến dịch.
  - Video Instagram Reels theo hashtag ngành hàng.
  - Các chỉ số tương tác vĩ mô: Likes, Comments Count, Public Plays, Timestamp.
- **Giới hạn chấp nhận**:
  - Không đọc được số liệu phân tích nội bộ (Internal Impressions, Retention Rate của tài khoản đối thủ).
  - *Kết luận*: **Đầy đủ 100% dữ liệu cần thiết** để thuật toán `StrategicMarketReasoner` của fn-ignis tính toán **Opportunity Index** (+100 đến -100) và phát hiện phân khúc `HIGH_DEMAND_LOW_SUPPLY`.

---

## 3. Tier 2: Tích hợp Sâu Meta Graph API cho Chuyên gia (Deep API & Enterprise)

Dành cho người dùng muốn vận hành hệ thống bền vững, tự động 24/7 với độ tin cậy tuyệt đối qua API chính thức của Meta.

### Bước 1: Đăng ký ứng dụng trên Meta Developer Portal
1. Truy cập [Meta for Developers](https://developers.facebook.com/) và đăng nhập tài khoản Meta của bạn.
2. Chọn **My Apps** $\rightarrow$ **Create App**.
3. Tại màn hình chọn Use Case:
   - Với **Threads**: Chọn **Other** $\rightarrow$ Chọn loại **Business** (hoặc chọn trực tiếp use case **Threads** nếu hiển thị).
   - Với **Instagram Reels**: Chọn **Instagram Graph API**.
4. Đặt tên ứng dụng (ví dụ: `fn-ignis-intelligence`) và điền email quản trị.

### Bước 2: Phân quyền Scopes & Cấu hình Redirect URI

#### Với Threads Graph API:
- Vào mục **Threads** $\rightarrow$ **Settings**:
  - Thêm **Redirect Callback URL**: `http://localhost:8000/oauth/callback` (hoặc URL local của bạn).
- Vào mục **App Roles** $\rightarrow$ **Roles**:
  - Thêm tài khoản Threads cá nhân của bạn vào danh sách **Testers** để có thể cấp quyền ngay lập tức mà không cần chờ Meta xét duyệt công khai.
- Các Scopes cần thiết:
  - `threads_basic` (Bắt buộc — Đọc thông tin profile và danh sách bài viết).
  - `threads_manage_insights` (Khuyến nghị — Đọc lượt views, impressions, reposts).
  - `threads_keyword_search` (Nâng cao — Cần Meta App Review để tìm kiếm mở rộng toàn cầu).

#### Với Instagram Graph API (Reels):
- Yêu cầu: Tài khoản Instagram phải được chuyển đổi thành **Instagram Creator hoặc Business**, liên kết với một **Facebook Page**.
- Scopes cần thiết:
  - `instagram_basic`
  - `instagram_manage_insights`

### Bước 3: Thiết lập Credentials vào file `.env`
Mở file `.env` tại thư mục gốc của `fn-ignis` và cấu hình:

```bash
# ------------------------------------------------------------------------------
# META THREADS GRAPH API (OAUTH 2.0)
# ------------------------------------------------------------------------------
THREADS_APP_ID=your_threads_app_id_here
THREADS_APP_SECRET=your_threads_app_secret_here
THREADS_REDIRECT_URI=http://localhost:8000/oauth/callback
THREADS_API_VERSION=v1.0

# ------------------------------------------------------------------------------
# INSTAGRAM GRAPH API (REELS)
# ------------------------------------------------------------------------------
INSTAGRAM_APP_ID=your_instagram_app_id_here
INSTAGRAM_APP_SECRET=your_instagram_app_secret_here
INSTAGRAM_REDIRECT_URI=http://localhost:8000/oauth/callback
INSTAGRAM_USER_ID=your_instagram_business_account_id
```

### Bước 4: Thực thi OAuth 2.0 Flow qua FastMCP Tools
Hệ thống `fn-ignis` đã tích hợp sẵn công cụ tự động hóa toàn bộ quá trình nâng cấp token:

1. **Tạo Authorization URL**:
   Người dùng truy cập đường dẫn cấp quyền do app sinh ra:
   ```
   https://threads.net/oauth/authorize?client_id={THREADS_APP_ID}&redirect_uri={REDIRECT_URI}&scope=threads_basic,threads_manage_insights&response_type=code
   ```
2. **Lấy Authorization Code**:
   Sau khi bấm chấp thuận, trình duyệt chuyển hướng về URL:
   `http://localhost:8000/oauth/callback?code=AQD...#_`
   Copy toàn bộ chuỗi mã `code` này (phần `#_` ở đuôi sẽ được hệ thống tự động loại bỏ).
3. **Kích hoạt công cụ FastMCP**:
   Gửi lệnh cho AI Agent:
   ```python
   authenticate_threads(auth_code="AQD...")
   authenticate_instagram(auth_code="IGQW...")
   ```
4. **Hệ thống tự động thực hiện 3 bước ngầm**:
   - Đổi `auth_code` lấy **Short-Lived Token** (hạn 1 giờ).
   - Ngay lập tức gọi Meta Graph API nâng cấp lên **Long-Lived User Token (hạn 60 ngày)**.
   - Mã hóa AES-256 toàn bộ token và client secret trước khi lưu vào `platform_credentials`.

---

## 4. 🤖 Kịch bản Tự Động Hóa Dành Riêng Cho AI Agent (Agent Runbook)

> **Dành cho Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes hoặc Pi Agent:**  
> Khi người dùng yêu cầu: *"Hãy giúp tôi cài đặt kết nối Meta Threads / Instagram cho fn-ignis"*, trước hết hãy hỏi họ có tài khoản Meta Developer hay không.
>
> - **Không có (đa số người dùng)** → chạy ngay Tier 1, chỉ một lệnh duy nhất, không cần `.env`, không cần App ID:
>   ```python
>   authenticate_threads()      # hoặc authenticate_instagram()
>   ```
>   Sau đó xác nhận bằng `get_threads_auth_status()` / `get_instagram_auth_status()` và kiểm tra trường `browser_session.status == "ACTIVE"`.
> - **Có, và muốn vận hành 24/7 ổn định** → thực hiện tuần tự quy trình Tier 2 dưới đây:

```
[Agent Step 1: Kiểm tra Khoá Mã Hóa]
  │
  ├── Đọc file .env kiểm tra IGNIS_ENCRYPTION_KEY.
  └── Nếu chưa có: Thực thi lệnh sinh khoá Fernet AES-256 và tự ghi vào .env:
      python -c "from ignis.infrastructure.auth.crypto import generate_new_key; print(generate_new_key())"
  │
[Agent Step 2: Thu Thập Thông Tin Ứng Dụng]
  │
  ├── Hỏi người dùng: "Vui lòng cung cấp THREADS_APP_ID và THREADS_APP_SECRET từ Meta Developer Portal của bạn."
  └── Ghi các giá trị này vào file .env một cách an toàn.
  │
[Agent Step 3: Sinh Đường Dẫn Cấp Quyền & Hướng Dẫn]
  │
  ├── Sinh đường link:
  │   https://threads.net/oauth/authorize?client_id={APP_ID}&redirect_uri={REDIRECT_URI}&scope=threads_basic,threads_manage_insights&response_type=code
  └── Báo người dùng: "Bạn hãy click vào link trên, bấm Cho phép, sau đó copy toàn bộ URL trình duyệt chuyển hướng dán lại vào đây."
  │
[Agent Step 4: Trích Xuất Code & Kích Hoạt FastMCP Tool]
  │
  ├── Tự động trích xuất tham số ?code=... từ chuỗi người dùng gửi (cắt bỏ phần đuôi '#_').
  └── Gọi FastMCP Tool:
      authenticate_threads(auth_code="...")
  │
[Agent Step 5: Chạy Kiểm Thử Chẩn Đoán Xác Nhận]
  │
  ├── Gọi tool: get_threads_auth_status()
  │   └── Xác nhận trạng thái: ACTIVE, Days remaining ~ 60 ngày.
  └── Gọi tool: verify_connectors_health()
      └── Xác nhận Threads connector báo trạng thái HEALTHY.
```

---

## 5. Kiến trúc Bảo mật Credentials & Vòng đời Token

1. **Mã Hóa At-Rest Tuyệt Đối**:
   - `CryptoService` áp dụng thuật toán chuẩn `Fernet` (kết hợp AES-128-CBC với HMAC-SHA256 để xác thực tính toàn vẹn dữ liệu).
   - Mã khóa được lưu trữ độc lập qua biến môi trường `IGNIS_ENCRYPTION_KEY`.
2. **Cơ Chế Fail-Fast Phòng Vệ**:
   - Nếu `IGNIS_ENCRYPTION_KEY` bị thiếu trong production, hệ thống sẽ **lập tức từ chối ghi** (`EncryptionKeyMissingException`) thay vì âm thầm sử dụng ephemeral key tạm thời trong RAM (vốn sẽ làm mất khả năng giải mã token sau khi khởi động lại server).
3. **Key Versioning Sẵn Sàng (`v1`)**:
   - Mọi bản ghi mã hóa đều mang metadata `key_version: "v1"`. Khi cần xoay vòng khóa bảo mật (Key Rotation), hệ thống có khả năng nhận biết bản ghi cũ và tự động giải mã nâng cấp sang key mới.
4. **Cơ Chế Tự Động Làm Mới (Proactive Refresh Loop)**:
   - Trước khi hết hạn 60 ngày, `ThreadsAuthManager` định kỳ kiểm tra. Nếu thời gian còn lại $\le 10$ ngày (`REFRESH_THRESHOLD_DAYS`), hệ thống tự động gọi endpoint `/refresh_access_token` để gia hạn thêm 60 ngày mà không làm gián đoạn bất kỳ chiến dịch nghiên cứu nào.

---

## 6. Xử lý Sự cố & Câu hỏi Thường gặp (FAQ)

### Q1: Tại sao `is_healthy()` báo Threads là `UNHEALTHY`?
**Trả lời**: `fn-ignis` tuân thủ nguyên tắc báo cáo trung thực (Honest Observability). Nếu plugin được cấu hình chạy OAuth nhưng chưa hoàn tất đăng nhập hoặc token đã hết hạn, hệ thống sẽ báo `UNHEALTHY` để nhà chiến lược biết và không đưa ra kết luận thị trường thiếu căn cứ.

### Q2: Gặp lỗi `ConnectorAuthenticationException: 401/403 Invalid OAuth access token`?
**Khắc phục**:
1. Kiểm tra lại xem tài khoản thử nghiệm của bạn đã được add vào **App Roles $\rightarrow$ Testers** trên Meta Developer Portal chưa.
2. Gọi tool `clear_threads_auth()` để xóa token cũ, sau đó thực hiện lại luồng `authenticate_threads()`.

### Q3: Bị lỗi `Rate Limited (HTTP 429)` từ Meta Graph API?
**Khắc phục**:
Meta Graph API giới hạn 200 lượt gọi/người dùng/giờ. Hệ thống `fn-ignis` đã tích hợp sẵn:
- **Insights TTL Cache (2 giờ)**: Chỉ số của từng bài viết (`views, likes, replies, reposts, quotes` với Threads; `plays, reach, total_interactions` với Reels) được lưu trong bộ nhớ với TTL 2 giờ. Worker daemon quét lại cùng một cửa sổ dữ liệu sau mỗi 15 phút sẽ đọc từ cache thay vì phát lại N+1 request, triệt tiêu nguồn tiêu thụ quota lớn nhất. Điều chỉnh qua biến môi trường `META_INSIGHTS_CACHE_TTL_SECONDS`.
- **Semaphore(5)**: Giới hạn tối đa 5 requests insights đồng thời.
- **Circuit Breaker**: Sau 3 lần chạm ngưỡng 429, Circuit Breaker sẽ tự động chuyển sang trạng thái `OPEN` để cách ly plugin trong 300 giây, bảo vệ tài khoản của bạn không bị Meta khóa tạm thời.
