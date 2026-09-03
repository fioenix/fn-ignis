# Independent Architectural & Launch Readiness Review

**Repo:** `fioenix/fn-ignis` · **HEAD:** `009cc08` = `origin/main` · **Tag:** `v0.1.0`, `v0.1.0-beta` (cả hai trỏ HEAD)
**Working tree:** clean ✓ · **Ruff:** `All checks passed!` ✓ · **Pytest:** **95 passed / 1,38s** ✓
**Ngày:** 03/09/2026 · Góc nhìn: Lead Engineer / Systems Architect

---

## Tóm tắt điều hành

Ba cổng chất lượng đều xanh và các cải tiến lần này **đúng hướng kiến trúc**: `ILanguageDetector` là một port sạch, DIP được tuân thủ, back-compat được giữ. Nhưng khi tôi chạy detector trực tiếp trên dữ liệu thật thay vì đọc diff, **cơ chế rubber-stamp chưa bị loại bỏ — nó chỉ được di chuyển**: 5/7 vùng địa lý được khai báo vẫn trả về `True` cho gần như mọi input.

Hai vấn đề chặn việc submit registry (`server.json` sai schema, `smithery.yaml` sai format) và một tag đã bị force-move.

| Hạng mục | Trạng thái |
|---|---|
| DIP & interface boundary | ✅ Đúng chuẩn |
| Back-compat helper + CLI | ✅ Giữ nguyên |
| Loại bỏ rubber-stamp | ❌ Còn ở US/GB/CA/AU/GLOBAL |
| Cross-language contamination | ❌ JP↔ZH, BR↔VI |
| `extra_terms` đa vùng | ❌ Chỉ VN dùng |
| View skew `n >= 3` | ✅ Đúng |
| Dynamic timeframe | ✅ Đúng |
| `server.json` | ❌ `$schema` 404 |
| `smithery.yaml` | ⚠️ Sai shape |
| Console scripts | ✅ 6/6 hợp lệ |
| sdist exclude | ⚠️ Rule `reports/` không ăn |

---

# 1. Clean Architecture & Interface Boundaries — ✅ ĐẠT

## 1.1 Dependency Inversion: đúng sách

```python
# quality_evaluator.py:23,28
detector: Optional[ILanguageDetector] = None,
...
self._detector: ILanguageDetector = detector or HeuristicLanguageDetector()
```

Đây là **Constructor Injection với Default Implementation** — mẫu đúng cho một thư viện: caller có thể inject adapter riêng, mà người dùng thông thường không phải tự wire. Kiểm chứng ranh giới:

- `domain/` — **không** import gì từ `application/` hay `infrastructure/` ✓
- `application/ports/language_detector_port.py` — chỉ import `abc`, `typing`, và `GeoCode` từ `domain/` ✓ (port phụ thuộc vào domain là đúng chiều)
- `application/` và `domain/` — **không** có bất kỳ tham chiếu nào tới `HeuristicLanguageDetector` ✓

**Không có rò rỉ hạ tầng vào domain.** Việc `QualityEvaluator` (nằm ở `infrastructure/harness/`) import cả port lẫn implementation là hợp lệ — nó là adapter, không phải use case.

**Một điểm cần lưu ý cho v0.2.0:** cả hai composition root đều gọi `QualityEvaluator()` không tham số:

```
interfaces/mcp/server.py:102   quality_evaluator = QualityEvaluator()
interfaces/cli/scheduler.py:125 quality_evaluator = QualityEvaluator()
```

Nghĩa là **khả năng inject tồn tại nhưng chưa có đường dẫn nào để người dùng thực sự dùng nó**. Một dev Nhật muốn thay `HeuristicLanguageDetector` bằng adapter gọi MeCab vẫn phải sửa source. Port mới chỉ mở khoá được cho test, chưa mở khoá cho cộng đồng. Đề xuất: đọc `IGNIS_LANGUAGE_DETECTOR` (đường dẫn `module:Class`) trong composition root và `importlib` nó — khoảng 10 dòng, biến port này thành extension point thật.

## 1.2 Back-compat — ✅ giữ trọn

| Symbol | Trạng thái |
|---|---|
| `QualityEvaluator.is_localized(title, geo)` | ✓ còn, delegate sang detector |
| `QualityEvaluator.is_vietnamese(title)` | ✓ còn, trả đúng |
| `runner.py` CLI | ✓ dùng `resolve_geo` / `resolve_timeframe`, không hardcode |
| 6 console scripts | ✓ cả 6 target `main()` đều tồn tại và callable |

