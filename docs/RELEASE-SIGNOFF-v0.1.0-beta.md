# fn-ignis — Giấy Nghiệm thu Release `v0.1.0-beta`

- **Ngày**: 02/09/2026 · **Commit**: `6bc2083` · **Working tree**: clean 100%
- **Chuỗi audit**: R1 `c8f954c` → R2 `402cb5b` → R3 `97635a2` → R4 `3d85ce4` → **R5 `6bc2083`**
- **Phương pháp**: Postgres thật `timescale/timescaledb-ha:pg16` với `sql/` nguyên trạng; round-trip dữ liệu qua cả 2 backend; kiểm noise filter theo cả hai chiều (false positive + true positive) kèm edge case.

---

# ✅ PHÁN QUYẾT: ĐƯỢC PHÉP TAG `v0.1.0-beta`

Không còn release blocker nào. Toàn bộ phát hiện Round 4 đã đóng, và đóng đúng cách — tôi kiểm chứng lại từng cái bằng thực nghiệm chứ không đọc diff.

## 1. Cổng chất lượng

| Cổng | Kết quả |
|---|---|
| `git status` | 🟢 clean |
| `uv run ruff check src/ tests/` | 🟢 **All checks passed** |
| `uv run pytest tests/ --cov=ignis` | 🟢 **81/81 passed**, coverage 62% |
| Guard đóng `_value2member_map_` còn lại | 🟢 **0 / 13** |
| Postgres initdb (`sql/` nguyên trạng) | 🟢 `Up`, **0 error**, **7/7 bảng** |

## 2. Nghiệm thu từng phát hiện Round 4

### 🟢 N2 — False-positive noise: ĐẠT toàn diện

Cơ chế mới `(?:\b|#){term}\b`. Tôi kiểm **cả bốn chiều**, vì siết boundary rất dễ làm hỏng chiều còn lại:

**(a) 8/8 false positive Round 4 đã hết:**
```
False ✓ 'Trending products tren TikTok Shop 2026'
False ✓ 'Viral marketing strategy cho local brand'
False ✓ 'Abundance mindset trong ban hang'          <- 'dance' không còn khớp
False ✓ 'Game development studio can tuyen dung'
False ✓ 'Nganh anime merchandise tai Viet Nam'
False ✓ 'Cosplay commerce niche analysis'
False ✓ 'AI music generation tool cho creator'
False ✓ 'Gamification trong CRM doanh nghiep'
```

**(b) 7/7 noise thật vẫn bị chặn** (không đánh đổi recall lấy precision):
```
True ✓ 'Hai kich #funny #haihuoc cuoi be bung'    True ✓ 'Video troll ban than cuc manh'
True ✓ 'Nhac tre remix #nhactre hay nhat'         True ✓ 'Clip haihuoc'
True ✓ 'Duet #fyp #xuhuong dance challenge'       True ✓ '#foryoupage content'
True ✓ 'Daily vlog cuoc song gia dinh'
```

**(c) Edge case tôi lo nhất — term đăng ký kèm dấu `#`** (Agent rất dễ truyền `["#funny"]` vì SOP và seed cũ đều viết vậy). Nếu không xử lý, `re.escape("#funny")` sẽ khiến pattern không bao giờ khớp:
```
True ✓ 'Hai kich #funny cuoi be bung'     (term = '#funny')
True ✓ '#haihuoc tap 5'                   (term = '#haihuoc')
```
Đã xử lý đúng.

**(d) Term tiếng Việt có dấu** — `\b` với Unicode dễ hành xử lạ:
```
True ✓ 'Phim hài Tet 2026'        True ✓ 'Tiểu phẩm gia dinh'
True ✓ 'Nam thần kinh tap 12'     True ✓ 'Xem phim hài'
```

Việc bỏ `trending`, `viral`, `game`, `anime` khỏi seed mặc định là quyết định đúng: đó là policy của người dùng, không phải mặc định của tool.

### 🟢 N1 — Parity gap thế hệ 3: ĐẠT, kèm contract test thật

```
PG = 19 term   SQLite = 19 term   set bằng nhau: True
```

Quan trọng hơn con số: `test_postgres_sqlite_noise_seed_parity` **parse trực tiếp `sql/004_global_lexicons.sql`** rồi so `set` với seed SQLite:

    assert pg_noise_terms == sqlite_noise_terms, f"Difference: {pg_noise_terms ^ sqlite_noise_terms}"

