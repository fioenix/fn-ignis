# 📋 FN-IGNIS BACKLOG & SYSTEM STATUS

> **Cập nhật lần cuối:** 09/09/2026  
> **Phiên bản:** `v0.3.5`  
> **Kiến trúc:** Clean Architecture + Dual-Backend (Postgres TimescaleDB & Zero-Docker SQLite) + FastMCP Server (39 Handlers & Tools)  
> **Trạng thái Tests:** 350/350 unit tests PASSED (100%) | Ruff Linter Clean

---

## 0. Chất Lượng Corpus (Epic Đang Mở)

Đo trực tiếp trên Postgres ngày 09/09/2026. Chi tiết trong `.handoff/2026-09-09-corpus-audit.handoff.md`.

Điểm cross-platform momentum dành 40/100 điểm cho số platform cùng nói về một chủ đề, nhưng
**96,6% cluster (995/1030) chỉ có tín hiệu từ một platform**, nên phần 40 điểm đó gần như không
bao giờ được kích hoạt. Nguyên nhân không nằm ở thuật toán clustering: mỗi connector kéo feed riêng
nên các platform không bao giờ nói về cùng chủ đề. Chỉ 2 trong 156 keyword Google Trends có
video YouTube chứa nguyên văn keyword đó ở bất kỳ đâu trong corpus.

### Đã xử lý
- [x] **Ingress ghép theo chủ đề:** connector tự khai báo feed của nó có sinh ra chủ đề hay chỉ
  xếp hạng độ phổ biến. `fetch_from_all` chạy hai tầng: kéo các discovery surface, rồi probe
  phần còn lại bằng chính những chủ đề đó cộng seed từ `market_lexicons`.
- [x] **Bỏ `chart=mostPopular` khỏi pass công khai:** feed này chiếm 94,8% corpus và toàn bộ là
  nội dung giải trí quốc gia mà không platform nào khác chứng thực được.
- [x] **Quota budget cho YouTube:** `search.list` tốn 100 unit trên hạn mức 10.000/ngày, nên
  fan-out bị chặn ở 10 keyword và cadence mặc định chuyển sang 8640s. Scheduler cảnh báo nếu
  interval đang dùng sẽ đốt hết quota trước khi hết ngày.
- [x] **`topic_clusters.topic_label`:** cluster được đặt tên theo chủ đề thay vì nguyên văn một
  post. `canonical_name` giữ vai trò identity key nên 1.030 cluster hiện có không bị đổi ID.
- [x] **Cổng ingress chỉ còn chặn theo chữ viết:** một pass VN từng lưu tiêu đề tiếng Ukraina
  và tiếng Ả Rập, vì `q=` là từ khoá tìm kiếm chứ không phải region filter.
  `detector.uses_regional_script()` chặn đúng một thứ: chữ viết mà vùng đó không dùng. Tỷ lệ loại
  giảm từ 65% xuống **1,7%** (1/60 trên pass thật).
- [x] **Ngừng ghi API key vào log:** httpx log toàn bộ URL ở mức INFO và YouTube xác thực bằng
  key trong query string.
- [x] **Cluster theo keyword đã probe, không chỉ theo cách diễn đạt tiêu đề:** mọi connector đều
  đã ghi lại query trả về tín hiệu, nhưng dưới ba tên metadata khác nhau và không chỗ nào đọc.
  Đo trên 400 tín hiệu mới nhất có provenance: **50,0% cluster đa platform (19/38)**, so với 8,0%
  và 3,4% ban đầu. 18 cluster đạt mức SURGING.

### Còn lại
- [x] **Đã xoá tín hiệu cũ viết bằng chữ viết ngoại ngữ:** 245 row (1,6%), gồm Hangul 162,
  CJK 49, Cyrillic 24, Katakana/Hiragana 15, Arabic 8, còn lại Thai/Devanagari/Lao/Myanmar.
  Corpus 15.800 xuống 15.555. Đã backup toàn bộ cột trước khi xoá.
