# fn-ignis — Round 2 Audit: Báo cáo Nghiệm thu Bản vá

- **Ngày**: 02/09/2026 · **HEAD**: `402cb5b` (main & develop cùng trỏ) · **Baseline**: Round 1 @ `c8f954c`
- **Diff**: 59 file, +1.087 / −320 dòng
- **Phương pháp**: mọi kết luận đều **reproduce bằng thực nghiệm** — dựng Postgres thật (`timescale/timescaledb-ha:pg16`) chạy `sql/` qua `/docker-entrypoint-initdb.d`, CRUD thật qua repository, script kiểm chứng từng hàm, ruff + pytest + coverage.

## ⚠️ Cảnh báo trước khi đọc: HEAD ≠ working tree

`git status` cho **16 file `src/` đang modified, chưa commit** (đợt dịch docstring/message VI→EN đang dở). Điều này tạo hai kết quả khác nhau và ảnh hưởng trực tiếp tới phán quyết release:

| | ruff | pytest |
|---|---|---|
| **HEAD `402cb5b`** (đã verify bằng `git stash`) | All checks passed ✓ | **71/71 pass** ✓ |
| **Working tree hiện tại** | All checks passed ✓ | **70/71 — 1 FAILED** ✗ |

Test fail: `test_crypto.py::test_decrypt_with_wrong_key_fails` — message trong `crypto.py` đã dịch thành `"Failed to decrypt credentials"` nhưng test vẫn assert regex `"Không thể giải mã"`. Đây là hệ quả cơ học của đợt dịch chưa hoàn tất, không phải lỗi logic.

**Kết luận về claim của đội**: "71/71 pass" **ĐÚNG với HEAD**. Nhưng không thể release một working tree dirty có test đỏ — cần commit hoặc revert đợt dịch, và sửa test kèm theo trong cùng commit.

---

## 1. Nghiệm thu 7 lỗi P0

| ID | Phán quyết | Bằng chứng |
|---|---|---|
| **P0-1** Macro Scan `AttributeError` | 🟡 **ĐẠT một phần** | Crash hết, `exc_info=True` có. Nhưng blacklist bị **xóa** chứ không chuyển sang class attr/DB → mất chức năng lọc hashtag generic |
| **P0-2** Xung đột lexicon | 🟢 **ĐẠT** | Giao 2 tập = rỗng; 5/5 câu VN không dấu → `True`; 5/5 câu ngoại → `False`; **supply_score 0.0 → 52.9** |
| **P0-3** Schema Postgres | 🔴 **CHƯA ĐẠT** | Nội dung SQL đúng, nhưng **container init `Exited (3)`, 0 bảng** — regression nặng hơn Round 1 |
| **P0-4** Contract credentials | 🟢 **ĐẠT** | `credentials_data` khớp 100% giữa 2 backend, alias `credentials` giữ nguyên |
| **P0-5** Quota re-raise | 🟢 **ĐẠT** | Re-raise ở cả 2 điểm, cache chỉ ghi khi `if kw_signals`, không double-append |
| **P0-6** Khóa mã hóa | 🔴 **CHƯA ĐẠT** | Chỉ sửa nhãn. Khóa **vẫn** `sha256(DATABASE_URL)` — đã giải mã lại được ciphertext bằng khóa tự suy |
| **P0-7** Dynamic decoupling | 🔴 **CHƯA ĐẠT** | `register_noise_blacklist` **vẫn chỉ được gọi từ test**. 4/4 tiêu đề hài nhảm không bị lọc |

**Tổng: 3 ĐẠT · 1 ĐẠT một phần · 3 CHƯA ĐẠT.**

---

### 🟢 P0-2 — ĐẠT, và đây là bản vá quan trọng nhất của đợt này

```
FOREIGN ∩ VI_CORE  : CLEAN ✓        FOREIGN ∩ TECHLOAN : CLEAN ✓
'Huong dan cai dat n8n tu dong hoa'      -> True  ✓   (Round 1: False)
'Tutorial AI agent cho nguoi Viet'       -> True  ✓   (Round 1: False)
'huong dan tu dong hoa cho doanh nghiep' -> True  ✓   (Round 1: False)
```

