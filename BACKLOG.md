# 📋 FN-IGNIS BACKLOG & SYSTEM STATUS

> - **Cập nhật lần cuối:** 17/09/2026
> - **Phiên bản:** `v0.4.0`
> - **Kiến trúc:** Clean Architecture + Dual-Backend (Postgres TimescaleDB & Zero-Docker SQLite)
>   + FastMCP Server (39 Handlers & Tools)
> - **Trạng thái:** `v0.4.0` đã tag và publish release, repo public từ 17/09/2026. Đọc trạng thái
>   thật bằng `python scripts/check_release_state.py` chứ đừng tin dòng này — nó là tài liệu, còn
>   tag với release nằm trên Git và GitHub. Cutover trên corpus PostgreSQL hiện hữu chưa chạy.
> - **Trạng thái Tests:** 919 passed, 2 skipped (SQLite + Timescale dùng một lần) | Ruff clean

---

## 0. Chất Lượng Corpus (Epic Đang Mở)

Đo trực tiếp trên Postgres ngày 09/09/2026. Bản đo chi tiết giữ ngoài repository.

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

### Chuẩn bị release v0.4.0 — mở 14/09/2026

- [x] **Đã xong (17/09/2026): rà soát các test cắm cứng ngày tháng.**
  `test_capture_and_publish_clocks.py` đặt `captured_at = 09/09/2026` bằng hằng số, trong khi
  `get_cluster_signals` mặc định lọc theo cửa sổ `LAST_7D` tính từ đồng hồ thật. Test xanh cho tới
  16/09 rồi đỏ từ 17/09 mà **không có dòng code nào đổi** — CI xanh lần cuối lúc 16/09 17:11 UTC,
  đúng ngày cuối cùng còn lọt cửa sổ. Đã sửa: `captured_at` giờ tính tương đối với hiện tại,
  `published_at` giữ tuyệt đối vì không query nào lọc theo nó.

  Mười file còn lại đã rà, và không file nào là bom. Cách rà: đẩy **mọi** hằng số ngày trong file
  lùi 60 ngày rồi chạy lại — mô phỏng đúng thứ đã làm nổ quả bom kia là fixture già đi so với đồng
  hồ. Cả mười giữ nguyên số test pass. Chạy với Postgres thật, vì nhóm integration skip khi không
  có DSN và "pass" do skip thì không chứng minh gì — lần rà đầu tiên chạy không có DSN và suýt
  được nghiệm thu như một kết quả thật.
  Cũng kiểm lớp bom ngược — hằng số nằm ở tương lai rồi thành quá khứ: không có cái nào.

  Nguyên tắc rút ra: hằng số ngày chỉ dùng được khi **không query nào lọc theo nó**; thứ mang nghĩa
  "vừa mới" phải tính từ đồng hồ. Không dựng contract tự động cho luật này vì không diễn đạt được
  một cách đáng tin — một cổng chỉ nhận ra được cách viết hôm nay thì tệ hơn là không có cổng.

- [x] **Đã xong (16/09/2026): verdict quyền của Threads được lưu và mọi chỗ định tuyến đều đọc.**
  `check_keyword_search_access()` vẫn dò như cũ, nhưng giờ ghi verdict vào `runtime_configs` dưới
  khoá `threads_keyword_search_access` qua `ThreadsAuthManager.record_keyword_search_verdict()`.
  Chỉ ghi ba verdict kết luận được (`PUBLIC_SEARCH_ENABLED`, `SELF_ONLY`, `NOT_PERMITTED`);
  `INCONCLUSIVE` và `NO_GRAPH_TOKEN` nghĩa là lần dò đó không học được gì, ghi xuống sẽ xoá mất
  một verdict đã xác lập.

  Ba chỗ đọc lại:
  - `resolve_auth_tier()` — token bị chặn search mà có browser session thì session thắng. Đây là
    chỗ sửa "OAuth token thắng browser session".
  - `resolve_ingest_runtime()` — theo tier ở trên, nên trả `BROWSER`.
  - `search_signals()` — khi Graph token là đường duy nhất còn lại và verdict nói chỉ tìm được bài
    của chính mình thì **raise `ConnectorAuthenticationException`** kèm cách khắc phục, thay vì trả
    về timeline của chính install như bằng chứng thị trường.

  Khoá được scope theo `PLATFORM_NAME` vì `InstagramAuthManager` kế thừa `ThreadsAuthManager`;
  dùng chung khoá thì grant của platform này quyết định định tuyến của platform kia. `clear_auth()`
  xoá luôn verdict — verdict sống lâu hơn token nó mô tả thì token mới thừa hưởng quyền của token
  cũ.

  Không có verdict **không phải** verdict phủ định: install chưa bao giờ dò thì giữ nguyên hành vi
  cũ. Contract: `tests/unit/test_threads_keyword_search_authority.py` (7 test, 3 negative control).


#### Ranh giới blocker — Fio chốt 14/09/2026

Ba mục dưới đây từng nằm chung trong "việc còn lại của release". Chúng không cùng một loại, và gộp
như vậy làm ranh giới phát hành đọc chặt hơn thực tế.

- [x] **T020 đã chạy xong (20/09/2026).** Cutover source/observation đã hoàn tất trên corpus
  PostgreSQL/Supabase; verifier trả `VERIFIED`. Mục này trước đây chặn việc kích hoạt runtime mới
  trên corpus đã có, và chưa bao giờ chặn publish bản open-source beta chạy SQLite cài mới. Bằng
  chứng nằm ở T020 trong phần source identity bên dưới.
- [x] **Đã đạt release acceptance v0.4.0 qua một phiên Claude Code đăng nhập thật
  (14/09/2026).** Từ checkout dùng một lần của `release/0.4.0` tại `49e2be4`, bootstrap tạo cấu
  hình project-scoped chỉ trỏ tới SQLite trong checkout đó. Sau khi Fio đăng nhập và duyệt server,
  model gọi `mcp__fn-ignis__get_runtime_config` với input `{}`. Tool trả `status: SUCCESS` và
  `total_configs: 6`; model đọc kết quả rồi báo lại `total_configs` bằng 6. Phần bằng chứng đã
  sanitize không chứa DSN, Supabase, token, API key hay password. Lượt này đóng khoảng trống mà
  `claude mcp list` và JSON-RPC trực tiếp không chứng minh được: model trong client thật đã gọi
  tool Ignis và đọc kết quả.