- [x] **Token số không còn headline nhãn:** nhánh fallback từng cho ra "vietinbank · 100 · chi".
  Chữ số vẫn nằm trong token để clustering phân biệt "iPhone 17" với "iPhone 16", chỉ bị cấm làm
  từ đứng đầu nhãn. Số nằm giữa một cụm mà cluster thật sự chia sẻ thì vẫn giữ ("Top 10 salon").
- [x] **Classifier yêu cầu bằng chứng có đối chứng:** một keyword là đủ chỉ khi nó **không thể
  trùng ngẫu nhiên**, tức là cụm ghép. Token đơn cần hit thứ hai. Lý do: đo trên corpus thật,
  179/342 cluster được phân loại chỉ dựa vào một token đơn, và mẫu cho thấy phần lớn là trùng
  ngẫu nhiên. Nặng nhất là `ai` — nó vừa là acronym tiếng Anh vừa là đại từ nghi vấn tiếng Việt,
  và một mình nó đưa cluster 278 signal "JISOO - CLICK (Official MV)" vào `tech`.
  Sau khi áp: **0** cluster còn được phân loại bằng một token đơn. JISOO và Alcaraz về
  `unclassified`. Vertical thật 68 → **172** (thay vì 348 lúc còn false positive).
  **Đánh đổi:** recall giảm từ 348 xuống 172, đổi lấy precision. Với dossier ra quyết định thì
  category sai tệ hơn category trống.
- [x] **Cân theo số signal thật sự chứa hit:** trước đây token được gộp chung cho cả cluster nên
  một signal thiểu số nói thay cho toàn bộ. Giờ khớp theo từng signal, và một vertical phải được
  ít nhất **1/5 số signal** của cluster làm chứng.
  Ngưỡng 1/5 lấy từ dữ liệu, không phải chọn bừa: trong các cluster chỉ có một signal khớp, mọi
  cluster từ 5 signal trở xuống đều là phán đoán hợp lý, còn hai cluster lớn hơn thì sai — bảng
  đấu esports vào `fashion` với 1/15, post ly hôn vào `beauty` với 1/9. Sau khi áp, đúng 2 row
  đổi, cả hai ca đó về `unclassified`, và các cluster đúng đều giữ nguyên.
- [ ] **`son` và `kem` trong taxonomy `beauty` mơ hồ khi mất dấu** (sơn/son, kém/kem). Luật đối
  chứng đã vô hiệu hoá tác hại của chúng, nên không còn gấp. Nợ có sẵn từ seed gốc.
- [ ] **Taxonomy chưa phủ các vertical ngoài thị trường:** tin tức, thể thao, người nổi tiếng,
  sức khoẻ/wellness vẫn rơi vào `unclassified`. Đây là **câu hỏi phạm vi sản phẩm**, không phải
  bug: một harness về cơ hội thị trường có nên theo dõi bóng đá không? Chờ Fio quyết.
- [ ] **Chưa cluster nào đạt BREAKOUT (>= 80):** cần 4-5 platform cùng nói về một chủ đề, hiện
  tối đa là 3.
- [ ] **Discovery source chưa đúng mục đích sản phẩm:** feed trending VN của Google Trends là tin
  tức tổng hợp (bóng đá, thời sự), nên ghép chủ đề theo nó cho ra corpus tin tức chứ không phải
  corpus cơ hội thị trường. Phần liên quan đến thị trường hiện chỉ đến từ seed lexicon.
- [ ] **Chất lượng nhãn trên corpus thật:** nhiều nhãn rút về dạng mảnh có dấu ba chấm
  ("… em theo …"). Thuật toán đúng nhưng đầu vào là câu nói thường ngày, không phải cụm chủ đề.