Quan trọng hơn cả việc hàm trả đúng: **bản vá đã lan truyền đúng xuống Opportunity Index**. So sánh cùng một input (demand 90, 5 video Việt không dấu):

| | Round 1 | Round 2 |
|---|---|---|
| `vn_count` | 0 | 5 |
| `supply_score` | 0.0 | **52.9** |
| nhãn | `UNVERIFIED_DEMAND_GAP` | `GROWING_OPPORTUNITY` |

Không có false positive mới: 5/5 câu Pháp/Bồ/Indonesia vẫn bị loại đúng. Việc gỡ `dan`/`ini`/`dari` khỏi `FOREIGN_STOPWORDS` **không** làm rò rỉ tiếng Indonesia — Layer 3 (cần ≥2 từ lõi Việt) vẫn chặn được (`'Ini adalah agen AI terbaru'` → False ✓).

**Còn dư một lỗ (P1, chưa fix)**: `VI_EXCLUSIVE_CHARS_PATTERN` chứa `ã`, `õ`, `ũ` — **không** độc quyền tiếng Việt (comment trong code ghi *"cannot appear in Portuguese, French, Spanish"* là sai sự thật). Layer 2 return `True` chỉ với 1 ký tự như vậy:

```
'Automação n8n'        -> True  ✗ (tiếng Bồ)
'Configuração da API'  -> True  ✗ (tiếng Bồ)
```

Chỉ thoát khi câu có kèm stopword. Nội dung AI/automation tiếng Bồ (Brazil) rất nhiều trên YouTube/TikTok đúng ngách này → bị tính là "đã bản địa hóa", thổi `language_precision` và `vn_count`. Fix: bỏ `ã õ ũ` khỏi pattern (`ạ ẹ ị ọ ụ ả ẻ ỉ ỏ ủ ơ ư đ` mới thật độc quyền và đã phủ gần như mọi câu Việt có dấu), hoặc yêu cầu ≥2 ký tự exclusive.

---

### 🔴 P0-3 — CHƯA ĐẠT: nội dung đúng, nhưng deploy Postgres **không boot được**

Nội dung bản vá **đúng và đã verify bằng CRUD thật**:

```
create_mission (PG)        : ĐẠT ✓   shortcode = VN-XU-H-7D-F652
get_mission by UUID        : ĐẠT ✓
get_mission by shortcode   : ĐẠT ✓
get_mission by session_id  : ĐẠT ✓
audit log ghi + đọc        : ĐẠT ✓ (1 log)
```

**Nhưng**: `sql/005_audit_logs_and_mission_columns.sql` sắp alphabet **trước** `sql/init.sql`. Postgres chạy `/docker-entrypoint-initdb.d` theo alphabet:

```
1. 002_platform_credentials.sql
2. 003_market_lexicons.sql
3. 004_global_lexicons.sql
4. 005_audit_logs_and_mission_columns.sql   ← ALTER TABLE research_missions
5. init.sql                                  ← CREATE TABLE research_missions
```

Thực nghiệm A/B trên chính image family mà `docker-compose.prod.yml` dùng:

| Test | `sql/` | Kết quả |
|---|---|---|
| **A** | như hiện tại | `ERROR: relation "research_missions" does not exist` → container **`Exited (3)`** → **0 bảng** |
| **B** | chỉ đổi tên `init.sql` → `001_init.sql` | container **`Up`** → **7/7 bảng** (`industry_taxonomies, market_lexicons, platform_credentials, research_missions, system_audit_logs, topic_clusters, trend_signals`) |

Round 1: "thiếu cột". Round 2: "container không khởi động". **Mức độ nghiêm trọng tăng** — trước còn tạo được bảng và fail ở lúc gọi API, giờ fail ngay initdb.

Đây là điểm tôi đã nêu trong Round 1 dưới mục *"Bonus cùng file: `init.sql` sắp thứ tự alphabet sau `004_*.sql` → đổi tên thành `001_init.sql`"* — phần bonus không được xử lý, và chính việc thêm `005` đã kích hoạt nó.

**Fix: một dòng.**
```bash
git mv sql/init.sql sql/001_init.sql
```
Sau đó `005` trở thành redundant cho fresh install (init.sql đã có 3 cột) nhưng vẫn cần cho DB đang chạy — giữ lại, vô hại vì `IF NOT EXISTS`.