- [ ] **P95 benchmark và ngưỡng coverage 85% là khoảng trống đã đo, không chặn beta.** SC-001 chưa
  có benchmark tái lập được nào trên 10.000 dòng cho `get_top_clusters` P95 < 50 ms. SC-004 đặt mục
  tiêu 85% nhưng CI đo 75% và không bật `--cov-fail-under`. Cả hai đã ghi rõ là mục tiêu chưa đạt
  (T021, T022), không phải điều kiện phát hành bản beta. Không được mô tả hai mục này như đã đạt.


- [x] **Đã xong (14/09/2026): hai client local chạy Ignis cùng lúc được.** Startup của MCP server
  `pgrep` chuỗi `ignis.interfaces.mcp.server` rồi `SIGTERM` mọi process khớp. Đó đúng là command
  line của mọi stdio server, nên "stale instance" nó dọn chính là client mở trước. Đo được: cả hai
  server initialize và list 39 tool xong, server đầu thoát với `-15` ngay khi server thứ hai khởi
  động, call tiếp theo raise `BrokenPipeError`. Đã bỏ sweep, giữ handler SIGINT/SIGTERM đóng pool.
  Contract nằm ở `tests/integration/test_concurrent_stdio_clients.py`, chạy subprocess thật; khôi
  phục sweep thì test fail lại.
- [x] **Đã xong (14/09/2026): bootstrap cài đúng bộ version đã khoá.** Trước đây dùng
  `uv pip install -e .`, tức resolve lại từ khoảng version và không đọc `uv.lock`. Giờ là
  `uv sync --locked`, fail rõ khi lock lệch `pyproject.toml`. `uv.lock` đã regenerate bằng
  `uv lock`: lúc đó lock ghi project ở `0.3.0` còn `pyproject.toml` đã ở bản v0.3.5 trước đó.
- [x] **Đã xong (14/09/2026): bump version regenerate `uv.lock` trong cùng commit.** `uv.lock` chứa
  version của chính project, nên đổi `pyproject.toml` mà không chạy `uv lock` sẽ làm
  `uv sync --locked` fail trên checkout sạch và đánh sập CI. Nó là file thứ bảy bên cạnh sáu file
  release-controlled. Cả hai checklist đã bắt buộc bước này: `AGENTS.md` Checklist C và `CLAUDE.md`
  Checklist C đều yêu cầu chạy `uv lock` trong đúng commit bump rồi xác nhận bằng `uv lock --check`,
  và cấm sửa tay file lock. Bump 0.3.5 → 0.4.0 đã chạy đúng như vậy: `uv lock` báo
  `Updated fn-ignis v0.3.5 -> v0.4.0`, diff đúng một dòng version, `uv lock --check` sạch.

### Source identity và mission evidence — quyết định 10/09/2026

- [x] **T020 — cutover đã chạy (mở 13/09/2026, đóng 20/09/2026).** Corpus Supabase đã migrate sang
  `sources` / `observations` / `mission_evidence`. Chạy bằng
  [`scripts/t020_cutover.py`](scripts/t020_cutover.py), viết chính trong lần chạy này vì runbook
  chạy tay có một gate không ai gác: `backfill_observations.py --dry-run` trả exit 0 dù bốn member
  count khớp baseline, lệch baseline, hay không tìm thấy schema đích.

  Bằng chứng, từ journal của lần chạy (giữ cùng snapshot, không commit):

  | Bước | Kết quả |
  |---|---|
  | snapshot | 5.484.109 byte, đọc lại được 844 archive entry |
  | baseline (audit) | exit 0, `BALANCED`, schema_version 7 |
  | `sql/016` | exit 0 |
  | dry run | bốn count khớp baseline, `pre_existing_observations = 0` |
  | backfill apply | exit 0, **8 giây** |
  | verification | exit 0, `VERIFIED` |

  Bốn digest khớp tuyệt đối giữa baseline và corpus sau migrate:

  ```
  sources               0eca4a53c92b73d2d42f2c750e1752131f1d883360db89dbd2ed34dfcf8c9c27   1.924
  observations          08ecb119070f04d8fadf4f2a65ac11cea044b8b8abb274940eec4295182eeac4  18.597
  mission_associations  c92fee13d5937b8e6b19d64daec4e2ec0aa737c8c1d03eadebe6557e2fc632f8   1.301
  cluster_memberships   c67c80103be5b144a1d37286e0da93d5d81d781816e55b84cabfd200a1ab55e5  15.754
  ```

  Ngoài ra: 18.597 dòng observation khớp đúng 18.597 dòng projected; 0 evidence mồ côi, 0
  observation trỏ vào source không tồn tại, 0 metadata sai kiểu; time provenance khớp từng nhóm
  (1.479 `exact_ingestion`, 17.118 `legacy_publish_only`, 0 `unknown`).

  Ba điều lần chạy này đính chính lại so với ghi chép cũ:

  - **`pg_dump` chạy được qua pooler session mode.** Lần diễn tập ghi là pooler từ chối ở startup
    protocol; lần này snapshot 844 entry được lấy qua chính pooler, port 5432.
  - **Host direct connection chỉ có AAAA record** và mạng tại chỗ không có IPv6, nên direct
    connection không tới được. Pooler là đường vào duy nhất.
  - **Pooler không làm tròn double.** Preflight gửi `262600000.00000003` qua connection và nhận về
    nguyên vẹn, nên lo ngại digest cũ không áp dụng cho session mode.

  Bước 8 và 9 đã chạy xong cùng ngày, đúng thứ tự: runtime mới khởi động với ingress đóng, smoke
  test read-only xanh, sau đó mới mở lại ingress theo lịch. Không còn bước nào của T020 đang chờ.

  Kích hoạt runtime làm lộ một defect timeframe nằm ngoài phạm vi cutover; nó được sửa riêng trên
  PR #21 chứ không nhét vào PR #20.