- [x] **Phân loại category:** matcher **không sai** — với taxonomy đã seed, nó phân loại đúng
  6/6 vertical thị trường và đúng khi trả `unclassified` cho bóng đá hay giá vàng. Vấn đề là
  vocabulary: 6 vertical chỉ có 44 keyword cho cả nền kinh tế, nên "chatgpt va gpt-6" và
  "meo phat am tieng anh" đều rớt dù nằm trong vertical đang theo dõi. Đã mở lên **128 keyword**
  trong `sql/003` và `sql/010`, kèm test chặn hai file lệch nhau.
  Đo lại trên 1.087 cluster: cluster thuộc vertical thật đi từ **68 lên 348**, `unclassified`
  (gộp cả `general` cũ) từ 1.018 xuống 739. Đã ghi vào Postgres.
- [x] **Không dùng token tiếng Việt ngắn làm keyword taxonomy:** `_fold_accents` xoá dấu nên
  "vang" phủ cả nghĩa vàng và nghĩa âm vang, "toc" phủ cả tóc và tốc. Lần mở rộng đầu tiên thêm
  đúng loại token đó và gây false positive thật: playlist bolero vào `finance`, bảng đấu esports
  vào `beauty`. Đã bỏ, chỉ giữ cụm ghép và từ vay mượn không mơ hồ. Có test chặn.
- [x] **Bug lộ ra khi đo lại:** 3 cluster từng bị gán category là số view (`27.6k`, `6.4k`, `28k`).
  Parser Creative Center đọc bảng theo vị trí nên hàng thiếu cột category lấy luôn số posts/views.
  Đã vá ở gốc, và thêm một tầng phòng vệ ở `_classify_category` vì plugin bên thứ ba cũng dùng
  cùng port đó.
- [x] **Đã quyết (09/09/2026): độ liên quan xét ở hạ nguồn, không xét ở ingress.** Cổng cũ xét
  độ liên quan theo `market_lexicons` nên loại mọi chủ đề chưa được seed, tức loại đúng thứ mà
  radar tồn tại để tìm. Trên corpus thật nó loại 67,8%, trong đó có cả
  "Khoa hoc AI cho nguoi moi bat dau". `QualityEvaluator` đã giữ sẵn vocabulary đó và đã chạy
  trên analysis path, nên phần xét độ liên quan chuyển hẳn về đó.
  **Giá phải trả, đã chấp nhận:** corpus lưu thêm nội dung nội địa lệch chủ đề, và Quality Gate
  ở hạ nguồn phải gánh thật. Cần theo dõi xem nó gánh được không.
- [x] **Đã xong (09/09/2026): năm chỗ từ vựng hardcode đã chuyển vào `market_lexicons`.**
  `AMBIGUOUS_UNIGRAMS`, `DEFAULT_GEO_PROBES`, danh sách từ khoá ý định của Google Trends, và
  hai bản sao khác nhau của danh sách dấu hiệu câu hỏi (một trong `autonomous_discovery`, một
  trong `extract_customer_pain_points`, bản sau là tập lớn hơn). Seed ở
  `sql/012_vocabulary_from_constants.sql`, đọc qua `vocabulary_loader`, và bốn entry tương ứng
  đã bị xoá khỏi allowlist của `test_repo_conventions.py` nên gate giờ chặn thật.
- [x] **Đã xong (09/09/2026): `tiktok_plugin.py` cũng đã sạch.** `NOTIFICATION_BLACKLIST` (13
  chuỗi UI thông báo của TikTok) và một mẫu probe intent viết cứng bằng tiếng Việt đã chuyển vào
  `sql/013_tiktok_ui_noise.sql`. Bộ lọc thông báo giờ **fail closed**: không có từ vựng thì loại
  hết card thay vì để trôi, vì nó là thứ bảo đảm plugin không bao giờ lưu inbox của người dùng.
  Mẫu probe thì bỏ qua geo nào chưa có phrasing, thay vì probe thị trường US bằng tiếng Việt.