**Kèm theo — blocker deploy thứ hai**: `docker-compose.prod.yml:3` ghi `timescale/timescaledb-ha:pg16-latest`. Tag này **không còn tồn tại trên Docker Hub**:
```
Error response from daemon: failed to resolve reference
  "docker.io/timescale/timescaledb-ha:pg16-latest": not found
```
Tag khả dụng: `pg16`, `pg16-ts2.29`, `pg16.14-ts2.29.2`, `pg16-oss`… Nghĩa là `docker compose -f docker-compose.prod.yml up` **fail ngay ở bước pull**, trước cả khi tới SQL. Nên pin tag cụ thể (`pg16.14-ts2.29.2`) để build reproducible.

---

### 🔴 P0-6 — CHƯA ĐẠT: sửa nhãn, không sửa lỗ hổng. Warning còn mô tả sai bản chất

Đã sửa: nhãn `"Fernet-AES128-CBC"` ✓, docstring `generate_new_key` ✓, có log cảnh báo ✓.

**Không sửa** — `crypto.py:17-18` nguyên xi so với Round 1:
```python
    if not raw_key:
        logger.warning("SECURITY WARNING: ... Using ephemeral fallback key. ...")
        derived = hashlib.sha256((settings.DATABASE_URL or "fn-ignis-default-salt").encode()).digest()
        raw_key = base64.urlsafe_b64encode(derived).decode()
```

Thực nghiệm — mã hóa qua API của app, rồi giải mã bằng khóa **tự suy theo công thức trong source**:
```
IGNIS_ENCRYPTION_KEY đã set? False
Giải mã bằng sha256(DATABASE_URL): {'cookies': [{'name': 'sessionid', 'value': 'SECRET_cookie'}]}
=> XÁC NHẬN: khóa TẤT ĐỊNH = sha256(DATABASE_URL). KHÔNG phải ephemeral.
```

Hai vấn đề, và cái thứ hai đáng lo hơn:

1. **Lỗ hổng còn nguyên.** Với repo public + `DATABASE_URL` có default hardcoded ở `config.py:14`, khóa mặc định là hằng số ai cũng tính ra. Session cookie TikTok trong DB ≈ plaintext.
2. **Warning nói sai sự thật.** "ephemeral" hàm ý khóa tạm, sinh ngẫu nhiên, không ai đoán được. Thực tế nó **tất định và suy ra được từ repo**. Một dev đọc warning này sẽ kết luận "chỉ là bất tiện, session không persist" và bỏ qua — trong khi bản chất là "DB của bạn ai cũng giải mã được". **Log gây hiểu sai còn tệ hơn không log**, vì nó tạo cảm giác đã được thông báo và đánh giá rủi ro.

Chưa fix kèm: SHA256 không salt/không KDF cho passphrase user (`:22`), silent plaintext downgrade khi thiếu cờ `_encrypted` (`:59-60`), và `config.py:27` vẫn ghi description `"Fernet AES-256 secret key"` — mâu thuẫn với nhãn mới.

**Fix đúng: fail-fast.** Không suy khóa từ connection string trong bất kỳ hoàn cảnh nào.
```python
    if not raw_key:
        raise ValueError(
            "IGNIS_ENCRYPTION_KEY chưa được cấu hình. Sinh khóa mới:\n"
            "  python -c \"from ignis.infrastructure.auth.crypto import generate_new_key; print(generate_new_key())\""
        )
```
Nếu bắt buộc phải có fallback không-chặn-luồng thì dùng `Fernet.generate_key()` thật (ephemeral đúng nghĩa, mất sau restart) và nói rõ trong warning là **session sẽ không persist**.

---

### 🔴 P0-7 — CHƯA ĐẠT: không dịch chuyển 1 li so với Round 1

Claim của đội: *"Đã xóa sạch mọi keyword/mảng hardcode… toàn bộ từ khóa loại trừ đều nạp động qua database / mission params."*

Phần **"xóa"** đã làm. Phần **"nạp động"** thì chưa — và đó chính là nội dung nguyên văn của phát hiện P0-7 Round 1.