Không có breaking change nào lọt ra ngoài.

---

# 2. Linguistic Edge Cases — ❌ Ba lỗ hổng thật

Tôi chạy `HeuristicLanguageDetector` trực tiếp, không đọc test của các bạn.

## 🔴 2.1 Rubber-stamp chưa bị loại bỏ — nó chỉ chuyển từ `is_localized` sang `_is_english`

```python
def _is_english(self, text: str, text_lower: str) -> bool:
    if self.FOREIGN_SCRIPTS_PATTERN.search(text):
        return False
    words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text_lower)
    return len(words) >= 1          # ← bất kỳ chữ Latin nào cũng đạt
```

Kết quả thực tế với `geo=US`:

| Input | Kết quả | Đúng ra |
|---|:-:|:-:|
| `How to build an AI agent in 2026` | True | True ✓ |
| `Hướng dẫn cài đặt n8n cho người mới` | **True** | False |
| `Como criar agentes de IA autônomos em 2026` | **True** | False |
| `Formation complète n8n pour débutant` | **True** | False |
| `Cara membuat AI agent untuk bisnis` | **True** | False |
| `asdfgh qwerty zxcvbn` | **True** | False |
| `!!! 12345 !!!` | **True** | False |

`US`, `GB`, `CA`, `AU`, `GLOBAL` — **5 trong 7 vùng được khai báo** — dùng chung nhánh này. Với các thị trường đó, `language_precision` vẫn báo ~100% và `SCORECARD_WEIGHT_LANGUAGE` (0,25) vẫn đóng góp tối đa vào confidence score cho dữ liệu chưa hề được kiểm tra.

Điều này quan trọng hơn con số: `language_precision` là 1/4 trọng số của Quality Gate, và Quality Gate là thứ quyết định mission có đạt ngưỡng 70% để đi tiếp hay không. Một dev Mỹ chạy mission sẽ thấy confidence cao **vì bộ lọc không lọc gì**, chứ không phải vì dữ liệu sạch. Đây đúng là điều tôi đã cảnh báo ở Round 4 dưới dạng "geo khác VN rubber-stamp", và fix lần này chưa chạm tới nó.

**Fix — tiếng Anh cần chứng cứ dương tính, không chỉ chứng cứ âm tính:**
```python
EN_CORE_WORDS = {"the","a","an","how","to","for","with","your","best","top",
                 "guide","tutorial","review","vs","and","of","in","on","why",
                 "what","is","make","build","using","free","new","step"}

def _is_english(self, text, text_lower):
    if self.FOREIGN_SCRIPTS_PATTERN.search(text): return False
    if self.VI_EXCLUSIVE_CHARS_PATTERN.search(text): return False   # loại tiếng Việt
    if re.search(r"[ãõçñ]", text, re.I): return False               # loại PT/ES
    words = set(re.findall(r"\b[a-z]+\b", text_lower))
    if words & self.FOREIGN_STOPWORDS: return False
    return len(words & EN_CORE_WORDS) >= 1
```
Cùng khuôn với `_is_vietnamese` (Layer 3/4) — đối xứng, dễ bảo trì, và có thể kiểm bằng ma trận 2 cột.

## 🔴 2.2 `_is_japanese` nhận cả tiếng Trung

```python
JAPANESE_SCRIPT_PATTERN = re.compile(r"[぀-ヿ一-鿿]")
```

`U+4E00–9FFF` là **CJK Unified Ideographs** — dùng chung cho cả tiếng Trung và Kanji Nhật. Đo thực tế:

| Input | `geo=JP` | Đúng ra |
|---|:-:|:-:|
| `AIエージェントの作り方` (Nhật) | True | True ✓ |
| `人工知能 完全ガイド` (Nhật) | True | True ✓ |
| `如何在2026年构建人工智能代理` (Trung giản thể) | **True** | False |
| `2026年最新人工智能教程` (Trung) | **True** | False |

Với YouTube/TikTok, nội dung tiếng Trung xuất hiện dày trong feed khu vực châu Á. Một mission `geo=JP` sẽ tính nội dung Trung Quốc là "supply nội địa Nhật" → **thổi phồng Supply Score → hạ Opportunity Index → báo cáo sai rằng thị trường Nhật đã bão hoà.** Đây là lỗi làm sai kết luận kinh doanh, không chỉ sai nhãn.