- [x] **Xác nhận duplicate có hai cơ chế, không phải một lỗi duy nhất.** Trên Postgres, nhóm lớn
  nhất là một video YouTube bị lưu 275 lần bởi `save_signals` trước commit
  `478a7c9e5209423a38dcee6cc4a47074bd9d4889`, khi hàm này còn insert vô điều kiện. 275 dòng có
  cùng `captured_at` vì cột đó lúc ấy giữ publish time, nhưng mang 266 giá trị metric khác nhau:
  đây là 275 lần poll, không phải một batch bị nhân bản. Đường `chart=mostPopular` đó không còn
  được public ingress ở HEAD đưa vào corpus.
- [x] **SQLite default nhân đôi source — đã sửa trên nhánh này (chốt 11/09/2026).**
  `save_clusters` tự insert mọi `c.signals` bằng một UUID mới; `ClusterSignalsUseCase` và
  `ExecuteMissionUseCase` sau đó lại gọi `save_signals`. Chạy thật qua `ExecuteMissionUseCase`
  với hai mission cùng một source cho hai row, hai ID và một identity. Đã cắt: `save_clusters`
  chỉ gán `cluster_id` trong bộ nhớ, `save_signals` là đường ghi duy nhất, và
  `test_saving_a_cluster_writes_no_observation` khoá lại điều đó trên cả hai backend.
- [x] **Source identity đã được database cưỡng chế (chốt 11/09/2026).** `trend_signals` không có
  primary key hay unique constraint cho source, và `save_signals` là `SELECT` rồi `INSERT` nên
  concurrent writer có thể đua. Đã thay: `sources` mang `UNIQUE (platform, external_id)` trên cả
  hai backend, và writer dùng **một câu** upsert `ON CONFLICT` chứ không còn `SELECT`-rồi-`INSERT`.
  Bảng legacy giữ nguyên trạng thái cũ vì nó đã thành read-only.
- [ ] **Threads và Reels còn khoảng trống alias — mở, chốt 13/09/2026.** "Một object, một
  identity dù đến bằng route nào" đã đóng cho TikTok và Google: hashtag hội tụ dù metadata ghi
  `#aothun` còn URL ghi `/tag/aothun`, keyword hội tụ dù explore URL percent-encode nó. Hai
  platform kia thì chưa, và cố ý chưa. Graph API trả primary key dạng số, permalink mang
  shortcode, và build hiện tại không có đường tra từ giá trị này sang giá trị kia:

  ```
  threads  post:123456789  ≠  post_shortcode:123456789
  reels    reel:17912      ≠  reel_shortcode:17912
  ```

  Để chung một namespace `post:` thì một shortcode toàn chữ số sẽ **va vào primary key của bài
  khác** — base64 có chứa chữ số — và merge sai thì im lặng, vĩnh viễn. Split thì đo được và sửa
  được bằng alias sau. **Giới hạn thật, ghi đúng như nó là:** corpus hiện tại có **0** cặp như
  vậy, nhưng ingress tương lai vẫn có thể tạo hai dòng cho cùng một bài, vào đúng lúc một bài
  được thấy bằng cả hai route. Đóng nó cần một trong hai: connector ghi cả hai giá trị vào
  metadata, hoặc một bảng alias giữa hai namespace cộng một lượt reconcile corpus.
- [x] **Migration `sql/008_deduplicate_signal_metrics.sql` không thực hiện điều header tuyên bố.**
  File ghi "Deduplicate trend_signals", "keeps earliest row as canonical" và tự gọi mình là
  "Migration 004", nhưng chỉ tạo `signal_metrics` rồi copy metric; không delete duplicate, không
  re-parent và không tạo unique constraint.
- [x] **Chọn mô hình ba thực thể thay cho mission-scoped dedup:** một canonical source theo
  platform-specific external identity; nhiều immutable observation theo lần thu thập; và
  mission-evidence association trỏ tới đúng observation mà dossier đã dùng. Lý do đo được:
  mission chỉ chiếm 1.301/15.938 row (8,2%), trong khi 14.377 row (90,2% corpus) nằm trong 378
  duplicate identity group của radar — mission-scoped dedup không chạm vào phần hỏng lớn nhất.
  Migration phải giữ legacy rows tới khi đối soát xong; evidence của các mission chưa từng được
  persist không thể dựng lại từ count trong summary.
- [x] **Cluster membership thuộc observation, không thuộc source (chốt 10/09/2026).** Canonical
  source chỉ trả lời "đây là nội dung nào"; nó không trả lời "lần quan sát này đóng góp cho chủ
  đề nào". Cùng một video được probe bởi hai keyword khác nhau ở hai thời điểm có thể thuộc hai
  cluster, và đó là thông tin thật chứ không phải xung đột cần giải. Kéo theo:
  `cross_platform_score` phải đọc observation trong analysis window rồi đếm distinct platform và
  distinct source, chứ không đếm row. `cluster_id` vì vậy không được đặt trên bảng source.
- [x] **Giữ Timescale thật trong CI, không mock và không cho skip (chốt 10/09/2026).** Một
  dual-backend contract mà nhánh Postgres có thể skip thì chưa phải dual-backend contract: không
  có service, case đó skip im lặng và suite trông nhẹ hơn thực tế một failure. Chi phí là CI phải
  boot container mỗi lần chạy và phụ thuộc một image bên thứ ba. Đo lại thời gian sau lần GREEN
  đầu tiên; nếu ảnh hưởng đáng kể thì **tách Postgres contract thành job song song**, không bỏ và
  không mock.