```
register_noise_blacklist  ->  chỉ 2 nơi gọi, đều trong tests/unit/test_agent_harness.py:204-205
MCP tool cho noise        ->  không có
nhánh nạp noise từ DB     ->  không có (chỉ phân loại foreign_stopwords vs pos_terms)
domain noise trong DB     ->  không có
   market_lexicons: ['common_vi','ecommerce','fashion','foreign_stopwords','tech']
```

Chạy đúng production path (nạp lexicon y như `refinement_orchestrator` làm) rồi thử lọc:
```
_is_garbage=False  is_vietnamese=True   'Hài kịch #funny #haihuoc cười sảng'
_is_garbage=False  is_vietnamese=True   'Nam thần kinh tập 12 #namthầnkinh'
_is_garbage=False  is_vietnamese=True   'Phim hài tiểu phẩm gia đình'
_is_garbage=False  is_vietnamese=True   'Reaction mukbang ăn uống'
```

`_custom_noise` rỗng vĩnh viễn → `_is_garbage()` chỉ còn chặn ký tự non-Latin. Toàn bộ khả năng lọc nội dung hài nhảm viral **vẫn không tồn tại trong runtime**. Test `test_agent_harness.py:204` vẫn pass vì gọi thẳng API — **vẫn là lỗi test-shape y như Round 1**: test mock đúng thứ production không bao giờ làm.

Điểm sáng đã có: `FOREIGN_SCRIPTS_PATTERN` mới hoạt động tốt — Hàn/Trung/Nhật/Thái đều bị loại đúng (3/3).

**Fix (4 việc, không thể bỏ việc nào)**:
1. Seed domain `noise_blacklist` vào `market_lexicons` (khôi phục danh sách đã xóa) — cả `sql/` và SQLite seed.
2. Map nó vào `register_noise_blacklist()` ở **cả hai** chỗ nạp lexicon (`refinement_orchestrator.py:52-60`, `autonomous_discovery.py:193-201`).
3. Thêm MCP tool `register_noise_blacklist(terms)` + đưa vào Step 1 của SOP.
4. Sửa test đi qua production path (`run_mission_harness` với DB có seed noise), không gọi thẳng API.

---

### 🟡 P0-1 — ĐẠT về crash, nhưng cách fix làm mất chức năng

Đã đúng: `self.GENERIC_HASHTAG_BLACKLIST` gỡ hết, `exc_info=True` thêm vào (`autonomous_discovery.py:101`). Macro Scan giờ **chạy được thật** — đây là điều quan trọng nhất.

Nhưng cách fix là **xóa hẳn** blacklist thay vì đưa lên class attribute:
```python
                for item in macro_trends:
                    tag = item.get("hashtag", "").replace("#", "").strip().lower()
                    if tag and tag not in macro_keywords:      # không còn filter generic
                        macro_keywords.append(tag)
```
Hệ quả: hashtag rác generic (`fyp`, `xuhuong`, `trending`, `dance`, `haihuoc`, `capcut`) giờ **đi thẳng** vào `macro_keywords` → `mission.keywords` → deep ingress. Trước đây lỗi khiến nó rơi vào fallback nên vô tình "an toàn"; giờ nó chạy nhưng không lọc gì. Cộng với P0-7 chưa xử lý, không có tầng nào chặn.

Và mâu thuẫn với chính claim P0-7 — **2 chỗ hardcode còn nguyên** trong `autonomous_discovery.py`:
```
:95   industry="Tech & Electronics"                                          # cứng 1 ngành
:108  macro_keywords = ["ai agent","chatbot","automation","ecommerce","tiktok shop"]
```

Fix: chuyển blacklist + industry + fallback keywords sang DB/mission params, đúng như tinh thần P0-7.

---

## 2. Tuân thủ & Bảo mật

### 🟡 PII pseudonymize — ĐẠT một nửa

**Đã làm đúng** (`tiktok_plugin.py:397-405`): tác giả bình luận được pseudonymize (`Ng***_d25b`), có comment dẫn chiếu Luật 91/2025/QH15 & GDPR.

**Bốn lỗ còn lại** — theo thứ tự mức độ:

1. **Nội dung comment không hề được redact.** `grep` không thấy bất kỳ xử lý số điện thoại/email nào. Trong ngữ cảnh thương mại VN, comment tự chứa PII rất thường xuyên ("inbox mình 09xx…", "zalo 03xx", email). `customer_inquiries` được render vào HTML digest mà **nginx serve công khai** (`docker-compose.prod.yml:44-45`). Đây là rủi ro lớn hơn cả tên tác giả, vì pseudonymize tên rồi để nguyên số điện thoại trong text là vô nghĩa.
2. **Handle creator không pseudonymize.** `_parse_json_item:573-574` vẫn lưu `"author": author_id` và `"author_name": nickname` **thật** vào `trend_signals.metadata` → persist vào DB và render vào report. Chỉ *commenter* được bảo vệ, *creator* thì không.
3. **`comment_id` (cid) giữ nguyên** (`:403`) — là identifier trỏ trực tiếp tới comment gốc trên TikTok, re-identify được ngay lập tức. Pseudonymize author mà giữ cid thì không đạt mục đích.
4. **Hash không salt.** `sha256(nickname)` không salt/không HMAC → rainbow table trivial. Theo GDPR Điều 4(5) và Recital 26, pseudonymization phải "không thể attribute lại mà không có thông tin bổ sung được giữ riêng" — hash không khóa **không đạt**, dữ liệu vẫn là PII. Thêm nữa giữ 2 ký tự đầu (`Ng***`) + 4 hex làm tăng khả năng re-identify.

**Fix**: `hmac.new(key=IGNIS_ENCRYPTION_KEY, msg=handle).hexdigest()[:10]` không giữ prefix; hash cả `comment_id`; pseudonymize creator handle; thêm regex redact SĐT/email trên `text`; và cờ `IGNIS_STORE_AUTHOR_IDENTIFIERS=false` làm default.

### 🟢 Dependencies & Config — phần lớn ĐẠT

| Mục | Phán quyết |
|---|---|
| `cachetools>=5.5.0` trong `dependencies` | 🟢 **ĐẠT** |
| `pytest-cov>=6.0.0` trong `dev` | 🟢 **ĐẠT** |
| `SCHEDULER_INTERVAL_SECONDS` trong `config.py` | 🟢 **ĐẠT** — verify env đọc được: đặt `=60` → nhận `60` |
| `PostgresTimescaleRepository` annotation chưa import | 🟢 **ĐẠT** — đã xóa sạch (0 occurrence) |
| `google-api-python-client` không dùng | 🔴 **CHƯA ĐẠT** — vẫn khai báo, `grep` vẫn 0 usage |
| `DISCOVERY_INTERVAL_HOURS` | 🔴 **CHƯA ĐẠT — setting chết mới** |

**Chi tiết `DISCOVERY_INTERVAL_HOURS`** — fix nửa vời tạo bug mới:
```python
# config.py:32
    DISCOVERY_INTERVAL_HOURS: int = Field(default=24, ...)      # khai báo tên HOURS
# scheduler.py:174
    discovery_interval = int(settings.__dict__.get("DISCOVERY_INTERVAL_SECONDS", 43200))  # đọc tên SECONDS
```
Thực nghiệm với `DISCOVERY_INTERVAL_HOURS=6`:
```
SCHEDULER_INTERVAL_SECONDS đọc được từ env : 60      ✓
DISCOVERY_INTERVAL_SECONDS (scheduler đọc) : MISS -> luôn fallback 43200
DISCOVERY_INTERVAL_HOURS (config khai báo)  : 6      <- KHÔNG ai đọc
```
Ba lỗi cộng dồn: tên không khớp, **đơn vị không khớp** (hours vs seconds), và `settings.__dict__.get()` che mất lỗi — nếu viết `settings.DISCOVERY_INTERVAL_SECONDS` thì đã `AttributeError` ngay lúc chạy. `health_check_interval_seconds` vẫn không có knob nào.

### 🟢 Linter & Test Suite

```
uv run ruff check src/ tests/     ->  All checks passed!            ✓ ĐẠT
uv run pytest tests/ (HEAD)       ->  71 passed                     ✓ ĐẠT
uv run pytest tests/ (worktree)   ->  70 passed, 1 failed           ✗
coverage (đo được lần đầu)         ->  TOTAL 62%
```

Coverage 62% — lần đầu đo được (Round 1 chưa có `pytest-cov`). Các module rủi ro nhất lại thấp nhất:

| Module | Coverage | Ghi chú |
|---|---|---|
| `execute_mission.py` | **20%** | chứa replace-mode không atomic |
| `get_mission_analysis.py` | **20%** | đường dẫn MCP tool chính |
| `refinement_orchestrator.py` | **21%** | harness — trái tim sản phẩm |
| `postgres_repository.py` | **40%** | backend production |
| `creative_center_plugin.py` | **40%** | vừa được "sửa" ở P0-1 |
| `runner.py` / `setup_bundle.py` | **0%** | |
| `quality_evaluator.py` | 93% | tốt |
| `strategic_reasoner.py` | 83% | tốt |

Chú ý: hai module *vừa được vá P0* (`refinement_orchestrator` 21%, `creative_center_plugin` 40%) nằm trong nhóm thấp nhất → bản vá chưa có test bảo vệ. Đề nghị ngưỡng CI: `--cov-fail-under=60` ngay, nâng dần.

---

## 3. Vấn đề mới phát sinh từ chính đợt vá

### 🟠 M1 — `evaluate_quality()` giờ ghi vào object của caller, cộng hưởng với cache aliasing chưa fix

`quality_evaluator.py:189` (tính năng "localization badges" mới):
```python
            s.metadata["is_localized"] = is_loc
```
Thực nghiệm:
```
metadata trước: {}
metadata sau  : {'is_localized': True}   <- read-path ghi vào object của caller
```

Ba hệ quả:
1. `evaluate_quality` được document/dùng như **hàm chấm điểm read-only**, giờ có side effect. Nó bị gọi tới **4 lần/request** (`server.py:227, 257, 458, 533`).
2. **Cộng hưởng với P1-1 Round 1 (cache aliasing) chưa được fix.** Đã reproduce lại: cache YouTube vẫn trả về **cùng instance**:
```
sau mission A, object trong cache có mission_id = A
mission B đọc cache, nhận về CÙNG object? True
object trong cache giờ thuộc            : B
=> P1-1 VẪN CÒN: cache trả về shared mutable instance
```
   Nghĩa là `is_localized` do mission A tính **ghi đè vào object nằm trong cache global**, rồi mission B đọc lại. Nhiễm chéo mission qua một field mới.
3. `is_localized` bị persist vào `trend_signals.metadata` như một side effect của đường đọc — không sai về dữ liệu, nhưng là hành vi ngoài ý định của `get_mission_analysis`.

**Fix**: trả badge trong `QualityScorecard` (hoặc một dict `{signal_index: bool}`) thay vì ghi vào input; đồng thời `copy.deepcopy` ở cache YouTube — tốt nhất là `@dataclass(frozen=True)` cho `TrendSignal` để diệt cả lớp lỗi này.

### 🟢 M2 — Damping mới: kiểm tra lại và ĐẠT

`damping_map = {1: 0.35, 2: 0.55, 3: 0.75, 4: 0.90}`, N≥5 → 1.0. Đơn điệu tăng ✓. Nhãn `PROBE_OPPORTUNITY` mới cho N=1 là xử lý đúng vấn đề "1 mẫu không phải bằng chứng". Nghịch lý xếp hạng Round 1 đã hết:
```
N=0: supply= 0.0  OI=13.5  UNVERIFIED_DEMAND_GAP
N=1: supply=20.4  OI=24.4  PROBE_OPPORTUNITY
N=2: supply=29.0  OI=33.6  GROWING_OPPORTUNITY
N=3: supply=37.1  OI=39.7  GROWING_OPPORTUNITY
N=4: supply=45.1  OI=40.4  GROWING_OPPORTUNITY
N=5: supply=52.9  OI=37.1  GROWING_OPPORTUNITY
```
OI giảm ở N≥5 là **đúng**, không phải nghịch lý: supply thật sự tăng theo số video nên `demand − supply` phải giảm. Damping cho một `raw_oi` cố định vẫn đơn điệu tăng. Và verified (OI 17.1) giờ xếp **trên** unverified (OI 13.5) ✓.

`demand` default khi Google Trends chết đã giảm `65.0 → 50.0` và damping xuống `0.15` (OI 7.5). **Giảm thiệt hại, chưa giải quyết nguyên tắc**: vẫn báo `demand=50/100` khi không có dữ liệu nào. Nên để `None` + flaw trong scorecard.