**Fix — yêu cầu Kana làm bằng chứng bắt buộc:**
```python
KANA_PATTERN = re.compile(r"[぀-ゟ゠-ヿ]")   # Hiragana + Katakana
SIMPLIFIED_ONLY = re.compile(r"[们这个来对说时国经济样单产会种应严]")

def _is_japanese(self, text):
    if SIMPLIFIED_ONLY.search(text): return False   # giản thể → chắc chắn không phải Nhật
    return bool(KANA_PATTERN.search(text))
```
Hầu như mọi tiêu đề Nhật tự nhiên đều có kana (trợ từ の, は, を, hoặc katakana cho từ mượn). Tiêu đề thuần Kanji rất hiếm — đánh đổi này lãi.

## 🟡 2.3 `_is_portuguese` nhận tiếng Việt

```python
if re.search(r"[ãõáéíóúâêôç]", text, re.IGNORECASE): return True
```

Tiếng Việt dùng chung `á é í ó ú â ê ô`. Đo thực tế:

| Input | `geo=BR` |
|---|:-:|
| `Como criar agentes de IA` | True ✓ |
| `Trí tuệ nhân tạo cho doanh nghiệp` | **True** ❌ |
| `Hướng dẫn tạo AI agent` | False ✓ *(may mắn — có `ư`, `ẫ` là ký tự VN độc quyền)* |

Chỉ những tiêu đề Việt chứa ký tự VN-độc-quyền (`ư ơ đ ạ ệ ...`) mới thoát. Tiêu đề Việt chỉ dùng dấu Latin chung — khá phổ biến — sẽ lọt.

**Fix:** thêm `if self.VI_EXCLUSIVE_CHARS_PATTERN.search(text): return False` ở đầu `_is_portuguese`, và ưu tiên `[ãõç]` (đặc trưng Bồ) hơn nhóm dấu chung. Class `SHARED_LATIN_DIACRITICS` đã được khai báo ở dòng 21 nhưng **chưa dùng ở đâu** — có lẽ đây chính là chỗ nó được dự định dùng.

## 🟡 2.4 `extra_terms` không tới được vùng nào ngoài VN

`register_domain_lexicon()` là tính năng bán hàng chủ lực — "agent tự mở rộng từ vựng ngành". Nhưng `extra_terms` chỉ được truyền vào `_is_vietnamese`. Đo thực tế:

```
JP + extra_terms={"kimono","wagashi"}, text="Kimono wagashi guide"  ->  False
BR + extra_terms={...},                text="dropshipping playbook" ->  False
```

Một dev Nhật đăng ký từ vựng ngành xong vẫn bị Quality Gate loại — và **không có cách nào sửa được từ phía họ**. Với định vị domain-agnostic, đây là mâu thuẫn trực tiếp giữa tính năng quảng cáo và hành vi thật.

*Điểm sáng:* `extra_noise` được áp **trước** khi route theo geo (Step 1), nên nó hoạt động cho cả 7 vùng — tôi đã kiểm VN/US/JP/KR/TH/BR/DE, đủ cả. Thiết kế này đúng; chỉ cần `extra_terms` và `extra_stopwords` được đối xử tương tự.

## 🟢 2.5 Vùng không khai báo rơi về rubber-stamp thuần

`DE`, `FR`, `IN`, `MX` — có trong `GeoCode` hoặc resolve được — rơi vào `return len(text_clean) >= 3`. Chấp nhận được như fallback, **nhưng phải minh bạch**: khi geo không có detector chuyên biệt, `QualityScorecard` nên trả `language_precision=None` (hoặc kèm cờ `language_verified=False`) thay vì `100.0`. Con số 100 hiện tại nói dối theo hướng có lợi cho hệ thống.

## 🟢 2.6 Ghi chú nhỏ

- `FOREIGN_STOPWORDS` chứa `"complete"` và `"artificial"` — hai từ tiếng Anh rất phổ biến trong tiêu đề công nghệ Việt. Hệ quả đo được: `"Khoá học n8n complete cho người mới"` → **False**, `"Tri tue nhan tao - Artificial Intelligence la gi"` → **False**. Đây là false negative thật, do gom stopword Pháp/Bồ chung một rổ với từ tiếng Anh. Nên tách `FRENCH_STOPWORDS` riêng và bỏ hai từ này.
- `VI_CORE_WORDS` có phần tử lặp (`tu`, `phan`, `tai` xuất hiện hai lần) — vô hại với `set` nhưng là dấu hiệu copy-paste.
- `SHARED_LATIN_DIACRITICS` (dòng 21) là dead code.