- [x] **Đã xong (09/09/2026): `language_detector.py` đã chuyển hai bộ từ vựng.**
  `FOREIGN_STOPWORD_PHRASES` (22 cụm Pháp, Bồ, Indonesia) và `PORTUGUESE_DISTINCTIVE_WORDS`
  (38 từ) vào `sql/014_language_detection_vocabulary.sql`. Một detector duy nhất được inject
  vào `QualityEvaluator` và `StrategicMarketReasoner` thay vì mỗi engine tự dựng một cái.
  Character class vẫn nằm trong code vì ở đó ký tự chính là thuật toán.
  Còn `VI_CORE_WORDS` và `TECH_LOAN_WORDS` chưa chuyển, nhưng giờ **được ghi tên** trong
  `KNOWN_VOCABULARY_CONSTANTS` thay vì vô hình với gate.
- [x] **Đã xong (10/09/2026): tách `captured_at` và `published_at` thành hai cột.**
  Trước đó ba trong mười lăm chỗ gán `captured_at` bằng thời điểm nội dung được đăng, và ba chỗ
  đó thuộc hai connector chiếm phần lớn corpus, nên mọi truy vấn theo timeframe đang trộn hai
  đồng hồ.

  `captured_at` giờ luôn là thời điểm thu thập và là đồng hồ duy nhất mà timeframe query dùng.
  `published_at` là thời điểm nền tảng báo nội dung được đăng, `NULL` ở nơi nền tảng không báo.

  Backfill trong `sql/015` chính xác, không suy đoán: 14.813 dòng youtube lấy từ
  `metadata->>'published_at'` và khớp 100% với giá trị của nền tảng, cộng 486 threads và 29
  reels cùng nguồn đó, cộng 72 dòng Google Trends RSS lấy từ chính `captured_at` vì ở đó nó là
  pubDate. 371 dòng còn lại để `NULL`: 259 tiktok và 112 dòng probe của Google đều không có
  khái niệm ngày đăng. Tổng 15.400/15.771 dòng có `published_at`.

  `QualityEvaluator` giờ đọc thẳng field cho điểm freshness, vì độ tươi là thuộc tính của nội
  dung. Guard chống tái phát là một test đọc AST của mọi connector: đặt lại lỗi cũ thì nó fail
  đúng dòng, tao đã thử.

  **Chỗ không lấy lại được:** với các dòng ghi trước migration bởi ba code path đó, `captured_at`
  vẫn là ngày đăng, và thời điểm thu thập thật chưa từng được lưu. Tao để nguyên chứ không đóng
  một mốc thời gian bịa. Cửa sổ thời gian trên các dòng đó còn xấp xỉ cho tới khi chúng rơi ra
  khỏi cửa sổ.

- [x] **Đã xong (10/09/2026): bỏ 5 từ khoá hardcode trong đường discovery.** Macro scan rỗng
  giờ rơi về seed trong `market_lexicons`, tức từ vựng của người vận hành, và log warning nói rõ
  chu kỳ này phản ánh vốn từ đã seed chứ không phải thứ nền tảng tự nổi lên. Nếu lexicon cũng
  rỗng thì trả `status: NO_SCOPE` kèm hướng dẫn, **không bịa từ khoá**. Kết quả luôn mang
  `keyword_source` là `creative_center` / `market_lexicon` / `none` nên không còn im lặng.
- [x] **Đã xong (10/09/2026): nối `timeframe` vào `trigger_ingress_refresh`.** Tool nhận
  `timeframe` và truyền xuống `fetch_from_all`, từ đó tới `plugin.fetch_signals` và
  `search_signals`. Kiểm bằng spy: `30d`, `7d`, `12m` đều tới đúng connector.

  Việc nối này mở ra một lỗ phải bịt luôn: `Timeframe._missing_` dựng member từ **bất kỳ** chuỗi,
  nên `'bogus'` thành `Timeframe.BOGUS` rồi bị map ngầm về mặc định ở hạ nguồn. Giờ trả
  `INVALID_TIMEFRAME` kèm danh sách giá trị hợp lệ. Rỗng vẫn là mặc định 24h, giống `resolve_geo`.
