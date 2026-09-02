# fn-ignis — Round 3 Final Audit: Phán quyết Release

- **Ngày**: 02/09/2026 · **HEAD**: `97635a2` · **Working tree**: clean 100% ✓
- **Chuỗi audit**: Round 1 `c8f954c` → Round 2 `402cb5b` → Round 3 `97635a2`
- **Phương pháp**: dựng Postgres thật `timescale/timescaledb-ha:pg16` chạy `sql/` qua `/docker-entrypoint-initdb.d` **không sửa gì**, CRUD thật qua repository, test noise filtering qua **cả 3 đường production** trên **cả 2 backend**, tấn công thử khóa mã hóa bằng mọi công thức tĩnh suy được từ source.

---

## 0. Bảng nghiệm thu Điều kiện Round 3

| Điều kiện tôi đặt ra cuối Round 2 | Kết quả |
|---|---|
| Container Postgres `Up` + 7/7 bảng với `sql/` không sửa | 🟢 **ĐẠT** |
| Không giải mã được bằng khóa tự suy từ source | 🟢 **ĐẠT** |
| Lọc 4/4 tiêu đề hài nhảm **qua production path** | 🟡 **ĐẠT 1/3 đường, trên 1/2 backend** |
| `git status` sạch + toàn bộ test pass | 🟢 **ĐẠT** (75/75, ruff 0 error) |

---

## 1. Ba Blocker của Round 2 — nghiệm thu

### 🟢 Blocker ① — Postgres Initdb & Docker tag: **ĐẠT**

Chạy lại **chính xác** test đã fail ở Round 2, `sql/` nguyên trạng, image đúng compose:

```
STATUS      : Up
ERROR log   : (rỗng — 0 lỗi trong initdb)
BẢNG        : industry_taxonomies, market_lexicons, platform_credentials,
              research_missions, system_audit_logs, topic_clusters, trend_signals   → 7/7
```

Round 2 cùng lệnh này cho `Exited (3)` / 0 bảng. Đổi tên `init.sql` → `001_initial_schema.sql` đã giải quyết trọn vẹn. Tag `timescale/timescaledb-ha:pg16` pull được ✓.

**CRUD thật qua repository trên container này:**
```
create_mission             : ĐẠT   shortcode = VN-XU-H-7D-1976
get_mission (UUID/shortcode/session_id) : True (cả 3)
save_signals / get_mission_signals / delete_mission_signals : 1 / 1 / 1
audit log ghi + đọc        : 1 log          ← P0-3 Round 1 đóng hoàn toàn
industry_taxonomies        : 6 bản ghi
credentials_data parity PG vs SQLite : True ← P0-4 giữ nguyên trạng thái ĐẠT
```

### 🟢 Blocker ② — P0-6 Key Isolation: **ĐẠT**

Tấn công thử bằng **mọi** công thức tĩnh suy được từ source public:

```
IGNIS_ENCRYPTION_KEY set? False
algorithm label: Fernet-AES128-CBC
  sha256(DATABASE_URL) : không giải mã được ✓
  sha256(default DSN)  : không giải mã được ✓
  sha256(default salt) : không giải mã được ✓

Khóa giữa 2 process khác nhau:
  process 1: S2zZEv4gZKo6f-T_…
  process 2: ja9Swl44gXtulfYI…
```

Cơ chế `sha256(DATABASE_URL)` đã bị loại bỏ hoàn toàn. `_EPHEMERAL_KEY` cache module-level nên nhất quán trong một process, random giữa các process. Và điều tôi nhấn ở Round 2 — **warning giờ mô tả đúng bản chất**:

> *"CRITICAL SECURITY WARNING: … Generated a random ephemeral in-memory key for this process lifetime. Stored encrypted credentials will NOT be decryptable across process restarts until IGNIS_ENCRYPTION_KEY is set."*

Nói rõ hệ quả vận hành (session không persist) thay vì che nó bằng từ "ephemeral" cho một khóa tất định. Đây là cách xử lý đúng.

*Còn lại (P1, không chặn release)*: passphrase do user cung cấp vẫn `sha256` không salt/không KDF (`crypto.py:31-33`) — nên dùng `scrypt`; `config.py:27` description vẫn ghi `"Fernet AES-256 secret key"`, lệch với nhãn mới.

### 🟡 Blocker ③ — P0-7 Noise Blacklist: **ĐẠT trên đường chính, HỞ 2 đường**

