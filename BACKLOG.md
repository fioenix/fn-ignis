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
- [x] **BREAKOUT đã với tới được (cập nhật 10/09/2026):** 5 cluster đạt `cross_platform_score
  >= 80`, và lượt pass đủ 6 connector ngày 09/09 tạo ra 2 cluster trải 4 nền tảng. Trước đó
  tối đa là 3. Ghi chú cũ nói chưa cluster nào đạt đã sai từ khi ingress hai tầng chạy thật.
- [ ] **Discovery source chưa đúng mục đích sản phẩm:** feed trending VN của Google Trends là tin
  tức tổng hợp (bóng đá, thời sự), nên ghép chủ đề theo nó cho ra corpus tin tức chứ không phải
  corpus cơ hội thị trường. Phần liên quan đến thị trường hiện chỉ đến từ seed lexicon.
- [x] **Chất lượng nhãn trên corpus thật:** đã sửa 10/09/2026, xem mục nhãn chủ đề
  ở phần dưới. Ellipsis 24/40 xuống 0 trên chính 40 cluster đã lưu.
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

- [x] **Đã xong (10/09/2026): secret không còn rò ra log khi test fail.** pytest in `repr()` của
  mọi object nằm trong frame của assertion fail. Với field kiểu `str`, bất kỳ test nào chạm vào
  một hàm đang giữ tham chiếu `Settings` cũng đẩy nguyên password database, khoá Fernet và key
  YouTube vào log. Trên repo public thì đó là log GitHub Actions ai cũng đọc được.

  Không phải giả thiết: một test scheduler fail trong session 10/09 đã in password Supabase thật.

  Sáu setting mang credential chuyển sang `SecretStr` — `DATABASE_URL`, `YOUTUBE_API_KEY`,
  `IGNIS_ENCRYPTION_KEY`, `THREADS_APP_SECRET`, `INSTAGRAM_APP_SECRET` và
  `PLAYWRIGHT_PROXY_SERVER` (dạng tài liệu hoá của nó nhúng `user:pass` vào URI). Hai
  `*_APP_ID` giữ `str` vì OAuth client_id là public by design.

  11 điểm đọc trong `src/` đi qua `reveal_secret()`, kể cả các phép kiểm truthiness: chúng vẫn
  đúng trên `Secret.__bool__` hiện tại của pydantic, nhưng người đọc không thể biết điều đó khi
  thấy `if settings.YOUTUBE_API_KEY:`, và nếu pydantic đổi thì nhánh lật ngược trong im lặng.
  `verify_connectors_health` từng in nguyên URI proxy vào tool output; `_describe_proxy` giờ chỉ
  trả scheme + host + port, phần userinfo thay bằng marker.

  Có test walk `src/` bắt mọi lần đọc sáu biến này mà không qua helper, nên call site mới sẽ đỏ
  ngay thay vì phải nhớ quy tắc.

- [x] **Đã xong (10/09/2026): Codex TOML bị nhân bản section thay vì thay thế.**
  `register_mcp_to_codex_toml` sub bằng regex non-greedy dừng ở `\n[` đầu tiên — chính là
  sub-table `[mcp_servers.fn-ignis.env]` của nó. Nên nó chỉ thay header, bảng env cũ sống sót, và
  mỗi lần chạy lại thêm một bảng nữa. Đợt migration "bỏ secret ra khỏi MCP config" vì vậy **không
  dọn được** `~/.codex/config.toml`, dù báo `configured`: password Supabase, khoá Fernet và một
  key YouTube đã revoke vẫn nằm đó, cộng thêm duplicate table mà TOML chuẩn từ chối parse.

  Giờ split file theo table header, xoá cả section rồi mới ghi lại, nên idempotent bất kể đã tích
  bao nhiêu bản cũ. Giá trị đi qua escaper cho TOML basic string.

- [x] **Đã xong (10/09/2026): provisioner không còn báo rotate key mà nó chưa làm.**
  `ensure_environment_file` gate việc ghi bằng cách so chuỗi rejoin với text gốc. Hai chuỗi lệch
  nhau ở newline cuối file mà hầu hết editor để lại, nên một lượt chạy không sinh gì vẫn ghi lại
  file và báo `Updated existing .env with generated IGNIS_ENCRYPTION_KEY`. Đổi khoá đó là mọi
  credential đã mã hoá bằng khoá cũ thành rác, nên một thông báo nói nó đã xảy ra còn tệ hơn
  không thông báo. Đồng thời template cho máy cài mới ghi `SCHEDULER_INTERVAL_SECONDS=900` trong
  khi `ignis.config` và `env.example` đều nói 8640 — nhịp 15 phút đốt hết quota YouTube trong
  khoảng một tiếng.