- [x] **Đã sửa (10/09/2026): seed keyword bị nhiễm từ vựng máy móc.** Đây là regression tao gây
  ra ngày 09/09: `NON_TOPIC_LEXICON_DOMAINS` trong `ingest_trends.py` chỉ loại 2 domain cũ, nên 8
  domain máy móc thêm hôm đó chảy thẳng vào seed. Đo trên Postgres thật: **cả 10 seed** đều là hư
  từ tiếng Việt, vì `ambiguous_unigrams` sắp trước theo bảng chữ cái và chiếm trọn budget.

  Nghĩa là lượt 6 connector tao báo hôm qua đã probe các nền tảng bằng hư từ. Phần signal từ
  stage 1 vẫn thật, nhưng phần keyword fan-out thì gần như vô nghĩa.

  Danh sách domain máy móc giờ chỉ còn một bản trong `vocabulary_loader`, và có test chặn bản
  thứ hai xuất hiện lại. Sau khi sửa, 10 seed là chủ đề thật.

- [ ] **`self_healing_sniffer` ghi `runtime_configs` 97 lần trong một lượt.** Đo trên lượt
  09/09/2026: 85 lần cho `threads_doc_id_trending_topics`, 7 cho `search_posts`, 5 cho
  `search_suggestions`, dồn trong khoảng 40 giây. Ghi cùng một giá trị lặp lại vào Postgres.
  Cần dedupe: chỉ ghi khi giá trị thay đổi thật.
- [ ] **CHẶN VẬN HÀNH: key YouTube trong `.env` là key cũ đã bị revoke.** Google trả về
  `400 badRequest · "API key expired. Please renew the API key."` Key mới đã tạo nhưng chưa vào
  `.env`. Hệ quả: YouTube ingress chết hoàn toàn, và YouTube là 1 trong 2 connector duy nhất
  worker chạy được, đồng thời chiếm 94% corpus 30 ngày. Đo ngày 09/09/2026.
- [ ] **`is_healthy()` của hai connector TikTok là `return True` cứng.** `TikTokPlugin` và
  `TikTokCreativeCenterPlugin` không kiểm gì cả, nên `verify_connectors_health` báo `HEALTHY`
  cho chúng trong mọi hoàn cảnh, kể cả khi Playwright không chạy được hay session đã hết.
  Google Trends, Threads, Reels, YouTube đều có probe thật. Bốn trên sáu là thật, hai là hằng số.
- [ ] **Taxonomy không phủ được câu hỏi lắng nghe mở.** Một lượt Google Trends VN thật ngày
  09/09 trả 10 signal, cluster ra 10 chủ đề, nhưng 9/10 là `unclassified`: "áp thấp nhiệt đới",
  "hồ ngọc hà", "match day 2026", "đỗ xe". Taxonomy hình dung theo vertical thị trường, còn
  Google Trends hằng ngày là tin tức và giải trí. Cần quyết: mở rộng taxonomy sang các nhóm
  phi thị trường, hay chấp nhận `unclassified` là câu trả lời hợp lệ và hiển thị nó tử tế.
- [ ] **Đợi quyết: `_is_private_or_notification` khớp theo substring thô.** `"live "` khớp trong
  `"olive oil review"`, nên một video thật bị loại như thông báo. Lỗi này có từ trước, không phải
  do lần chuyển từ vựng. Sửa bằng cách khớp theo biên từ là đổi hành vi, nên tao chưa làm.


---

## 🚀 1. Hiện Trạng Hệ Thống Đã Hoàn Thành (Current Accomplishments)