---

## 4. Các phát hiện Round 1 chưa được xử lý (đã verify lại từng cái)

| ID | Nội dung | Bằng chứng Round 2 |
|---|---|---|
| P1-1 | Cache YouTube trả shared mutable instance | reproduce lại: `cached2[0] is sig -> True` |
| P1-4 | Harness/discovery không `delete_mission_signals` | chỉ `execute_mission.py:65` có |
| P1-6 | Shortcode trùng → SQLite **xóa mất** mission cũ | `save(Alpha)` + `save(Beta)` cùng shortcode → còn **1** mission: `['Mission Beta']` |
| P1-7 | Shortcode tiếng Việt vô nghĩa | `'Xu hướng AI Agent tại Việt Nam'` → `VN-XU-H-7D-01` |
| P1-11 | `language_precision` sai mẫu số | 3 video VN hoàn hảo + 1 signal Google → **75.0%** |
| P1-12 | `geo != VN` luôn 100% | tiêu đề tiếng Bồ, `geo=US` → **100.0** |
| P1-13 | `captured_at` hai ngữ nghĩa | TikTok `now()` (`:589,:674`) vs YouTube publish (`:232,:369`); chưa có `published_at` |
| P1-14 | `evaluate_quality` không nhận `timeframe_days` | 8/8 call site không truyền → luôn 90 ngày |
| P1-15 | View skew bắn nhầm khi n=1 | 1 video → vẫn flag "Severe view distribution skew" |
| P1-19 | 429/403 ở TikTok/Threads/Reels | `grep 429\|403` → **không có kết quả** |
| P1-23 | `is_healthy()` cứng `True` | 4/4 connector scraper vẫn `return True` |
| P1-27 | Restart chạy discovery ngay | `_last_discovery_time = 0.0` (`:50`) |
| P2-1 | application → infrastructure | 7 import y nguyên |
| P2-14 | Reports split-brain | `parents[3]` (`src/reports`) vs `parents[4]` (`reports/`) |
| P2-15 | Error contract MCP | **11/27** handler có try/except |
| P3-11 | README ghi "15 FastMCP Tools" | thực tế **27** |

Ghi nhận công bằng: đội chỉ cam kết xử lý **7 P0 + contract divergences**, không cam kết P1/P2. Bảng này là để hoạch định, không phải để tính là thất hứa.

---

## 5. PHÁN QUYẾT

# 🔴 CHƯA SẴN SÀNG RELEASE

**Tiến bộ là thật và đáng ghi nhận.** P0-2 — lỗi có bán kính ảnh hưởng lớn nhất, làm sụp toàn bộ Opportunity Index — đã được vá đúng, và tôi đã verify nó **lan truyền đúng xuống tận đầu ra** (`supply_score` 0.0 → 52.9, nhãn đổi từ `UNVERIFIED` sang `GROWING_OPPORTUNITY`). P0-4 và P0-5 đạt sạch sẽ. Damping map mới + `PROBE_OPPORTUNITY` là thiết kế tốt hơn tôi đề xuất. Ruff sạch, 71/71 trên HEAD, và lần đầu đo được coverage.

**Nhưng ba việc chặn release, xếp theo thứ tự phải sửa:**

**① Postgres deploy không boot được (P0-3 + tag image).** Đây là chặn tuyệt đối: một user clone repo rồi `docker compose -f docker-compose.prod.yml up` sẽ (a) fail ở pull vì tag `pg16-latest` không tồn tại, và (b) nếu sửa tag thì container `Exited (3)`, 0 bảng. Trải nghiệm onboarding vẫn hỏng ở bước đầu — chính là điều Round 1 đã chỉ ra, giờ ở dạng nặng hơn. **Chi phí sửa: 2 dòng** (`git mv` + pin tag).