- [x] **Đã xong (10/09/2026): `env.example` ghi đè chính nhịp an toàn quota của nó.**
  File mẫu đặt `SYNC_INTERVAL_MINUTES=60` ngay trên `SCHEDULER_INTERVAL_SECONDS=8640`. Giá trị
  lớn hơn 0 thắng field giây, nên ai copy file này thành `.env` — bước đầu tiên sau khi clone —
  đều chạy tick 60 phút, 24 lượt/ngày trên ngân sách vừa đủ 10 lượt, còn dòng ngay bên dưới thì
  trông vẫn đúng. Hai dòng riêng lẻ đều hợp lý; đọc cùng nhau mới sai, nên test mới cho cả hai
  giá trị chạy qua `resolve_ingress_interval()` rồi assert kết quả — kiểm *file copy ra schedule
  cái gì*, không kiểm file trông có đúng không.

  Cùng lúc xoá bốn default 900 chết trong `scheduler.py`: chúng không bao giờ fire vì mọi caller
  đều đọc từ `Settings`, nhưng 900 chính là con số đã trôi vào cả hai file cấu hình.

- [ ] **Quyết định 10/09/2026 — Fio chấp nhận rủi ro ba secret đã lọt vào transcript.**
  Password Supabase, `IGNIS_ENCRYPTION_KEY` và key YouTube xuất hiện dạng plaintext trong
  transcript phiên 10/09 khi grep `~/.codex/config.toml`. Tao đề nghị rotate cả ba; Fio quyết
  không rotate, lý do: hiện chỉ nội bộ dùng `ignis` và mức độ mật không đáng.

  Phạm vi quyết định này: chỉ các giá trị đã lọt vào transcript. Ba secret đó **không** nằm trong
  git history — đã quét toàn bộ `git rev-list --all`. Cần xem lại nếu có thêm người ngoài truy
  cập được `ignis`, hoặc nếu transcript được chia sẻ ra ngoài.

- [x] **Đã xong (10/09/2026): MCP config giữ đường dẫn tới `.env`, không giữ secret.**
  `build_mcp_entry` từng sao `DATABASE_URL`, `IGNIS_ENCRYPTION_KEY` và `YOUTUBE_API_KEY` vào
  **bốn** file: `.mcp.json`, config Claude Desktop, config Antigravity và TOML của Codex. Vừa để
  password database cùng khoá Fernet ở dạng plaintext bốn nơi, vừa tạo bốn nguồn sự thật.

  Hậu quả thật đã xảy ra: sau khi rotate key YouTube, `.env` và `.mcp.json` được cập nhật nhưng
  config Claude Desktop còn giữ key cũ. Vì `env` của host ghi đè file env, mọi lệnh gọi YouTube
  qua MCP thất bại với "API key expired", trong khi cùng đoạn code chạy từ shell lại thành công.
  Đó chính là chỗ tao báo "key expired" rồi ngay sau đó một lượt pass lấy được 95 signal.

  Giờ entry chỉ mang `IGNIS_ENV_FILE`, một đường dẫn tuyệt đối. Kiểm với `env -i`: chỉ một biến
  đó là server load đủ DSN, key YouTube và khoá Fernet.
- [x] **Đã sửa (10/09/2026): thứ tự đọc env file bị ngược.** `env_file=(_PROJECT_ENV, ".env")` —
  pydantic-settings cho file **cuối** quyền cao nhất, nên một `.env` lạ nằm ở thư mục mà host
  tình cờ khởi động server sẽ ghi đè `.env` của project. Tao dựng decoy để chứng minh: thứ tự cũ
  cho decoy thắng, thứ tự mới cho project thắng. Có test giữ đúng thứ tự vì lỗi này im lặng, chỉ
  sai giá trị chứ không báo gì.
- [ ] **Còn lại của mày: `claude_desktop_config.json` vẫn giữ key cũ và ba secret.** Tao không
  sửa file ngoài repo. Chạy `./scripts/bootstrap.sh` (hoặc `python -m ignis.interfaces.cli.setup_bundle`)
  là nó ghi lại entry `fn-ignis` ở cả bốn nơi theo dạng mới, rồi restart Claude Desktop.
- [ ] **Còn lại của mày: `fn-ignis` đang đăng ký hai lần.** Có trong cả `.mcp.json` (workspace) và
  `claude_desktop_config.json` (global), `command` với `args` giống hệt. Đây là nghi phạm cho
  `Connection closed`; server tự nó bắt tay MCP xong trong 1,2 giây, exit 0. Bỏ một trong hai.