- [x] **Baseline đối soát là bằng chứng migration lâu dài, không phải handoff (chốt
  10/09/2026).** Bản đã sanitize được track ở `docs/migrations/2026-09-10-source-observation-
  baseline.{json,md}`: chỉ công thức, aggregate count, reason-code total, 11 invariant result và
  một SHA-256 trên mỗi tập canonical. Baseline hiện là `schema_version: 7`, 14/14 invariant. Không
  title, URL, external ID hay mission title. Bản
  row-level có nêu identity thì ở ngoài git, đi cùng database backup. Digest khoá trên business
  identity chứ không trên `trend_signals.id`, vì digest khoá trên surrogate key sẽ đổi ngay khi
  migration ghi lại dòng — mất giá trị đúng lúc cần nhất.
- [x] **Hai observation cùng source trong một mission: giữ cả hai (chốt 10/09/2026).**
  Constraint là `UNIQUE (mission_id, observation_id)`, **không** phải
  `UNIQUE (mission_id, source_id)`. Mission ledger phải lossless; migration không được tự đoán
  observation nào thừa. Analysis mặc định chọn observation mới nhất của mỗi source để tính score
  và trình bày headline, còn toàn bộ observation vẫn giữ cho timeline, citation và audit.
  Baseline đo được 2 mission đang ở tình trạng này.
- [x] **Contract mới cho `cross_platform_score` (chốt 10/09/2026).** Bản hiện tại ở
  `semantic_clusterer.py:_calculate_cross_platform_score` cộng `metric_value` của **mọi** row và
  lấy average velocity trên **mọi** row, nên tần suất poll làm điểm tăng dù không có thêm source
  độc lập nào — một video bị poll 275 lần đóng góp 275 lần. Nó cũng chia
  `len(unique_platforms) / 5.0`, tức hard-code 5, và một platform duy nhất vẫn được 8 điểm.

  Contract mới: lọc observation theo analysis window; chọn observation mới nhất cho mỗi canonical
  source; mỗi source đóng góp đúng một lần vào metric và velocity; platform component tính theo
  số platform độc lập — `1 platform → 0`, `2 → 20`, `3+ → 40`. Không chia cho tổng connector,
  không hard-code 5, không để channel lỗi làm topic khác tự nhiên được điểm cao hơn.

  Tổng trọng số tạm giữ `40 platform + 40 metric + 20 velocity`. Việc normalize metric khác đơn vị
  giữa Google index, view và engagement là một scoring decision riêng, không nhét vào
  data-model migration.
- [x] **Timestamp lịch sử: không ghi publish time vào ingestion time (chốt 10/09/2026).**
  Observation schema cần `observed_at` nullable, `published_at` nullable, và `time_provenance` với
  ba giá trị `exact_ingestion` / `legacy_publish_only` / `unknown`. Với dòng YouTube và Google
  Trends lịch sử không chứng minh được thời điểm thu thập: `observed_at = NULL`,
  `published_at = captured_at` cũ, `time_provenance = legacy_publish_only`. Time-window score mặc
  định chỉ dùng `exact_ingestion`; dữ liệu legacy vẫn được xuất hiện trong all-history hoặc
  published-time analysis nhưng output phải gắn cảnh báo approximate.
- [x] **Thay evidence theo kiểu failure-safe, không còn nhãn "Atomic Replace" (chốt 11/09/2026).**
  `delete_mission_signals()` commit ở transaction riêng, rồi cluster / save / attach chạy ở các
  transaction sau. Writer lỗi giữa chừng thì mission mất sạch evidence cũ mà không có gì thay thế:
  tái hiện được trên SQLite, evidence `1 → 0`; Postgres cùng transaction boundary. Không chặn việc
  viết backfill, nhưng phải xử lý trước merge.

  Chốt hướng thứ hai: **ghi mới trước, prune cũ sau**, không mở transaction abstraction xuyên use
  case. Thêm `prune_mission_evidence(mission_id, retained_ids)`; `delete_mission_signals()` rời
  khỏi đường execute và ở lại đúng vai trò withdrawal tường minh. Bảo đảm mới **yếu hơn atomic và
  đủ dùng**, và phải phát biểu cho đúng: **mọi lỗi xảy ra trước hoặc trong lúc prune** thì mission
  giữ **ít nhất** số evidence nó đang có. Prune chạy xong thì replacement đã hoàn tất — lỗi sau đó,
  ví dụ `update_mission(COMPLETED)`, là lỗi sau khi thay xong chứ không làm mất evidence. Claim
  thừa sót lại sau lỗi thì pass sau dọn; evidence bị xoá bởi một pass lỗi thì mất luôn. Retained
  set đọc từ `observation_id` thực sự ghi được, không phải từ danh sách signal — sighting bị
  writer bỏ qua không mang observation id nên không được tính là evidence.
- [x] **SQLite persist `platforms` của mission (chốt 13/09/2026).** Schema SQLite và
  `save_mission`/`get_mission` không persist `platforms`. Mission tạo với đúng YouTube, đọc lại
  thành mặc định năm platform. Quota test không bắt được vì fake registry bỏ qua `target_platforms`.
  Hệ quả user-facing: summary in ra "1 signal across 1/5 responsive platforms" cho một pass thực
  tế thu **0** signal và **0** platform phản hồi — con số duy nhất còn lại đến từ một observation
  cũ được preserve. Đây là defect về bằng chứng hiển thị cho người dùng.

  Đã sửa: thêm cột `platforms` (JSON list) cho database mới, `ALTER` idempotent cho database cũ,
  upsert ghi cả nhánh insert lẫn nhánh conflict, và hai đường hydrate đọc qua `resolve_platform`.
  Dòng có từ trước cột này **không phục dựng được** target thật — selection chưa từng được ghi —
  nên chúng nhận default năm platform để giữ đúng hành vi cũ; đây là **assumption của migration,
  không phải bằng chứng lịch sử**. Postgres không phải đổi, chỉ chạy thêm contract parity.