**② Hai P0 được đánh dấu "hoàn tất" nhưng lỗ hổng còn nguyên (P0-6, P0-7).** Cả hai chỉ được sửa ở lớp bề mặt — nhãn và việc xóa code — trong khi cơ chế gây lỗi không thay đổi. Với P0-6, warning mới còn **mô tả sai bản chất** ("ephemeral" cho một khóa tất định suy được từ repo), khiến người đọc log đánh giá thấp rủi ro. Với P0-7, `register_noise_blacklist` vẫn chỉ có test gọi — đúng nguyên văn phát hiện Round 1. Đây là điểm tôi muốn nói thẳng: **cả hai đã được báo là ĐẠT trong khi thực nghiệm cho thấy chưa**, và với một dự án security-sensitive sắp public thì sai lệch giữa trạng thái báo cáo và trạng thái thật là rủi ro lớn hơn bản thân hai lỗi.

**③ Working tree dirty với test đỏ.** Không thể tag release từ đây. Commit hoặc revert đợt dịch VI→EN, sửa `test_crypto.py` trong cùng commit.

### Việc phải làm trước khi release (ước lượng nửa ngày)

| # | Việc | File | Effort |
|---|---|---|---|
| 1 | `git mv sql/init.sql sql/001_init.sql` | `sql/` | 1 phút |
| 2 | Pin `timescale/timescaledb-ha:pg16.14-ts2.29.2` | `docker-compose.prod.yml:3` | 1 phút |
| 3 | Fail-fast khi thiếu `IGNIS_ENCRYPTION_KEY`; xóa nhánh `sha256(DATABASE_URL)`; sửa description `config.py:27` | `crypto.py:15-23` | 30 phút |
| 4 | Seed `noise_blacklist` + wire `register_noise_blacklist` ở 2 chỗ nạp lexicon + MCP tool + sửa test đi production path | `sql/`, 2 use case, `server.py`, test | 3 giờ |
| 5 | Commit/revert đợt dịch VI→EN + sửa `test_crypto.py` | 16 file | 30 phút |
| 6 | Bỏ `ã õ ũ` khỏi `VI_EXCLUSIVE_CHARS_PATTERN` + sửa comment sai sự thật | `quality_evaluator.py:19`, `strategic_reasoner.py:51` | 15 phút |
| 7 | Sửa `DISCOVERY_INTERVAL_HOURS`: đổi `scheduler.py:174` đọc đúng tên + chuyển đơn vị; dùng `settings.X` thay `__dict__.get` | `scheduler.py:173-174` | 15 phút |
| 8 | Trả `is_localized` qua scorecard thay vì ghi vào input + `deepcopy` cache YouTube | `quality_evaluator.py:189`, `youtube_plugin.py:264` | 45 phút |
| 9 | Khôi phục filter hashtag generic (nạp từ DB) + đưa `industry`/fallback keywords ra config | `autonomous_discovery.py:95,105,108` | 45 phút |
| 10 | README: 15 → 27 tools | `README.md:78` | 1 phút |

### Nên làm ngay sau release v0.1

- **Regression test cho chính 7 P0** — hiện chưa có test nào bảo vệ chúng. Cụ thể: (a) `assert FOREIGN_STOPWORDS.isdisjoint(VI_CORE_WORDS | TECH_LOAN_WORDS)`, (b) test dựng schema từ `sql/*.sql` theo **đúng thứ tự alphabet** rồi CRUD mission — test này bắt được P0-3-R2 trong 1 giây, (c) test `register_noise_blacklist` qua `run_mission_harness`, (d) test `crypto` raise khi thiếu key.
- **`--cov-fail-under=60`** vào CI, kèm bước `ruff check` (job vẫn tên *"Test & Lint"* mà chưa có bước lint).
- PII: redact SĐT/email trong comment text, HMAC thay SHA256, pseudonymize creator handle + `comment_id`.
- Nhóm P1 thống kê (P1-11 → P1-15): `language_precision` sai mẫu số và `data_freshness_score` (trọng số cao nhất, 30%) vẫn gần như hằng số. Đây là nhóm ảnh hưởng trực tiếp tới độ tin của con số bán ra cho khách.

**Điều kiện nghiệm thu Round 3**: chạy lại đúng 2 test A/B Postgres trong mục P0-3 (yêu cầu container `Up` + 7/7 bảng với `sql/` **không sửa gì**), script kiểm chứng P0-6 không giải mã được bằng khóa tự suy, script P0-7 lọc được 4/4 tiêu đề hài nhảm qua production path, và `git status` sạch với 71/71 pass.