- [x] **Đã xong (10/09/2026): sniffer chỉ ghi khi doc_id thật sự đổi.** `GraphQLDocIdCache.set`
  chạy trong request interceptor của Playwright, nên Threads gọi GraphQL bao nhiêu lần thì nó
  chạy bấy nhiêu lần, và lần nào cũng queue một lệnh ghi database. Một lượt đo được 97 lần ghi,
  85 lần cùng một giá trị cho `trending_topics`.

  doc_id chỉ đổi khi Meta ship build frontend mới, mà đó cũng là lý do duy nhất để persist nó,
  nên giá trị không đổi giờ ghi một lần rồi thôi. Token LSD xoay liên tục và không được persist,
  nên nó chỉ cập nhật trong memory và không còn bị tính là thay đổi.

  Sửa thêm hai chỗ trong cùng hàm: task `create_task` trước đây không ai giữ tham chiếu nên có
  thể bị garbage-collect giữa lúc ghi, và exception trong đó bị nuốt hoàn toàn. Giờ task được
  giữ trong một set và lỗi được log, vì một lệnh ghi mất nghĩa là tiến trình sau phải sniff lại.
- [x] **Đã xong (10/09/2026): nhãn chủ đề.** Đo trên 40 cluster đã lưu, dựng lại nhãn bằng chính
  code: **24/40 nhãn bị bọc trong dấu `…`**, nhiều nhãn bị cắt còn hai từ vô nghĩa
  (`bão số`, `ba về`, `tên các`), ba nhãn là danh sách token nối bằng `·`, và một nhãn giữ nửa
  cụm trong ngoặc kép.

  Bốn thứ đã sửa:
  1. Bỏ hẳn dấu `…`. Nhãn vốn đã là bản tóm tắt, đánh dấu nó là đoạn trích không cho người đọc
     thêm thông tin nào mà làm mọi nhãn trông như bị cắt. Toàn văn vẫn ở `canonical_name`.
  2. `TOPIC_LABEL_MIN_WORDS = 3`. Vòng thu gọn trước đây tụt được xuống đúng hai từ.
  3. Fallback loại `ambiguous_unigrams` — clusterer đã nạp sẵn vốn từ đó cho similarity guard,
     nhưng chỗ này chưa hỏi tới nó, nên một nhãn ra `cho · cách · sốp`.
  4. Khi các token đứng liền nhau trong tiêu đề thì trả về đúng cụm đó thay vì danh sách:
     một công viên tên `lê thị riêng` là một cái tên, không phải ba từ khoá.

  Sau khi sửa, trên đúng 40 cluster đó: ellipsis 24 → **0**, ngoặc kép và ngoặc đơn cân hết.
  Token-soup còn 3, vì `_contiguous_phrase` chỉ soi `canonical_name`, và có trường hợp token
  đắt giá nằm ở tiêu đề của signal khác. Chỗ đó tao chưa sửa.

  Ba guard tao thử ngược: đặt lại ellipsis thì 2 test fail, hạ floor về 2 thì test fragment fail,
  trả lại phép so sánh ngoặc kép sai thì test parity fail. Khôi phục thì 10 test pass.
- [x] **Đã xong (10/09/2026): `is_healthy()` của hai connector TikTok là phép đo thật.**
  Cả hai từng `return True` vô điều kiện, nên `verify_connectors_health` báo HEALTHY trong mọi
  hoàn cảnh: host không có browser, chưa có session, TikTok không truy cập được. Bốn trên sáu
  connector có probe thật, hai cái này là hằng số, và điều đó làm cả bản báo cáo mất giá trị.

  Một lượt browser cần đúng hai thứ, giờ probe hỏi đúng hai thứ đó: một Chromium **chạy được**
  và trang cần cào có trả lời. Hai chi tiết phải đo chứ không đoán:
  - `browser_runtime_available()` cũ chỉ kiểm module `playwright` import được, **không** kiểm
    Chromium có trên đĩa. `pip install playwright` mà thiếu `playwright install` thì check đó vẫn
    xanh trong khi mọi lượt browser đều fail. Giờ hỏi thẳng Playwright đường dẫn nó sẽ launch rồi
    kiểm file tồn tại — cách này còn đúng khi có `PLAYWRIGHT_BROWSERS_PATH` hoặc đổi nền tảng,
    trong khi đoán đường cache thì không. Tốn ~0,58s, không launch browser, cache một lần mỗi
    tiến trình. Cổng đăng ký của worker cũng dùng câu hỏi mạnh này.
  - Probe của Threads dùng `follow_redirects=False` và đòi đúng 200. Copy nguyên sang Creative
    Center là **báo sai**: URL của nó trả `301` rồi đáp `200` ở path khác
    (`ads.tiktok.com/creative/creativeCenter/trends`). Hai probe này follow redirect, nhận mọi
    status dưới 400.

  Session **không** tính vào verdict của video grid: explore là trang công khai, và một auth
  manager chưa có gì lưu là trạng thái bình thường trước khi chạy `authenticate_tiktok`. Coi đó
  là hỏng thì báo sai một connector đang chạy tốt. Hạn session là việc của
  `get_platform_auth_status`.

  Kiểm ngược trên host thật: bỏ module playwright → cả hai False; trỏ sang host không tồn tại →
  cả hai False; host thật → cả hai True. Đặt lại `return True` thì 3 test fail.