### A. Hạ Tầng & Cơ Sở Dữ Liệu
- [x] **Supabase Cloud Pooler (Region ap-southeast-1):** Kết nối qua pooler endpoint `aws-0-ap-southeast-1.pooler.supabase.com:5432` với `psycopg_pool.AsyncConnectionPool`.
- [x] **Schema Bền Vững:** `research_missions`, `topic_clusters`, `trend_signals`, `system_audit_logs`, `platform_credentials`.
- [x] **Lightweight Worker Container:** Dockerfile tối ưu (~90MB, multi-stage uv build) chạy nền 24/7 trên OrbStack.
- [x] **Credentials Hardening:** `CryptoService` áp dụng Fernet AES-128-CBC + HMAC-SHA256, có fail-fast (`assert_persistent_key`) và hỗ trợ `key_version` ("v1") sẵn sàng cho key rotation.

### B. Ingress Connectors & Authentication
- [x] **YouTube Data API v3:** 
  - Batch call `videos.list?part=snippet,statistics` lấy views, likes, comments thật.
  - Tốc độ tăng trưởng thật: `velocity = views / hours_since_published`.
  - Bộ lọc thời gian: Áp dụng `publishedAfter` (RFC 3339) theo timeframe yêu cầu.
  - Bản địa hóa: Bộ lọc `relevanceLanguage` và `regionCode`.
- [x] **Google Trends RSS & Suggest API:** 
  - Dynamic interest score & traffic volume thật, lấy cụm từ khóa tìm kiếm liên quan theo thời gian thực.
- [x] **TikTok Ingress & Creative Center:**
  - `TikTokAuthManager` với khả năng bắt tự động `storageState` (cookies, tokens) mà end-user không cần DevTools.
  - Hỗ trợ cào Trending và Tìm kiếm theo từ khóa (`search_signals`) bóc tách Play Count, Digg Count, Comment Count, Share Count thật.
  - Tích hợp TikTok Creative Center Macro Trends (`get_tiktok_creative_center_trends`).
- [x] **Meta Threads Graph API (OAuth 2.0 - Epic 1 Hoàn Tất trong v0.2.0):**
  - Tích hợp Threads Graph API OAuth với luồng đổi Long-Lived Token (60 ngày).
  - Tự động refresh token khi còn $\le 10$ ngày mà không làm gián đoạn hệ thống.
  - FastMCP Tools: `authenticate_threads`, `get_threads_auth_status`, `clear_threads_auth`.
- [x] **Instagram Reels Ingress (Graph API - Epic 1 Hoàn Tất trong v0.2.0):**
  - `ReelsPlugin` hỗ trợ bóc tách qua `ig_hashtag_search` $\rightarrow$ `top_media`, lọc `media_product_type == "REELS"`.
  - Bóc tách play_count, like_count, comment_count, caption, published_at.
- [x] **Error Isolation & Observability:** Circuit Breaker độc lập cho từng kênh kết nối, phân loại lỗi 401/403/429 chuẩn mực.

### C. Agent Harness & Multi-Region Quality Evaluation
- [x] **Autonomous Refinement Loop (`AutonomousRefinementOrchestrator`):** Tự động phát hiện dữ liệu mỏng hoặc độ tin cậy thấp để cào bổ sung đợt 2 (Pass 2) theo từ khóa phụ.
- [x] **ILanguageDetector & Subtractive Filtering:** Nhận diện ngôn ngữ chuẩn xác không dùng rubber-stamp:
  - Hỗ trợ 6 vùng: `VN`, `US`, `JP`, `KR`, `TH`, `BR`.
  - Cơ chế Subtractive Filtering: Chấp nhận 100% tiêu đề công nghệ chứa tên thương hiệu (`n8n Zapier Make Comparison`, `Kubernetes Helm Terraform DevOps`), từ chối triệt để ký tự ngoại ngữ, CJK không có Kana ở Nhật, tiếng Việt ở Brazil, và chuỗi rác vô nghĩa.
  - Dynamic Lexicon whitelist (`register_domain_lexicon`) và noise blacklist (`register_noise_blacklist`).