Đây là **contract test đúng nghĩa đầu tiên** của dự án — chính thứ tôi đề xuất từ Round 1, và là thứ đã bỏ lọt cùng một lớp lỗi ba lần liên tiếp (R1 key names → R3 SQLite rỗng → R4 cùng count khác content). Lần này nó không thể tái diễn mà không làm đỏ CI.

### 🟢 Gỡ 13 guard đóng: ĐẠT — fix quan trọng nhất của cả 5 vòng

`resolve_geo()` / `resolve_platform()` / `resolve_timeframe()` trong `domain/value_objects.py`, 0 guard còn lại.

**resolve_geo — 10/10 thị trường quốc tế giữ nguyên, không thay thế âm thầm:**
```
VN->VN ✓  US->US ✓  BR->BR ✓  KR->KR ✓  IN->IN ✓
MX->MX ✓  AU->AU ✓  CA->CA ✓  NG->NG ✓  PL->PL ✓
```
(Round 4: `BR KR IN MX AU CA` đều bị ép về `VN`.)

**resolve_platform — connector cộng đồng hoạt động:**
```
youtube ✓   reddit ✓   xiaohongshu ✓   linkedin ✓
```

**Bài kiểm quyết định — round-trip qua Postgres thật:**
```
ghi   geo='BR'  platforms=['youtube', 'reddit', 'xiaohongshu']
đọc   geo='BR'  platforms=['youtube', 'reddit', 'xiaohongshu']
geo giữ nguyên: ✓        platforms giữ nguyên: ✓
```
Round 4: đọc ra chỉ còn `['youtube']` (mất 2/3) và `geo='BR'` thành `'VN'`. Giờ nguyên vẹn. SQLite cũng vậy (`KR` → `KR` ✓).

Nghĩa là **mục tiêu số 1 của bản refactor kiến trúc — "cộng đồng viết Connector mới mà không sửa core" — giờ đã đạt được trên đường dữ liệu**.

### 🟢 Coverage score cap: ĐẠT
```
2 platform -> coverage= 40.0  confidence=39.5 ✓
5 platform -> coverage=100.0  confidence=47.0 ✓
7 platform -> coverage=100.0  confidence=47.0 ✓   (Round 4: 140.0)
```

### 🟢 Regression suite: 7/7 PASSED thật, không skip
Tôi kiểm riêng bằng `-v` vì có một `@pytest.mark.asyncio` đặt sai trên hàm sync — pytest-asyncio bỏ qua marker đó với hàm đồng bộ nên test vẫn chạy thật, không bị skip ngầm.

## 3. Ba điểm nhỏ, không chặn release

1. **`resolve_timeframe` nhận mọi chuỗi.** `resolve_timeframe('bogus')` → `'bogus'`, rồi `_timeframe_to_published_after('bogus')` **âm thầm dùng 7 ngày**. Cùng mô-típ "thay thế âm thầm" nhưng trên tham số kỹ thuật có biên, tác động thấp hơn geo rất nhiều. Điểm cộng ngoài dự kiến: `'90d'` giờ hoạt động (trước chỉ 24h/7d/30d) — đúng thứ các mission đang dùng. Đề nghị v0.2.0: whitelist `^\d+[hdwm]$` + raise khi sai.
2. **`@pytest.mark.asyncio` trên hàm sync** (`test_dynamic_resolvers_without_silent_substitution`) — vô hại, chỉ là nhiễu. Xóa marker.
3. **`RuntimeWarning: coroutine ... never awaited`** tại `tiktok_plugin.py:183` — dấu vết cuối cùng của R1-P1-21 (handler `page.on("response")` đăng ký trong vòng lặp trên cùng một `page`, closure bắt biến vòng lặp → nhiễm chéo suggestions giữa các keyword + rò rỉ listener). Không chặn beta.

## 4. Danh sách chuyển tiếp v0.2.0

Nhóm này chưa từng nằm trong cam kết của đội qua 5 vòng — ghi lại để hoạch định, không tính là nợ quá hạn.