- [ ] **Còn lại: `BASE_URL` của Creative Center là đường dẫn trước redirect.**
  `/business/creativecenter/inspiration/popular/hashtag/pc/en` giờ 301 sang
  `/creative/creativeCenter/trends`. Browser tự follow nên plugin vẫn chạy. Đo ngày 10/09/2026.
- [x] **Đã xong (10/09/2026): health report nói rõ TikTok chặn ở surface nào.**
  Lượt mission trên seed sạch cho TikTok `AUTH_REQUIRED` với 0 signal, trong khi `is_healthy`
  báo HEALTHY. Tao ban đầu nói nguyên nhân là `search_across_all` đòi session — **sai**.
  `AUTH_REQUIRED` do `strategic_reasoner` suy từ map `auth_status`, còn `search_signals` truyền
  `storage_state=None` xuống Playwright rồi cào bình thường, không đòi gì.

  Nguyên nhân thật, đo được: **không có session TikTok nào được lưu**, và `search_signals` không
  session **chạy không lỗi và trả về 0 card**. Còn `fetch_signals` (explore) thì lượt trước lấy
  17 signal cũng không session. Nên connector này có **hai surface, hai yêu cầu khác nhau**, và
  một boolean không diễn tả được.

  `is_healthy` giữ nghĩa năng lực (browser chạy được + trang trả lời) vì explore vẫn hoạt động
  thật. Thêm `keyword_search_blocked_reason()`, và health report đưa nó ra dạng `remediation`
  cộng một alert `KEYWORD_SEARCH_BLOCKED`, giữ status HEALTHY. Người vận hành giờ đọc được đúng
  lý do một mission không nhận gì từ TikTok.

  Một điểm yếu lộ ra khi làm: `hasattr(plugin, ...)` **luôn True với mock**, nên branch mới gọi
  nó trên mock plugin của hai test khác và nhét `AsyncMock` vào payload JSON — một connector trả
  lời lạ làm sập cả bản báo cáo. Giờ chỉ nhận chuỗi không rỗng. Check `synthetic_probe` sẵn có
  cùng kiểu duck-typing và cùng điểm yếu, nhưng nó nằm ngoài phạm vi lần này.
- [x] **Đã xong (10/09/2026): TikTok mất số view vì một race, không phải vì parser.**
  Sau khi login TikTok, 27/48 signal của mission có `metric_value = 0`. Supply score đọc chính
  cột đó, nên nó ăn thẳng vào chỉ số chính của sản phẩm.

  Kiến trúc plugin vốn đã đúng: nó chặn response JSON của TikTok (`page.on("response")`) và ưu
  tiên `_parse_json_item` — đường đó có `playCount`, `likes`, `comments`, `shares`. Chỉ khi
  **không bắt được JSON** nó mới rơi về `_parse_dom_card`. Và trong DOM **không có số view**: tao
  dò `card`, `parent`, `grandparent`, không `data-e2e` count, không `<strong>` số. Nên sửa
  selector là vô ích.

  Nguyên nhân: `await page.wait_for_timeout(3500)` là khoảng chờ **cứng**. XHR về trước 3,5 giây
  thì có full stats, về sau thì `browser.close()` đã chạy. Chứng minh bằng variance: cùng
  `tay toc`, ba lần liên tiếp một session, mất 8/8 → 1/8 → 0/8.

  Sửa: chờ đúng cái cần chờ. Settle 2000ms rồi poll `captured_items` mỗi 500ms tới 12000ms.
  Poll theo `captured_items` thay vì khớp URL response để nó còn chạy khi TikTok đổi endpoint —
  việc họ đã làm rồi. Trường hợp thường gặp còn **nhanh hơn** cũ: ~2s thay vì 3,5s cố định.

  Đo 3 lần × 2 từ khoá, trước và sau:

  | | trước | sau |
  |---|---|---|
  | tổng mất metric | 33/48 (68,8%) | **1/48 (2,1%)** |
  | `salon toc` | 24/24 | **0/24** |
  | `tay toc` | 9/24 | 1/24 |

  Ba lần tao chẩn sai trước khi tới đây, ghi lại vì cùng một hình dạng: đoán "parse theo vị trí"
  (đúng mô tả, sai nguyên nhân); kết luận "card chưa render" trong khi probe đọc `card` còn
  parser đọc `parent`, tức **đo sai element**; và tưởng `views=0` là đặc tính đường search trong
  khi 197/201 row lịch sử có metric.