- [ ] **Chưa đo: `first_seen_at` đã lưu của các cluster cũ (mở 11/09/2026).** Bản sửa nullable-clock
  chỉ áp cho cluster **mới tính**; nó không sửa giá trị đã nằm trong `topic_clusters`, và cả hai
  upsert đều không cập nhật `first_seen_at` khi cluster đã tồn tại. Nghĩa là một cluster từng được
  tính bằng `min()` trên publish-time clock sẽ giữ nguyên giá trị đó vô thời hạn. Baseline **không**
  digest `topic_clusters.first_seen_at`, nên hiện chưa biết corpus có bao nhiêu giá trị bắt nguồn từ
  publish time. Không kéo vào backfill. Trình tự: đo trước — đếm cluster có `first_seen_at` trùng
  `published_at` của một signal thành viên — rồi mới quyết giữ, xoá hay gắn provenance.
- [x] **Runtime ngừng ghi bảng legacy (chốt 11/09/2026).** `save_signals` chỉ còn ghi `sources`,
  `observations`, `mission_evidence`; không còn `SELECT/INSERT/UPDATE trend_signals` hay
  `INSERT signal_metrics` ở bất kỳ đâu trong hai repository. Hai bảng legacy **không** bị drop —
  audit, backfill và toàn bộ lịch sử migration còn đọc chúng — nhưng chúng thành read-only. Tới
  đây data-model cutover hoàn tất ở runtime: một nguồn sự thật. Test cũ assert dedup legacy đã
  **chuyển** sang assert contract source/observation chứ không xoá: poll lặp một source cho một
  source và hai observation; URL cấp feed của Google Trends không gộp hai keyword; identity test
  đếm dòng trong `sources`.
- [x] **Reader / scoring / pruner đọc `observations`, không đọc `trend_signals` (chốt 11/09/2026).**
  `get_top_clusters`, `get_cluster_signals` và `prune_empty_clusters` chuyển sang
  `observations → sources` trên cả hai backend. Window mặc định chỉ nhận `exact_ingestion` có
  `observed_at`; **không** dùng `published_at` thay clock cho 17.118 dòng legacy. Trong window,
  mỗi source đóng góp đúng một lần — observation mới nhất theo `source_id`, không theo URL, vì
  corpus có một source xuất hiện dưới hai biến thể URL còn URL cấp feed thì nhiều item dùng chung.
  Pruner giữ cluster có ít nhất một observation membership, kể cả observation legacy ngoài window.
  `cross_platform_score` giờ chỉ có **một** implementation ở `src/ignis/domain/cross_platform_score.py`;
  trước đó có ba, và bản SQL vẫn chia số platform cho 5 trong khi quyết định đã ghi là dải
  `1 → 0`, `2 → 20`, `3+ → 40`. Metric và velocity giữ nguyên normalization.
- [x] **`first_seen_at` của cluster là earliest exact ingestion, nullable (chốt 11/09/2026).**
  `min(s.captured_at for s in group)` raise `TypeError` ngay khi group trộn observation legacy với
  observation exact — đúng hình dạng sẽ xuất hiện sau backfill. Semantics chốt: bỏ qua observation
  không có clock; cả group đều legacy thì `first_seen_at = NULL`; **không** thay bằng
  `published_at` hay `now()`, cùng lý do đã bỏ lifecycle cache khỏi `sources`. Kéo theo:
  `TopicCluster.first_seen_at` nullable, cột SQLite bỏ `NOT NULL`, và cả hai backend ngừng thay
  `now()` khi ghi lẫn khi đọc. Database SQLite có sẵn phải rebuild bảng, vì
  `CREATE TABLE IF NOT EXISTS` không nới được ràng buộc.
- [x] **Discovery gắn cluster bằng `assign_observation_clusters`, không ghi lại signal (chốt
  11/09/2026).** `AutonomousDiscoveryUseCase` gọi `save_signals()` ở bước 4 rồi
  mới `save_clusters()` ở bước 6, và không ghi lại signal sau đó — observation nằm lại với
  `cluster_id = NULL`. Đây là lỗi **có sẵn**, không phải regression: trên Postgres, `save_clusters`
  chỉ gán `cluster_id` trong bộ nhớ, nên đường này chưa bao giờ persist membership. Trên SQLite
  trước đây nó "có" membership nhờ chính đường ghi trùng vừa bị cắt, tức là bằng cách tạo dòng
  thứ hai cho cùng một source. Hai cách sửa, chưa chọn: (1) đảo thứ tự trong discovery để cluster
  chạy trước khi persist; (2) thêm thao tác repository gán cluster cho observation đã ghi. Chọn
  (2), vì membership trên một observation đã tồn tại là `UPDATE`, còn gọi lại `save_signals()`
  đúng nghĩa tạo collection event thứ hai. Test khoá bằng **thứ tự lời gọi**: sau `save_clusters`
  không được có `save_signals` nào nữa.
- [x] **Read contract theo kịp model mới (chốt 11/09/2026).** `TrendSignal` mang thêm
  `observation_id`, `identity_source`, `time_provenance`, và `captured_at` thành nullable —
  `None` nghĩa là không biết thời điểm thu thập, đúng trạng thái của 17.118 observation legacy.
  SQLite trước đây thay `NULL` bằng `datetime.now()`, tức biến "không biết" thành "vừa thu thập",
  và bỏ luôn `cluster_id` dù query đã đọc. Quota fallback không còn đẩy observation cũ qua writer:
  nó giữ evidence bằng `attach_mission_evidence`. `save_signals()` trả số observation thật sự ghi,
  không còn trả số dòng insert vào bảng legacy.
- [x] **`INSERT OR REPLACE` trên SQLite phá dữ liệu con khi bật foreign key (sửa 11/09/2026).**
  `REPLACE` là `DELETE` rồi `INSERT`, nên mỗi lần cập nhật trạng thái mission sẽ cascade xoá sạch
  `mission_evidence` vừa ghi, và mỗi lần lưu lại một cluster sẽ `SET NULL` cluster của mọi
  observation đang trỏ tới nó. Cả hai chuyển sang `ON CONFLICT (id) DO UPDATE`. Lỗi này chỉ lộ ra
  sau khi bật `PRAGMA foreign_keys = ON` — trước đó FK không được cưỡng chế nên `REPLACE` trông
  vô hại.