- [x] **White Space Discovery (`StrategicMarketReasoner`):**
  - So sánh Nhu cầu tìm kiếm vs Nguồn cung video/thảo luận.
  - Bóc tách các phân khúc: `HIGH_DEMAND_LOW_SUPPLY`, `ENTERPRISE_GAP`, `SATURATED_SEGMENT`.
  - Đánh giá giai đoạn xu hướng (Trend Maturity Stage: `EMERGING`, `HYPING`, `MATURE`).
- [x] **Deterministic Artifact Builder:** Single-file HTML Report (Tailwind CSS) trực quan hóa Scorecard, Ma trận Cung-Cầu và Bằng chứng đa kênh.

### D. Tối Ưu Hóa Giao Tiếp & FastMCP Catalog
- [x] **Danh mục 31 FastMCP Tools:** Hoàn thiện và đồng bộ đối xứng giữa `server.py`, `openclaw.json`, `hermes_manifest.json`, `.hermes/tools.json` và `setup_bundle.py`.
- [x] **Cross-Agent Session Tracing:** Lưu trữ trường `agent` và `session_id`. Tool `get_current_session_mission` tự động khôi phục ngữ cảnh làm việc mà không cần nhập lại ID.
- [x] **Tài liệu Tích hợp Meta Dedicated:** [docs/META_INTEGRATION_GUIDE.md](docs/META_INTEGRATION_GUIDE.md) định nghĩa toàn diện mô hình Dual-UX và kịch bản tự động hóa cho AI Agent.

---

## 📌 2. Danh Mục Backlog Cho Các Session Tiếp Theo (Upcoming Roadmap)

### ✅ Epic 1.5: Dual-UX Meta Ingress & Instagram Parity (Đã hoàn thành)
*Mục tiêu: Đạt tỷ lệ kích hoạt 100% cho cả người dùng phổ thông (Non-tech) lẫn chuyên gia (Tech-heavy).*
- [x] **Tier 1 (Non-Tech) 1-Click Browser Session Capture:** Bổ sung luồng Playwright browser login cho Threads và Instagram tương tự `authenticate_tiktok()`, cho phép người dùng phổ thông đăng nhập bằng tài khoản cá nhân thông thường để quét dữ liệu công khai (public search, hashtags) mà không cần Meta Developer Portal.
- [x] **FastMCP Instagram Tools Parity:** Bổ sung 3 công cụ FastMCP:
  - `authenticate_instagram(auth_code, client_id, client_secret, redirect_uri)` — hợp nhất luôn cả luồng `browser_login` của Tier 1
  - `get_instagram_auth_status()`
  - `clear_instagram_auth()`
- [x] **Insights TTL Caching (2 giờ):** Caching in-memory cho post metrics của Threads/Reels để giải quyết triệt để bài toán N+1 request và bảo vệ hạn mức 200 reqs/user/hour của Meta Graph API.
- [x] **Registry Multi-Plugin Coexistence (Tech Debt):** Đảm bảo `TikTokPlugin` (Search Video Grid & Comments) và `TikTokCreativeCenterPlugin` (Macro Trends Radar) cùng tồn tại song song trong `ConnectorPluginRegistry` mà không bị ghi đè.