**Phần đã làm đúng và tôi xác nhận hiệu quả:**
- Seed 22 term vào `sql/004_global_lexicons.sql` domain `noise_blacklist` ✓
- MCP tool `register_noise_blacklist` (`server.py:1177`) ✓
- `_sync_lexicons_from_db()` (`server.py:150`) phân loại đúng 3 nhóm, được gọi từ **5 handler** (dòng 184, 242, 270, 469, 553) ✓
- `AutonomousDiscoveryUseCase` nạp `get_domain_lexicons(domain="noise_blacklist")` (`:89-93`) ✓

Kiểm chứng qua production path:
```
=== Đường MCP (_sync_lexicons_from_db) ===
  [Postgres] noise nạp được=22   chặn 4/4   => ĐẠT ✓
  [SQLite  ] noise nạp được= 0   chặn 0/4   => CHƯA ĐẠT ✗
```

**Hở thứ nhất — SQLite không được seed.** `noise_blacklist` chỉ thêm vào `sql/`, không thêm vào `sqlite_repository._create_tables_and_seed()`. Hệ quả: **chế độ Zero-Docker SQLite vẫn không có filter noise nào** — đúng trạng thái Round 2. Đây là **cùng một lớp lỗi với P0-4 của Round 1**: vá một backend, quên backend kia. Và là chính xác lớp lỗi mà "contract test dùng chung cho `ITrendRepository`" — đề xuất từ Round 1, vẫn chưa làm — sẽ bắt được ngay.

**Hở thứ hai, nghiêm trọng hơn — `refinement_orchestrator` có bộ nạp riêng và nó ĐẢO NGƯỢC ý định.**

`refinement_orchestrator.py:53` vẫn giữ logic cũ:
```python
pos_terms = [item["term"] for item in db_lexicons if item.get("domain") != "foreign_stopwords"]
```
Bộ lọc `!= "foreign_stopwords"` **không loại `noise_blacklist`** → toàn bộ 22 noise term được `register_terms()` vào **lexicon TÍCH CỰC**, tức là kho từ dùng làm *bằng chứng nội dung là tiếng Việt bản địa*:

```
=== Đường refinement_orchestrator ===
  [Postgres] chặn 0/4  | noise LỌT vào lexicon TÍCH CỰC: ['fyp','funny','haihuoc','dance','troll']

Hệ quả:
  is_vietnamese('funny dance')      = True   ← nội dung rác được xác nhận là VN bản địa
  is_vietnamese('troll vlog music') = True
  is_vietnamese('fyp duet')         = True
```

Đây **tệ hơn** trạng thái Round 2: trước đây noise chỉ *không bị lọc*; giờ nó *được tính là bằng chứng bản địa hóa*, thổi `language_precision` và `vn_count` → thổi `supply_score`. Và vì `_evaluator`/`_reasoner` là **singleton process-wide** (P1-2 Round 1, chưa fix), ô nhiễm này lan sang mọi mission tiếp theo trong cùng process — kể cả những mission đi qua đường MCP đã đúng.

Đường thực thi cụ thể: `handle_run_autonomous_research_mission` gọi `_sync_lexicons_from_db` (đúng, dòng 184) **rồi** gọi `run_mission_harness()` chạy bộ nạp riêng (sai, dòng 52) → bộ sai ghi đè lên bộ đúng.

**Fix (30 phút, 2 việc)**:
1. `refinement_orchestrator.py:53` → `not in ("foreign_stopwords", "noise_blacklist")` + thêm nhánh `register_noise_blacklist`. Tốt hơn: xóa bộ nạp trùng lặp này, dùng chung một helper với `_sync_lexicons_from_db`.
2. Seed `noise_blacklist` vào `sqlite_repository._create_tables_and_seed()`.

---

## 2. Các fix khác trong Round 3

| Mục | Phán quyết | Bằng chứng |
|---|---|---|
| **Cache aliasing** (`youtube_plugin`) | 🟢 **ĐẠT** | clone thật, metadata dict riêng, cache sạch sau khi caller mutate |
| **Metadata isolation** (`quality_evaluator`) | 🟢 **ĐẠT** | `sig.metadata is not original_meta` |
| **`DISCOVERY_INTERVAL_HOURS`** | 🟢 **ĐẠT** | `settings.DISCOVERY_INTERVAL_HOURS * 3600`; bỏ `__dict__.get()` |
| **PII redaction** | 🟡 **ĐẠT một phần** | phone/email redact ✓, `comment_id` pseudonymize ✓, salt ✓ — nhưng salt là hằng số public |
| **Regression suite** | 🟡 **ĐẠT hình thức, 3/4 test không kiểm được điều nó hứa** | xem mục 3 |
| **Tiếng Anh 100%** | 🔴 **CHƯA ĐẠT** | 136 dòng tiếng Việt còn lại trong `src/` |