---

# 3. Packaging & FastMCP Conformance

## 🔴 3.1 `server.json`: `$schema` trả 404 → `mcp-publisher` sẽ từ chối

```
đang dùng:  https://raw.githubusercontent.com/modelcontextprotocol/registry/main/schema/server.json   → HTTP 404
chính thức: https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json              → HTTP 200
```

Ngoài URL, còn ba điểm lệch so với spec chính thức:

| Trường hiện tại | Vấn đề |
|---|---|
| `"repository": {"type": "git", "url": ...}` | spec dùng `{"url": ..., "source": "github"}` |
| `"executable": "ignis-mcp"` | không có trong package schema; dùng `runtimeHint` nếu cần |
| thiếu `environmentVariables` | mất phần "Configuration" trên trang listing |

**Bản đã sửa:**
```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.fioenix/fn-ignis",
  "title": "fnIgnis Trend Intelligence & Market Research",
  "description": "Unified self-hosted autonomous trend intelligence, multi-platform social listening, and market opportunity white-space discovery MCP harness.",
  "repository": { "url": "https://github.com/fioenix/fn-ignis", "source": "github" },
  "version": "0.1.0",
  "packages": [{
    "registryType": "pypi",
    "identifier": "fn-ignis",
    "version": "0.1.0",
    "transport": { "type": "stdio" },
    "environmentVariables": [
      { "name": "DATABASE_URL",    "description": "PostgreSQL DSN, or sqlite:///ignis.db for zero-Docker mode", "isRequired": false, "format": "string" },
      { "name": "YOUTUBE_API_KEY", "description": "YouTube Data API v3 key",  "isRequired": false, "format": "string", "isSecret": true },
      { "name": "DEFAULT_GEO",     "description": "ISO 3166-1 alpha-2 code",  "isRequired": false, "format": "string" }
    ]
  }]
}
```

✅ **Điểm tốt:** `<!-- mcp-name: io.github.fioenix/fn-ignis -->` đã có ở `README.md:89` — đây là điều kiện bắt buộc để registry xác thực quyền sở hữu package PyPI, và các bạn đã đặt đúng.

⚠️ **Thứ tự bắt buộc:** `fn-ignis` **vẫn chưa có trên PyPI** (kiểm tra hôm nay: HTTP 404). Registry chỉ lưu metadata, không lưu artifact — nên phải `uv publish` lên PyPI **trước**, rồi mới `mcp-publisher publish`. Chạy `mcp-publisher publish --dry-run` để bắt lỗi schema trước khi đẩy thật.

## 🟡 3.2 `smithery.yaml` không đúng shape Smithery mong đợi

File hiện tại dùng `version` / `runtime` / `entrypoint` / `command` / `args` / `env` ở top level. Smithery expect một `startCommand` object với `type`, `configSchema` (JSON Schema) và `commandFunction`:

```yaml
startCommand:
  type: stdio
  configSchema:
    type: object
    properties:
      databaseUrl:  { type: string, default: "sqlite:///ignis.db", description: "PostgreSQL DSN or sqlite:///ignis.db" }
      youtubeApiKey:{ type: string, default: "", description: "YouTube Data API v3 key" }
      defaultGeo:   { type: string, default: "VN", description: "ISO 3166-1 alpha-2 country code" }
  commandFunction: |
    (config) => ({
      command: "uvx",
      args: ["fn-ignis"],
      env: {
        DATABASE_URL: config.databaseUrl || "sqlite:///ignis.db",
        YOUTUBE_API_KEY: config.youtubeApiKey || "",
        DEFAULT_GEO: config.defaultGeo || "VN"
      }
    })
```

> **Mức tin cậy: trung bình.** Tôi đã báo ở lần review trước và vẫn giữ nguyên cảnh báo — trang tài liệu Smithery (`/docs/build/project-config`, `/docs/build/deployments/custom-container`) trả 404 khi tôi truy cập, nên shape trên dựng từ các `smithery.yaml` đang chạy thực tế trong hệ sinh thái, không phải từ spec hiện hành. **Validate trên Smithery trước khi submit.** Đừng coi mục này là kết luận chắc chắn.

## 🟡 3.3 sdist: rule loại trừ `reports/` không có hiệu lực

```toml
exclude = [".specify", ".pytest_cache", ".ruff_cache", ".agents",
           "BACKLOG.md", "backlog.local.md", "specs",
           "reports/*.html", "!reports/case_study_*.html"]
```