- [x] **`sources` chỉ ba cột; route và URL thuộc observation (chốt 11/09/2026).** `sources` giữ
  `id`, `platform`, `external_id` và không gì khác. `identity_source` xuống `observations`,
  `NOT NULL`, `CHECK` ba giá trị, và là field thứ 11 của projection — cùng lý do đo được đã dùng
  để chốt namespace: ba video YouTube vào corpus bằng hai route, nên một cột ở tầng source chỉ giữ
  được một route. `canonical_url` bỏ hẳn: URL là thứ một lần quan sát báo về, và corpus đã có
  source xuất hiện dưới hai biến thể URL, nên cột đó là cache "URL mới nhất" không rebuild contract
  — citation dùng `observation.source_url`, canonical locator derive từ `(platform, external_id)`.
  `first_seen_at`/`last_seen_at` cũng bỏ, vì 17.118 observation không có ingestion time nên
  `NOW()` sẽ bịa lifecycle. Baseline lên `schema_version: 5`; digest `sources` giữ nguyên
  `69d72aee192bf526`, ba digest còn lại đổi, member counts không đổi.
- [x] **Identity khoá theo namespace của object, không theo nhãn field (chốt 10/09/2026).**
  Audit đang khoá identity theo `platform:<tên field>:<giá trị>`, mà tên field là cách audit
  *tìm ra* identifier chứ không phải bản chất object. Hệ quả đo được trên corpus thật: cùng một
  video YouTube đi vào hai lần, một lần có `video_id` trong metadata và một lần chỉ parse được từ
  URL (nhãn `video`), nên bị tính thành hai canonical source. Có **3 cặp** như vậy.
  Nếu chuẩn hoá về namespace của object (`video_id ≡ video`, `item_id ≡ video`,
  `hashtag ≡ tag`, `post_id ≡ post`, `reel_id ≡ reel`, `keyword ≡ probe_keyword`) thì:
  source **1.927 → 1.924**; observation vẫn **18.597** và ba bucket provenance không đổi
  (1.479 / 17.118 / 0); mission evidence vẫn **1.301** với 2 mission lặp identity; cluster
  membership vẫn **15.754** nhưng identity nằm nhiều cluster tăng **172 → 175**; reason code
  `repeat_observation_of_one_source` 14.089 → 14.095. Cả bốn digest đổi, audit vẫn `BALANCED`.
  Đã chốt 1.924: giữ 1.927 đồng nghĩa backfill cố tình tái tạo ba source đã biết là bị chia sai.
  Đường phân giải có chỗ riêng, không tham gia key — v5 chuyển nó xuống
  `observations.identity_source`, xem mục dưới. Baseline
  regenerate thành `schema_version: 4`, member counts `1.924 / 18.597 / 1.301 / 15.754`, cả bốn
  digest đổi. Kéo theo một quyết định kiến trúc: policy không được nằm trong script audit, vì
  commit persistence viết lại mapping sẽ thành định nghĩa identity thứ hai. Resolver canonical ở
  `src/ignis/domain/source_identity.py`; audit, backfill và live write path gọi cùng một hàm.
- [x] **Không dùng `xfail` cho defect này (chốt 10/09/2026).** `xfail` trên `main` biến một
  data-integrity defect đang hoạt động thành "known acceptable failure". Giá trị của contract test
  là làm merge gate; BACKLOG đã đủ để defect hiện diện trên `main`. Contract sống RED trên branch
  `codex/source-observation-evidence` và chỉ merge khi cả nó lẫn toàn suite đều xanh.
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
  đúng dòng, đã thử.

  **Chỗ không lấy lại được:** với các dòng ghi trước migration bởi ba code path đó, `captured_at`
  vẫn là ngày đăng, và thời điểm thu thập thật chưa từng được lưu. Giữ nguyên chứ không đóng
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
- [x] **Đã sửa (10/09/2026): seed keyword bị nhiễm từ vựng máy móc.** Đây là regression tự gây
  ra ngày 09/09: `NON_TOPIC_LEXICON_DOMAINS` trong `ingest_trends.py` chỉ loại 2 domain cũ, nên 8
  domain máy móc thêm hôm đó chảy thẳng vào seed. Đo trên Postgres thật: **cả 10 seed** đều là hư
  từ tiếng Việt, vì `ambiguous_unigrams` sắp trước theo bảng chữ cái và chiếm trọn budget.

  Nghĩa là lượt 6 connector báo cáo hôm qua đã probe các nền tảng bằng hư từ. Phần signal từ
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

- [x] **Đã xong (17/09/2026): ba credential vận hành đã xoay vòng, Fio xác nhận.**
  Ngày 10/09/2026 có một quyết định hoãn xoay vòng, với điều kiện xem lại ghi ngay trong quyết
  định đó: xem lại nếu có người ngoài truy cập được hệ thống. Chuyển repository sang public chính
  là điều kiện ấy, nên quyết định hoãn đã hết hiệu lực và việc xoay vòng được thực hiện.

  Ba credential — mật khẩu database, khoá mã hoá, và khoá API nền tảng video — đều đã được thay.
  Quy trình chạy ngoài repository; không giá trị nào được ghi vào đây, và mục này chỉ ghi lại xác
  nhận của người vận hành chứ không tự suy ra từ bất kỳ phép đo nào.

  Một phần có bằng chứng độc lập: GitHub secret scanning bật ngày 17/09 đã dựng alert #1 cho một
  Google API key nằm trong `.mcp.json` ở commit `8a7b376e` (07/09). Commit đó không còn reachable
  từ ref nào sau lần viết lại history ngày 09/09, nhưng GitHub vẫn giữ object mồ côi — trả lời dứt
  điểm câu hỏi treo trong `docs/PROJECT_REVIEW_CONTEXT.md` mục 4 là remote **chưa** garbage-collect.
  Fio đối chiếu mười ký tự đầu với key đang dùng, xác nhận đã khác; alert được đóng với resolution
  `revoked`. Object mồ côi vẫn còn cho tới khi GitHub Support purge, nhưng giá trị trong đó đã chết.

  Việc còn lại của người vận hành, không chặn gì: đổi khoá mã hoá làm ciphertext cũ không đọc được,
  nên từng connector phải `authenticate_*` lại; và `claude_desktop_config.json` trên máy vận hành
  cần bỏ bốn khoá credential còn sót, xem mục ngay bên dưới.