**Cache aliasing — verify chi tiết** (Round 2 tôi reproduce được nhiễm chéo, giờ hết):
```
cache hit trả về 1 signal
cùng object với cache? False   ← đã clone ✓
metadata cùng dict?    False   ← dict riêng ✓
object TRONG CACHE sau khi caller gán mission_id + metadata['polluted']:
  mission_id = None            ← sạch ✓
  metadata   = {'video_id': 'v1'}   ← sạch ✓
```

**PII — còn 3 điểm hở:**
1. **`salt = "ignis_salt_2026"` là hằng số hardcode trong source public** (`tiktok_plugin.py:392`). Đây không phải salt bí mật. GDPR Điều 4(5) đòi pseudonymization phải dùng "thông tin bổ sung **được giữ riêng biệt**" — một hằng số trong repo public không đáp ứng. Hash truncate 4–8 hex + salt công khai → rainbow table cho danh sách handle TikTok phổ biến là khả thi. Fix: `hmac.new(key=IGNIS_ENCRYPTION_KEY, msg=handle, digestmod=sha256)`.
2. **Handle creator vẫn lưu nguyên** — `_parse_json_item` (`:25-26` trong hàm) vẫn ghi `"author": author_id` và `"author_name": nickname` **thật** vào `trend_signals.metadata`, persist vào DB và render vào HTML report do nginx serve. Chỉ *người bình luận* được bảo vệ, *nhà sáng tạo* thì không. (Phát hiện Round 2 #2, chưa xử lý.)
3. Regex `\b\d{10,11}\b` sẽ redact nhầm mọi số 10–11 chữ số — kể cả `view_count`, ID video TikTok (19 số nên an toàn), mã đơn hàng. False positive vô hại nhưng làm nhiễu dữ liệu Voice-of-Customer.

**Tiếng Anh — 136 dòng còn lại**, phân bố:
```
29  tiktok_plugin.py        23  youtube_plugin.py       20  registry.py
18  refinement_orchestrator 11  mcp/server.py            9  creative_center_plugin
 6  strategic_reasoner       6  quality_evaluator        5  postgres_repository
```
Đáng chú ý không phải số lượng, mà là **`youtube_plugin.py:41-51` chứa 37 pattern rác hardcode tiếng Việt** (`GARBAGE_PATTERNS`: `bóng đá`, `tổng tài`, `phim ngắn`, `truyện audio`, `phone farm`…) — đúng loại hardcode mà claim P0-7 nói *"đã xóa sạch mọi keyword/mảng hardcode"*. Nó nằm ngoài `harness/` nên đợt refactor bỏ qua, nhưng **vẫn đang chạy** ở đường ingress YouTube và **không có tham số geo** → áp nghiệp vụ thị trường VN cho mọi thị trường:
```
số pattern: 37
_is_garbage('Drama tổng tài phim ngắn') = True   (không có tham số geo)
```
Đây là chỗ `noise_blacklist` động đáng lẽ phải thay thế. (`_enrich_keyword` thì **đúng** — có guard `if geo == GeoCode.VN` ✓.)

---

## 3. Chất lượng bộ Regression Suite — điểm cần nói thẳng

`tests/unit/test_round2_regressions.py` — 4/4 pass. Nhưng tôi đã cảnh báo về test-shape ở cả Round 1 và Round 2, nên phải soi kỹ: **3/4 test không kiểm được điều mà tên và docstring của nó hứa.**

### 🔴 `test_dynamic_noise_blacklist_rejection` — vẫn đúng lỗi test-shape cũ

```python
    evaluator = QualityEvaluator()
    evaluator.register_noise_blacklist(["fyp", "xuhuong", "haihuoc", ...])   # hardcode trong test
```
Gọi API **trực tiếp** với danh sách hardcode, **không** đi qua `repository → get_domain_lexicons → register`. Bằng chứng nó vô dụng: test này **xanh 100%** trong khi tôi vừa chứng minh 2 trong 3 đường production chặn **0/4**. Test đang chứng minh "hàm `register_noise_blacklist` hoạt động" — điều chưa bao giờ có ai nghi ngờ — chứ không phải "production lọc được noise", là điều thực sự cần bảo vệ.

Fix: fixture `SqliteTrendRepository(':memory:')` có seed noise → gọi `run_mission_harness()` hoặc `_sync_lexicons_from_db()` → assert. Test đó sẽ **đỏ ngay hôm nay**, và đó chính là giá trị của nó.

### 🔴 `test_crypto_ephemeral_key_security` — pass y nguyên trên code Round 2 đã bị bác bỏ

Docstring: *"Verify that unconfigured key uses non-deterministic random ephemeral key."* Nội dung thực tế: encrypt → decrypt roundtrip trong cùng process. **Không assert gì về tính không-tất-định.** Tôi kiểm chứng bằng cách set khóa về đúng cơ chế Round 2:
```
Với khóa TẤT ĐỊNH (cơ chế sha256(DATABASE_URL) của Round 2), test vẫn PASS? True
```
Test này sẽ không phát hiện được nếu ai đó revert P0-6. Fix: assert `sha256(DATABASE_URL)` **không** giải mã được, và 2 lần khởi tạo cho khóa khác nhau — đúng như 2 script tôi chạy ở mục 1.

### 🟡 `test_sql_alphabetical_bootstrap_order` — kiểm quy ước đặt tên, không kiểm SQL chạy được

Docstring nói *"named and ordered such that they execute cleanly"* nhưng test **không execute SQL nào**, chỉ assert prefix `001..005` liên tục. Thêm `006_x.sql` chứa `ALTER TABLE` lên bảng chưa tồn tại → test vẫn pass, container vẫn chết. Nó cũng sẽ **fail sai** với tên hợp lệ như `005b_hotfix.sql`. Giá trị thực: chặn được đúng một lỗi cụ thể (đặt tên không có prefix số) — hữu ích nhưng không phải regression test cho Blocker ①.

Fix đúng: test integration với Postgres service container trong CI, dựng schema từ `sql/*.sql` theo thứ tự alphabet rồi CRUD — chính là script tôi chạy ở mục 1, mất ~70 giây.

### 🟢 `test_quality_evaluator_metadata_isolation` — test tốt

Assert `sig.metadata is not original_meta` — kiểm đúng bất biến, sẽ đỏ nếu ai bỏ clone. Đây là mẫu mực cho 3 test còn lại.

**Coverage 62%** (không đổi so với Round 2, dù thêm 4 test). Các module rủi ro nhất vẫn thấp nhất: `execute_mission` 20%, `get_mission_analysis` 20%, `refinement_orchestrator` 21% — và **`refinement_orchestrator` chính là nơi chứa lỗi noise-inversion vừa phát hiện**. 21% coverage giải thích tại sao nó thoát khỏi cả 2 đợt vá.

---

## 4. Các phát hiện Round 1/2 chưa xử lý (verify lại từng cái)

| ID | Nội dung | Trạng thái Round 3 |
|---|---|---|
| P0-2 dư | `ã õ ũ` trong `VI_EXCLUSIVE_CHARS` không độc quyền VN | `'Automação n8n'`, `'Configuração da API'`, `'Não perca a criação'` → **True** ✗ |
| P1-2 | Lexicon tích lũy trên singleton, không bao giờ xóa | chưa fix — là chất xúc tác cho lỗi noise-inversion |
| P1-4 | Harness/discovery không `delete_mission_signals` | chỉ `execute_mission.py:65` có |
| P1-6 | Shortcode trùng → SQLite xóa mất mission cũ | chưa fix |
| P1-7 | Shortcode tiếng Việt | `'Xu hướng AI Agent…'` → `VN-XU-H-7D-01` |
| P1-11 | `language_precision` sai mẫu số | 3 video VN + 1 Google signal → **75.0%** |
| P1-12 | `geo != VN` luôn 100% | tiêu đề tiếng Bồ, `geo=US` → **100.0** |
| P1-13 | `captured_at` hai ngữ nghĩa, chưa có `published_at` | chưa fix |
| P1-14 | `evaluate_quality` không nhận `timeframe_days` | chưa fix |
| P1-15 | View skew bắn nhầm khi n=1 | vẫn flag |
| P1-19 | 429/403 ở TikTok/Threads/Reels | `grep` → không có |
| P1-23 | `is_healthy()` cứng `True` | 4/4 connector scraper |
| P1-27 | Restart chạy discovery ngay | `_last_discovery_time = 0.0` |
| P2-1 | application → infrastructure | 7 import (5 + 1 + 1) |
| P2-14 | Reports split-brain | `parents[3]` vs `parents[4]` |
| P3-11 | README "15 FastMCP Tools" | thực tế **28** |

Ghi nhận công bằng: đội chỉ cam kết 3 Blocker + 3 nhóm fix, không cam kết nhóm này.

---

## 5. PHÁN QUYẾT CUỐI

# 🟡 SẴN SÀNG RELEASE `v0.1.0-beta` SAU 30 PHÚT SỬA

Đây là lần đầu tôi không đưa phán quyết chặn. Lý do: **cả 3 Blocker chặn release của Round 2 đều đã đóng**, và đóng đúng cách — không phải sửa nhãn, mà sửa cơ chế. Tôi đã chạy lại chính xác những test đã fail và chúng xanh:

| | Round 2 | Round 3 |
|---|---|---|
| Postgres initdb | `Exited (3)`, 0 bảng | **`Up`, 7/7 bảng, 0 error** |
| Khóa mã hóa | giải mã được bằng khóa tự suy | **3/3 công thức tĩnh thất bại, random mỗi process** |
| Noise filter (đường MCP/PG) | 0/4 | **4/4** |
| Cache aliasing | nhiễm chéo mission | **cache sạch sau mutate** |
| Working tree | dirty, 70/71 | **clean, 75/75, ruff 0 error** |

P0-3 Round 1 giờ đóng hoàn toàn với bằng chứng CRUD thật. P0-6 xử lý đúng cả về cơ chế **và** về tính trung thực của thông báo. Chất lượng bản vá lần này khác hẳn Round 2.

### Hai việc phải sửa trước khi tag (30 phút)

**① `refinement_orchestrator.py:53` — noise-inversion.** Đây là việc duy nhất tôi coi là chặn, vì nó không chỉ "chưa fix" mà **đảo ngược** ý định của chính bản vá vừa làm: 22 noise term được đăng ký làm bằng chứng bản địa hóa, rồi lan qua singleton sang mọi mission sau. Một dòng sửa `!=` → `not in (...)`, cộng nhánh `register_noise_blacklist`. Tốt nhất là xóa bộ nạp trùng lặp và dùng chung helper.

**② Seed `noise_blacklist` vào `sqlite_repository`.** Không sửa thì chế độ Zero-Docker — điểm bán hàng khác biệt của sản phẩm — vẫn không có filter noise. Đúng lớp lỗi P0-4 Round 1.

### Nên làm trong tuần đầu sau release

**Ưu tiên 1 — chữa 3 test giả tạo cảm giác an toàn** (`test_dynamic_noise_blacklist_rejection`, `test_crypto_ephemeral_key_security`, `test_sql_alphabetical_bootstrap_order`). Đây là việc quan trọng nhất trong danh sách, không phải vì bug hôm nay, mà vì: **cả hai lỗi tôi vừa tìm thấy đều nằm trong vùng mà bộ test đang báo "đã được bảo vệ"**. Test xanh mà production hỏng là cơ chế đã để P0-7 sống qua 2 đợt vá. Cụ thể: đưa 3 test đi qua repository/production path, và thêm 1 test integration Postgres trong CI (~70s, dùng service container).

**Ưu tiên 2 — nâng coverage cho 3 module rủi ro nhất**: `refinement_orchestrator` (21%), `execute_mission` (20%), `get_mission_analysis` (20%). Đặt `--cov-fail-under=62` ngay để không tụt.

**Ưu tiên 3 — PII trước khi có traffic thật**: HMAC với `IGNIS_ENCRYPTION_KEY` thay salt hằng số; pseudonymize handle creator; siết regex `\d{10,11}`.

**Ưu tiên 4 — hoàn tất decoupling**: `youtube_plugin.GARBAGE_PATTERNS` (37 pattern VN hardcode, không geo-guard) chuyển sang `noise_blacklist` động — đây là phần còn lại của chính claim P0-7. Kèm 136 dòng tiếng Việt còn lại.

**Ưu tiên 5 — nhóm thống kê P1-11 → P1-15**: `language_precision` sai mẫu số, `geo != VN` luôn 100%, `data_freshness_score` (trọng số cao nhất 30%) vẫn gần như hằng số. Nhóm này ảnh hưởng trực tiếp tới độ tin của con số mà khách hàng nhìn thấy — cần xử lý trước khi ai đó ra quyết định kinh doanh dựa trên nó.

### Ghi chú về nhãn phiên bản

Đề nghị tag `v0.1.0-beta` chứ không phải `v0.1.0`: `pyproject.toml` đã ghi `Development Status :: 4 - Beta`, coverage 62% với 3 module cốt lõi dưới 25%, và nhóm P1 thống kê chưa xử lý. Nhãn beta cho phép launch Product Hunt một cách trung thực, và tránh cam kết ổn định API mà codebase chưa có test để giữ.