`.specify`, `specs`, `BACKLOG.md` đã bị loại ✓. Nhưng build thực tế vẫn chứa:

```
fn_ignis-0.1.0/reports/mission_test1234.html          ← lẽ ra bị loại
fn_ignis-0.1.0/reports/case_study_*.html  (×3)
```

sdist 377 KB, trong đó ~300 KB là HTML report. Hatchling `exclude` **không hỗ trợ cú pháp phủ định `!`** như gitignore — dòng `"!reports/case_study_*.html"` nhiều khả năng đang vô hiệu hoá cả rule đứng trước. Nếu chủ ý là loại toàn bộ report khỏi sdist (người `pip install` không cần chúng — README trên GitHub mới cần), chỉ giữ `"reports"` và bỏ dòng phủ định.

## 🟡 3.4 Tag `v0.1.0` đã bị force-move

```
remote refs/tags/v0.1.0        -> bd1993e (annotated) -> 009cc08
trước đây v0.1.0 trỏ tới       -> 4b4c709
```

Cả `v0.1.0` và `v0.1.0-beta` giờ cùng trỏ `009cc08`. Ai đã `git fetch` trước đó đang giữ một `v0.1.0` khác — và Docker image `ghcr.io` build từ tag cũ cũng khác nội dung. Tag đã publish nên là bất biến. Khuyến nghị: giữ nguyên hiện trạng (đã lỡ rồi), nhưng từ nay phát hành `v0.1.1` cho mọi thay đổi thay vì di chuyển tag; và ghi một dòng trong release notes nói rõ `v0.1.0` đã được re-tag ngày 03/09.

## ✅ 3.5 Những thứ đã đúng

- 6 console script — cả 6 target `main()` đều tồn tại và callable, `uvx fn-ignis` sẽ chạy được sau khi publish
- `fastmcp>=0.4.0,<4.0.0` — đã có chặn trên, đóng đúng rủi ro tôi nêu lần trước
- 28 tools đồng bộ trên `README.md`, `openclaw.json`, `hermes_manifest.json`, `server.json`
- View skew `len(content_signals) >= 3` (`quality_evaluator.py:150`) — đúng, chặn được kết luận sai từ mẫu n=1/n=2
- Dynamic timeframe với `published_at` ưu tiên (`:170-191`) — đúng

---

# 4. Nợ kỹ thuật trước Epic 3 & Epic 1

## 4.1 Epic 3 (Live Alerts & Webhooks) — hai vấn đề nền móng phải xử lý trước

**(a) Scheduler state hoàn toàn in-memory.**
```python
scheduler.py:50-51
self._last_discovery_time: float = 0.0
self._last_health_check_time: float = 0.0
```
Mỗi lần restart, `0.0` khiến cycle chạy lại ngay lập tức. Với ingress thì chỉ tốn quota. **Với alerts thì đó là gửi lại thông báo trùng** — container restart lúc 3h sáng = người dùng nhận lại toàn bộ alert. Trước khi làm Epic 3, hai mốc thời gian này phải nằm trong DB.

**(b) Không có retry/backoff/idempotency ở bất kỳ đâu.** Tôi grep toàn `src/`: không có `backoff`, `retry`, `tenacity`, `max_attempts`, không outbox, không dedup key. Webhook là I/O ra ngoài, không đáng tin cậy theo bản chất — endpoint 500, timeout, người dùng đổi URL. Không có retry thì alert mất im lặng; có retry mà không idempotent thì alert nhân bản. Cần tối thiểu: bảng `webhook_deliveries` (trạng thái + attempt count + next_retry_at), exponential backoff, và một dedup key ổn định `(mission_id, signal_hash, rule_id)`.

**(c) Ngưỡng alert sẽ kế thừa trực tiếp lỗi §2.1.** Alert dựa trên Opportunity Index, mà Index dựa trên Quality Gate, mà Quality Gate có 25% trọng số là `language_precision` — hiện đang báo ~100% giả cho 5 vùng. Với ingress thủ công thì người dùng còn nhìn thấy và tự đánh giá; với alert tự động thì **hệ thống tự tin gửi thông báo sai vào lúc 3h sáng.** §2.1 nên được xem là điều kiện tiên quyết của Epic 3, không phải việc song song.

## 4.2 Epic 1 (Official Meta Threads OAuth) — kiểm lại vòng đời khoá

Lớp crypto hiện tại (`encrypt_credentials` / `decrypt_credentials`, Fernet) đủ dùng cho cookie session TikTok, nhưng OAuth token khác về bản chất:

- **Ephemeral key sẽ phá OAuth.** Nếu `IGNIS_ENCRYPTION_KEY` trống, hệ thống sinh khoá tạm trong RAM (fix từ Round 3). Cookie mất sau restart chỉ gây phiền; **refresh token mất sau restart nghĩa là user phải đăng nhập lại mỗi lần deploy.** Epic 1 phải coi `IGNIS_ENCRYPTION_KEY` là **bắt buộc**, fail-fast khi thiếu, chứ không degrade âm thầm.
- **Chưa có refresh flow.** Long-lived token của Threads hết hạn sau ~60 ngày và cần chủ động refresh. Cần một cycle mới trong scheduler + cột `expires_at`, và tuyệt đối không refresh lười trong request path.
- **Chưa có key rotation.** Đổi `IGNIS_ENCRYPTION_KEY` hôm nay = mọi credential đã lưu thành rác không đọc được, không có đường di trú. Nên thêm `key_version` vào bản ghi credential **trước khi** có token OAuth thật để bảo vệ.
- **PII.** Threads trả về profile người dùng. `sanitize_pii_text` hiện áp cho title và comment; luồng OAuth mới sẽ mang thêm username, user ID, có thể cả email — cần quyết định *trước* chứ không phải sau: cái gì được lưu, lưu bao lâu, và có pseudonymize không (Luật 91/2025/QH15).

## 4.3 Nợ kiến trúc còn tồn (nhắc lại, chưa thay đổi)

7 chỗ `application/` import thẳng `infrastructure/`, nặng nhất là `autonomous_discovery.py:13-14` phụ thuộc hai class TikTok đích danh. Cả hai Epic sắp tới đều **thêm** connector và **thêm** đường dữ liệu — mỗi tuần trì hoãn làm việc gỡ này đắt thêm. Đây vẫn là hạng mục số một của v0.2.0.

---

# 5. Việc cần làm, xếp theo thứ tự

| # | Việc | Mức | Ước lượng |
|:-:|---|:-:|---|
| 1 | Sửa `_is_english` — yêu cầu chứng cứ dương tính (§2.1) | 🔴 | 1h |
| 2 | `_is_japanese` bắt buộc có Kana + loại giản thể (§2.2) | 🔴 | 30ph |
| 3 | `server.json`: `$schema` chính thức + `repository.source` + `environmentVariables` (§3.1) | 🔴 | 20ph |
| 4 | `_is_portuguese` loại ký tự VN-độc-quyền (§2.3) | 🟡 | 15ph |
| 5 | Truyền `extra_terms`/`extra_stopwords` vào mọi nhánh geo (§2.4) | 🟡 | 45ph |
| 6 | `language_precision=None` cho geo không có detector (§2.5) | 🟡 | 30ph |
| 7 | Bỏ `complete`/`artificial` khỏi `FOREIGN_STOPWORDS` (§2.6) | 🟡 | 10ph |
| 8 | Sửa `smithery.yaml` + validate trên Smithery (§3.2) | 🟡 | 30ph |
| 9 | Publish PyPI → `mcp-publisher publish --dry-run` → publish (§3.1) | 🟡 | 1h |
| 10 | Persist scheduler timestamps vào DB — **chặn Epic 3** (§4.1a) | 🟡 | 2h |

Việc 1–3 nên nằm trong `v0.1.1` trước khi công bố rộng. Việc 10 là điều kiện tiên quyết kỹ thuật của Epic 3.

---

## Ghi chú phương pháp

Mọi phát hiện ở §2 đến từ việc **gọi trực tiếp `HeuristicLanguageDetector` với dữ liệu thật**, không phải từ đọc diff hay tin vào 95/95. Bộ test hiện tại xanh hoàn toàn trong khi `geo=US` chấp nhận `'!!! 12345 !!!'` — đúng mô hình đã lặp lại xuyên suốt các vòng review: **lỗi nghiêm trọng nằm trong vùng mà bộ test báo là đã được bảo vệ.**

Đề xuất cụ thể: mỗi nhánh geo cần một ma trận 2 cột — *phải chấp nhận* và *phải từ chối*, trong đó cột thứ hai chứa văn bản của **các ngôn ngữ láng giềng** (JP phải từ chối ZH; BR phải từ chối VI; US phải từ chối PT/FR/ID/VI). Đây chính là khuôn `test_pii_two_column_matrix_guardrails` mà các bạn đã áp dụng thành công cho sanitizer — nhân nó sang detector là xong.