- [x] **Đã xong (10/09/2026): MCP config giữ đường dẫn tới `.env`, không giữ secret.**
  `build_mcp_entry` từng sao `DATABASE_URL`, `IGNIS_ENCRYPTION_KEY` và `YOUTUBE_API_KEY` vào
  **bốn** file: `.mcp.json`, config Claude Desktop, config Antigravity và TOML của Codex. Vừa để
  password database cùng khoá Fernet ở dạng plaintext bốn nơi, vừa tạo bốn nguồn sự thật.

  Hậu quả thật đã xảy ra: sau khi rotate key YouTube, `.env` và `.mcp.json` được cập nhật nhưng
  config Claude Desktop còn giữ key cũ. Vì `env` của host ghi đè file env, mọi lệnh gọi YouTube
  qua MCP thất bại với "API key expired", trong khi cùng đoạn code chạy từ shell lại thành công.
  Đó chính là chỗ báo cáo "key expired" rồi ngay sau đó một lượt pass lấy được 95 signal.

  Giờ entry chỉ mang `IGNIS_ENV_FILE`, một đường dẫn tuyệt đối. Kiểm với `env -i`: chỉ một biến
  đó là server load đủ DSN, key YouTube và khoá Fernet.
- [x] **Đã sửa (10/09/2026): thứ tự đọc env file bị ngược.** `env_file=(_PROJECT_ENV, ".env")` —
  pydantic-settings cho file **cuối** quyền cao nhất, nên một `.env` lạ nằm ở thư mục mà host
  tình cờ khởi động server sẽ ghi đè `.env` của project. Một decoy dựng lên để chứng minh: thứ tự cũ
  cho decoy thắng, thứ tự mới cho project thắng. Có test giữ đúng thứ tự vì lỗi này im lặng, chỉ
  sai giá trị chứ không báo gì.
- [ ] **Việc của người vận hành: `claude_desktop_config.json` vẫn còn giá trị cũ.** Kiểm lại
  13/09/2026: entry global vẫn mang trực tiếp bốn biến môi trường thay vì một đường dẫn, trong
  khi `.mcp.json` đã chỉ còn `IGNIS_ENV_FILE`. Claude Desktop giữ config trong memory và ghi đè external edit khi thoát, nên
  thứ tự đúng là: **quit Claude Desktop trước**, chạy `./scripts/bootstrap.sh` (hoặc
  `python -m ignis.interfaces.cli.setup_bundle`), rồi mở lại app. Chạy bootstrap khi app còn mở
  không tạo thay đổi bền vững.
- [x] **Rút lại giả thuyết `fn-ignis` đăng ký hai lần (13/09/2026).** `.mcp.json` là registration
  của workspace client, `claude_desktop_config.json` là registration của Claude Desktop; một entry
  trong mỗi client không phải hai server được cùng một client khởi động. Hai `command`/`args` giống
  nhau là đúng. Không còn dùng giả thuyết này để giải thích `Connection closed`; nguyên nhân đó vẫn
  chưa xác định.
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
  đắt giá nằm ở tiêu đề của signal khác. Chỗ đó chưa sửa.

  Ba guard đã thử ngược: đặt lại ellipsis thì 2 test fail, hạ floor về 2 thì test fragment fail,
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
- [x] **Đã xong (10/09/2026): `BASE_URL` của Creative Center dùng URL sau redirect.**
  `/business/creativecenter/inspiration/popular/hashtag/pc/en` trả 301 sang
  `/creative/creativeCenter/trends`; commit `cde326c` đã đổi constant sang URL đích. Contract
  `test_tiktok_health_probes.py` giữ đúng URL này. Mục cũ vẫn để mở dù code và test đã đóng nó.
- [x] **Đã xong (10/09/2026): health report nói rõ TikTok chặn ở surface nào.**
  Lượt mission trên seed sạch cho TikTok `AUTH_REQUIRED` với 0 signal, trong khi `is_healthy`
  báo HEALTHY. Chẩn đoán ban đầu cho rằng nguyên nhân là `search_across_all` đòi session — **sai**.
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
  **không bắt được JSON** nó mới rơi về `_parse_dom_card`. Và trong DOM **không có số view**:
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

  Ba lần chẩn sai trước khi tới đây, ghi lại vì cùng một hình dạng: đoán "parse theo vị trí"
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
  `đang phát trực tiếp` cho badge live tiếng Việt. Chưa tự thay vì đây là từ vựng của một
  privacy guard, và guard đang fail-closed — bỏ term là quyết định của người vận hành.
---

## 🚀 1. Hiện Trạng Hệ Thống Đã Hoàn Thành (Current Accomplishments)

### A. Hạ Tầng & Cơ Sở Dữ Liệu
- [x] **Supabase Cloud Pooler:** Kết nối qua Supabase pooler bằng `psycopg_pool.AsyncConnectionPool`. Endpoint và region lấy từ `DATABASE_URL`, không ghi vào repository.
- [x] **Schema Bền Vững:** runtime dùng `sources`, `observations`, `mission_evidence` cùng
  `research_missions`, `topic_clusters`, `system_audit_logs`, `platform_credentials`. Hai bảng
  `trend_signals` và `signal_metrics` chỉ còn phục vụ lịch sử migration và chưa bị drop.