**Nhóm A — Độ tin của số liệu bán ra cho khách (ưu tiên cao nhất)**
- `language_precision` sai mẫu số (tính cả signal Google Trends không mang ngôn ngữ) → 75% thay vì 100%
- `is_localized` bất đối xứng: mọi geo ≠ VN là con dấu cao su (`'aaa'` → True), `language_precision = 100%` cho US/JP/DE/BR, tức **miễn phí 25 điểm** confidence
- `captured_at` hai ngữ nghĩa (TikTok = giờ scrape, YouTube = giờ publish) → `data_freshness_score` (trọng số 30%, cao nhất) gần như hằng số
- `evaluate_quality` không nhận `timeframe_days` từ mission → luôn cửa sổ 90 ngày
- View-skew rule bắn nhầm khi n=1
- **Chưa có golden-file test cho `_discover_market_opportunities` và `evaluate_quality`** — điều kiện tiên quyết trước khi làm pluggable scoring

**Nhóm B — Resilience**
- Không xử lý 429/403 ở TikTok/Threads/Reels → soft-block trả 0 kết quả, không exception → breaker gọi `record_success()`, vĩnh viễn CLOSED
- `is_healthy()` cứng `True` ở 4/6 connector (đúng 4 scraper mong manh nhất)
- `_last_discovery_time = 0.0` → mỗi lần restart chạy lại full discovery ngay

**Nhóm C — Kiến trúc (3 khuyến nghị Round 4, đội đã đồng thuận)**
- Khép hợp đồng Extensible Primitives: `register()` tường minh + 249 mã ISO-3166
- `ILanguageDetector` port (giải quyết trực tiếp Nhóm A điểm 2)
- Capability Registry + Auto-Discovery qua entry points; kèm 7 import application→infrastructure và 7 chỗ truy cập `registry._plugins`

**Nhóm D — Vệ sinh & tuân thủ**
- PII: `salt = "ignis_salt_2026"` là hằng số trong source public (chưa đạt GDPR Điều 4(5)); handle creator vẫn lưu nguyên trong `trend_signals.metadata`
- Reports split-brain: `parents[3]` (`src/reports`) vs `parents[4]` (`reports/`) → nginx không nhận digest của scheduler
- Error contract MCP: 11/28 handler có try/except
- README ghi "15 FastMCP Tools", thực tế **28**
- 136 dòng tiếng Việt còn lại trong `src/`

## 5. Trước khi công bố: sửa 2 dòng README

Đây là vấn đề trung thực của tài liệu, không phải code:
- `README.md:78`: "15 FastMCP Tools" → **28**
- Ghi rõ phạm vi geo. Sau bản vá này `resolve_geo` nhận **mọi** mã, nên câu "any ISO-3166 region" đã đúng về hành vi — nhưng hãy nói thêm rằng **chỉ `VN` có bộ nhận diện ngôn ngữ đầy đủ**; các geo khác hiện bỏ qua bước xác thực ngôn ngữ và `language_precision` sẽ báo 100%. Người dùng quốc tế cần biết con số đó nghĩa là "chưa kiểm tra", không phải "hoàn hảo".

---

## Ghi chú cuối

Năm vòng audit đi từ **7 lỗi P0** — container không boot, khóa mã hóa công khai, Macro Scan chết im lặng, bộ lọc tiếng Việt loại chính cụm từ phổ biến nhất của tiếng Việt — xuống **không còn blocker nào**.

Điều đáng ghi nhận nhất không phải số lỗi đã sửa, mà là **sự thay đổi trong cách sửa**. Round 2 sửa nhãn `AES-256` → `AES-128` mà để nguyên lỗ hổng khóa. Round 5 thì: siết boundary regex **và** kiểm cả hai chiều recall/precision, thêm parity test parse thẳng file SQL, gỡ cả 13 guard chứ không vá từng chỗ. Đó là khác biệt giữa đóng ticket và đóng lớp lỗi.

Một bài học nên giữ lại: qua cả 5 vòng, mỗi lỗi nghiêm trọng nhất đều nằm trong vùng mà **bộ test đang báo là đã được bảo vệ** — `test_dynamic_noise_blacklist_rejection` xanh trong khi 2/3 đường production chặn 0/4; `test_crypto_ephemeral_key_security` pass y nguyên trên code đã bị bác bỏ. Bài học không phải "viết thêm test", mà là **test phải đi qua đúng con đường mà production đi**. `test_postgres_sqlite_noise_seed_parity` của Round 5 là ví dụ đầu tiên làm đúng điều đó — nên nhân bản mô hình ấy cho Nhóm A ở v0.2.0.