- [ ] **Còn lại: supply score không phân biệt "không có dữ liệu" với "không ai xem".**
  `view_factor = 0.0 if loc_views == 0`, nên một signal thiếu metric bị tính như một video 0 view.
  Sau khi sửa race thì chỉ còn 2,1% signal rơi vào diện này, nên không gấp. Sửa đúng cách là ghi
  một cờ trong metadata khi rơi về DOM và cho supply bỏ qua signal đó thay vì coi là 0.
- [ ] **Còn lại: `_contiguous_phrase` chỉ đọc `canonical_name`.** Nếu cụm đáng làm nhãn nằm ở
  tiêu đề của một signal khác trong cùng cluster thì nó không thấy, và nhãn rơi về danh sách
  token. Đây là lý do `lê · thị · riêng` vẫn còn dạng cũ.

- [x] **Đã xong (10/09/2026): `_is_private_or_notification` khớp theo biên từ.**
  Mỗi term giờ compile thành pattern có `\b` hai đầu, khoảng trắng trong cụm khớp lỏng để chịu
  được caption có dấu ngắt dòng. Kiểm `\b` với chữ có dấu trước khi làm: 10/10 ca đúng, gồm
  `đã thích` khớp trong "bạn đã thích video này" mà không khớp trong "đã thíchx".

  Dấu cách cuối của term `"live "` từ đó thành **không còn cần thiết**, nên registration strip
  term. Ghi chú cũ nói dấu cách đó load-bearing giờ đã sai, đã sửa lại.

  Đo trên 15.771 tiêu đề thật: substring loại 47, biên từ loại 46. Bỏ được `olive oil review`
  và `livestream review`; sinh thêm `Studio 2.0 is live.` vì substring cần `"live "` có dấu cách
  nên bỏ lỡ `live.`
- [ ] **NHƯNG: từ vựng của guard này đang gây hại hơn là bảo vệ.** Đo cùng lúc, qua chính plugin:
  trong 46 tiêu đề bị loại, **gần như toàn bộ là post công khai thật**, không phải thông báo:
  - `The new Gmail app icon is live on Google Play`
  - `KHÁT VỌNG VINH QUANG | Tùng Dương - Live at ASEAN Huyndai Cup 2026`
  - `Studio 2.0 is live.`
  - `EM CHỈ MUỐN THÔNG BÁO LÀ EM TÌM CON VỀ ĐƯỢC RUIIIIII`

  Ba term chịu trách nhiệm gần hết: `live` (40 lần), `thông báo` (3), `tin nhắn` (2). Cả ba là
  từ thông thường, không phải chuỗi UI. Chỉ `đang phát trực tiếp` bắn 1 lần và đúng.

  **9 trong 13 term chưa bao giờ bắn**: `follow bạn`, `bắt đầu follow`, `thích bình luận`,
  `thích video`, `đã thích`, `bình luận của bạn`, `đăng lại`, `follow lại`, `hộp thư`. Chúng là
  chuỗi UI thật và không tốn gì.

  Nguyên nhân: từ vựng này lấy từ **trang thông báo** của TikTok, mà connector không cào trang
  đó — nó cào explore và search grid. Lời hứa về quyền riêng tư được bảo đảm bằng **cấu trúc**
  (không bao giờ vào surface đó), còn bộ lọc text này là lớp phụ và đang đắt.

  **Đề nghị:** bỏ ba term `live`, `thông báo`, `tin nhắn` khỏi domain `tiktok_ui_noise`, giữ
  `đang phát trực tiếp` cho badge live tiếng Việt. Tao không tự làm vì đây là từ vựng của một
  privacy guard, và guard đang fail-closed — bỏ term là quyết định của mày.
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