- [x] **Lightweight Worker Container:** Dockerfile tối ưu (~90MB, multi-stage uv build) chạy nền 24/7 trên OrbStack.
- [x] **Credentials Hardening:** `CryptoService` áp dụng Fernet AES-128-CBC + HMAC-SHA256, có
  fail-fast (`assert_persistent_key`) từ chối ghi credential dài hạn dưới ephemeral key. Bản ghi
  mã hóa mang nhãn `key_version` ("v1"), nhưng đó **chỉ là metadata envelope**: `decrypt_credentials()`
  dựng một Fernet từ khóa hiện tại và không đọc nhãn đó. Chưa có dual-key decryption và chưa có
  re-encryption tự động, nên **không được mô tả là sẵn sàng cho key rotation**.

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
- [x] **Danh mục 39 FastMCP Tools:** Hoàn thiện và đồng bộ đối xứng giữa `server.py`, `openclaw.json`, `hermes_manifest.json`, `.hermes/tools.json` và `setup_bundle.py`.
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

### 🎯 Epic 2: Data Provenance, Ingress Health Audit & Citation Attribution Engine (Partial)
*Mục tiêu: Xóa bỏ nhận định mơ hồ và ảo giác; minh bạch hóa nguồn gốc dữ liệu (Data Provenance) và phát hiện kênh ingress bị rỗng/lỗi.*
- [ ] **Channel health còn thiếu surface-level identity:** `ChannelDataSummary` đã có đủ năm status
  và báo năm platform mà mission nhắm tới, kèm count và top citation. Nó chưa tách TikTok Video Grid
  khỏi TikTok Comments; cả hai đang cùng là `PlatformType.TIKTOK`, nên một surface khỏe có thể che
  surface kia hỏng. Quyết trước xem health contract là platform hay connector surface rồi mới đổi
  schema/payload.
- [ ] **Citation Attribution còn thiếu hai consumer:** `StrategicInsight` và top citation của
  channel đã dùng `CitationEvidence`; `get_mission_analysis` serialize được chúng. Nhưng
  `MarketOpportunity.supporting_signals` và `actionable_takeaways` vẫn là `List[str]`, nên chưa có
  typed citation gắn trực tiếp vào cơ hội và hành động như spec hứa. Quan trọng hơn,
  `CitationEvidence` chưa mang `observation_id`, còn `_citation_key()` tự định danh bằng
  `platform | source_url-or-title` thay vì dùng observation/source identity đã được repository
  giải quyết. Đây là bản source identity thứ hai: URL variant có thể tách một source thành hai
  citation, còn URL dùng chung hoặc title trùng có thể gộp sai. Contract cần trỏ citation tới đúng
  observation trong `mission_evidence`; display URL/title chỉ là payload.
  - **HTML consequence:** dashboard đã render Data Ingress audit và citation pills dưới strategic
    insights; opportunity và actionable chưa thể có pill cho tới khi model mang typed citation.
  - **FastMCP consequence:** payload đã có `channel_summaries` và citations cho
    `strategic_insights`; phần còn lại là serialize đúng typed citation mới, không phải một backlog
    item độc lập. Xem
    [docs/DATA_PROVENANCE_AND_CITATION_SPEC.md](docs/DATA_PROVENANCE_AND_CITATION_SPEC.md).

### Parking lot — giả thuyết roadmap, không phải backlog đã cam kết

Các mục dưới đây chưa có measurement, decision hay release target. Chúng được giữ để không mất ý
tưởng, nhưng không được tính là việc đang mở cho tới khi một outcome cụ thể được ưu tiên.

#### Epic 3: Live Alerts & Notification Webhooks
*Mục tiêu: Đẩy thông báo chủ động cho người dùng khi xu hướng bùng nổ.*
- **Persisted Discovery State:** Lưu trữ `last_discovery_time` vào cơ sở dữ liệu thay vì biến in-memory, tránh tình trạng khởi động lại daemon worker gửi lại toàn bộ alert cũ.
- **Webhook Deliveries & Idempotency:** Thiết kế bảng `webhook_deliveries` với dedup key duy nhất (`topic_id` + `alert_type` + `date`) và pipeline retry/backoff.
- **Breakout Trend Webhook:** Tự động gửi cảnh báo qua Slack / Telegram / Discord khi một topic cluster đạt `cross_platform_score >= 80.0` (Momentum: BREAKOUT).
- **Weekly Executive Digest:** Tự động chạy báo cáo tổng kết xu hướng hàng tuần và xuất bản trang HTML tĩnh.

#### Epic 4: Multi-Language & Regional Expansion (SEA & Global)
*Mục tiêu: Mở rộng khả năng lắng nghe thị trường ngoài Việt Nam.*
- **Đa khu vực (Geo Expansion):** Mở rộng bộ phân tích cho các thị trường Đông Nam Á (`TH`, `ID`, `MY`, `SG`, `PH`) và Toàn cầu (`US`, `GLOBAL`).
- **Cross-Language Semantic Alignment:** Đối chiếu các chủ đề đang bùng nổ tại thị trường US/Trung Quốc với tốc độ du nhập về Việt Nam (Time-Lag Arbitrage).

#### Epic 5: Trend Velocity Forecasting (Dự Báo Tương Lai)
*Mục tiêu: Đo lường chu kỳ sống của xu hướng.*
- **Time-series Projection:** Sử dụng mô hình ARIMA / Exponential Smoothing trên chuỗi dữ liệu Google Trends để dự đoán thời điểm xu hướng chạm đỉnh (Peak Interest).
- **Saturation Index:** Tính toán ngưỡng bão hòa của thị trường dựa trên tốc độ ra mắt video mới của các nhà sáng tạo nội dung.

---

## 🛠️ 3. Hướng Dẫn Kích Hoạt Cho Session Mới

Khi mở session mới với bất kỳ Agent nào (Antigravity, Claude Code, Codex), chỉ cần truyền lệnh:

> *"Đọc file `BACKLOG.md` để nắm hiện trạng kiến trúc `fn-ignis` và bắt đầu triển khai [Tên tính năng trong Backlog]."*