### 🎯 Epic 2: Data Provenance, Ingress Health Audit & Citation Attribution Engine (Sprint Ready)
*Mục tiêu: Xóa bỏ nhận định mơ hồ và ảo giác; minh bạch hóa nguồn gốc dữ liệu (Data Provenance) và phát hiện kênh ingress bị rỗng/lỗi.*
- [ ] **Channel Ingress & Health Summary Table:** Tổng hợp trạng thái (`HEALTHY`, `EMPTY_NO_DATA`, `AUTH_REQUIRED`, `RATE_LIMITED`) và số lượng tín hiệu của từng kênh kết nối (Google Trends, YouTube, TikTok Video Grid, TikTok Comments, Threads, Instagram Reels), đính kèm mẫu tín hiệu tiêu biểu.
- [ ] **Citation Attribution Engine:** Tự động gắn thẻ dẫn chứng cụ thể (`CitationEvidence`: platform, title, metrics, author, excerpt) vào từng `StrategicInsight`, `MarketOpportunity` và `ActionableTakeaway`.
- [ ] **HTML Dashboard Visualization:** Trực quan hóa Bảng Kiểm Toán Kênh Dữ Liệu (Ingress Audit Table) và các huy hiệu Citation Badges (Pill Badges) trong báo cáo HTML.
- [ ] **FastMCP & Agent Reporting Protocol:** Cập nhật payload `get_mission_analysis` và chuẩn hóa quy trình xuất báo cáo bắt buộc có bảng audit và inline citations theo [docs/DATA_PROVENANCE_AND_CITATION_SPEC.md](docs/DATA_PROVENANCE_AND_CITATION_SPEC.md).

### 🎯 Epic 3: Live Alerts & Notification Webhooks
*Mục tiêu: Đẩy thông báo chủ động cho người dùng khi xu hướng bùng nổ.*
- [ ] **Persisted Discovery State:** Lưu trữ `last_discovery_time` vào cơ sở dữ liệu thay vì biến in-memory, tránh tình trạng khởi động lại daemon worker gửi lại toàn bộ alert cũ.
- [ ] **Webhook Deliveries & Idempotency:** Thiết kế bảng `webhook_deliveries` với dedup key duy nhất (`topic_id` + `alert_type` + `date`) và pipeline retry/backoff.
- [ ] **Breakout Trend Webhook:** Tự động gửi cảnh báo qua Slack / Telegram / Discord khi một topic cluster đạt `cross_platform_score >= 80.0` (Momentum: BREAKOUT).
- [ ] **Weekly Executive Digest:** Tự động chạy báo cáo tổng kết xu hướng hàng tuần và xuất bản trang HTML tĩnh.

### 🎯 Epic 2: Multi-Language & Regional Expansion (SEA & Global)
*Mục tiêu: Mở rộng khả năng lắng nghe thị trường ngoài Việt Nam.*
- [ ] **Đa khu vực (Geo Expansion):** Mở rộng bộ phân tích cho các thị trường Đông Nam Á (`TH`, `ID`, `MY`, `SG`, `PH`) và Toàn cầu (`US`, `GLOBAL`).
- [ ] **Cross-Language Semantic Alignment:** Đối chiếu các chủ đề đang bùng nổ tại thị trường US/Trung Quốc với tốc độ du nhập về Việt Nam (Time-Lag Arbitrage).

### 🎯 Epic 4: Trend Velocity Forecasting (Dự Báo Tương Lai)
*Mục tiêu: Đo lường chu kỳ sống của xu hướng.*
- [ ] **Time-series Projection:** Sử dụng mô hình ARIMA / Exponential Smoothing trên chuỗi dữ liệu Google Trends để dự đoán thời điểm xu hướng chạm đỉnh (Peak Interest).
- [ ] **Saturation Index:** Tính toán ngưỡng bão hòa của thị trường dựa trên tốc độ ra mắt video mới của các nhà sáng tạo nội dung.

---

## 🛠️ 3. Hướng Dẫn Kích Hoạt Cho Session Mới

Khi mở session mới với bất kỳ Agent nào (Antigravity, Claude Code, Codex), chỉ cần truyền lệnh:

> *"Đọc file `BACKLOG.md` để nắm hiện trạng kiến trúc `fn-ignis` và bắt đầu triển khai [Tên tính năng trong Backlog]."*
