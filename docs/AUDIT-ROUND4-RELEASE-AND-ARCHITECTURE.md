# fn-ignis — Round 4: Nghiệm thu Release + Architectural Review (Generalization)

- **Ngày**: 02/09/2026 · **HEAD**: `3d85ce4` · **Working tree**: clean 100% ✓
- **Chuỗi audit**: R1 `c8f954c` → R2 `402cb5b` → R3 `97635a2` → R4 `3d85ce4`
- **Phương pháp**: Postgres thật `timescale/timescaledb-ha:pg16` chạy `sql/` nguyên trạng; test noise qua production path trên **cả 2 backend**; mô phỏng chính xác logic từng call site để đo hành vi thực của abstraction.

---

# PHẦN A — PHÁN QUYẾT RELEASE

## A.0 Nghiệm thu 2 Blocker của Round 3

| Blocker | Phán quyết | Bằng chứng |
|---|---|---|
| ① Noise inversion trong `refinement_orchestrator` | 🟢 **ĐẠT** | `not in ("foreign_stopwords","noise_blacklist")` + nạp `register_noise_blacklist`; noise **không còn** lọt vào lexicon tích cực |
| ② Seed `noise_blacklist` vào SQLite | 🟡 **ĐẠT hình thức, LỆCH nội dung** | 22 term có mặt, nhưng **chỉ 10/22 trùng với Postgres** |

Kiểm chứng Blocker ① trên đường orchestrator (SQLite, Zero-Docker):
```
noise seed từ SQLite      : 22 term
noise lọt lexicon TÍCH CỰC: KHÔNG ✓        (Round 3: ['fyp','funny','haihuoc','dance','troll'])
```
Lỗi đảo ngược nghiêm trọng nhất của Round 3 đã đóng.

## A.1 Các fix khác — ĐẠT

| Mục | Kết quả |
|---|---|
| Postgres initdb (`sql/` nguyên trạng) | 🟢 `Up`, **0 error**, **7/7 bảng** |
| Bỏ `ã õ ũ` khỏi `VI_EXCLUSIVE_CHARS` | 🟢 **ĐẠT, không regression** |
| Xóa 37 `GARBAGE_PATTERNS` hardcode | 🟢 **ĐẠT** (`grep` = 0) |
| `_geo_to_region_code` động ISO-3166 | 🟢 **ĐẠT** |
| `ruff check src/ tests/` | 🟢 **0 error** |
| `pytest` | 🟢 **79/79 pass**, coverage 62% |
| `git status` | 🟢 **clean** |

**Fix `ã õ ũ` làm rất đúng** — tôi kiểm cả hai chiều, vì rủi ro thật là gỡ ký tự chung sẽ làm hỏng nhận diện tiếng Việt:
```
Tiếng Bồ (mục tiêu False):
  False  'Automação de processos com n8n'
  False  'Configuração da API do WhatsApp'
  False  'Criação de agentes inteligentes'

Tiếng Việt có ã/õ/ũ (mục tiêu True) — KHÔNG regression:
  True   'Rõ ràng và minh bạch'
  True   'Cũng như mọi khi'
  True   'Mãi mãi một tình yêu'
  True   'Hướng dẫn cài đặt n8n'
```
Lý do fix an toàn: các câu Việt này luôn kèm ký tự **thật sự** độc quyền (`ạ ề ữ ẻ ơ`), nên `ã/õ/ũ` là dấu hiệu dư thừa. Đây là phân tích đúng.

## A.2 Ba phát hiện mới

### 🟠 N1 — Seed noise 2 backend lệch 12/22 term (parity gap thế hệ thứ 3)

```
Postgres: 22 term | SQLite: 22 term | trùng nhau: 10/22

CHỈ Postgres có: bongda, capcut, chuyenhai, duet, giadinh, giaitri,
                 golivegrowfast, music, namthankinh, thethao, tiktokshop99, vietnamvodich
CHỈ SQLite  có : anime, chuyenma, cosplay, foryou, foryoupage, game,
                 gaming, gocnhin, kinhdi, ngontinh, phimngan, reviewphim
```

Cùng một mission chạy trên 2 backend sẽ **lọc noise khác nhau 55%**: Postgres chặn `bongda`/`namthankinh`, SQLite thì không; SQLite chặn `game`/`anime`/`cosplay`, Postgres thì không.

Đây là **lần thứ ba** cùng một lớp lỗi xuất hiện: R1-P0-4 (`credentials` vs `credentials_data`), R3-Blocker② (SQLite rỗng), giờ R4-N1 (cùng số lượng, khác nội dung). Mỗi lần nó lại subtler hơn một bậc, và mỗi lần đều thoát khỏi bộ test.

**Lý do nó thoát**: `test_dynamic_noise_blacklist_rejection_end_to_end_sqlite` assert `len(noise_items) >= 22` + kiểm 3 term (`fyp`, `haihuoc`, `dance`) — cả 3 đều nằm trong phần trùng 10/22. Test đi qua DB thật (**tiến bộ thật so với R3** ✓) nhưng vẫn assert vào *số lượng* + *mẫu an toàn* thay vì *parity*.

**Fix**: một nguồn duy nhất. Đưa danh sách seed vào một module Python (`domain/seeds.py` hoặc `infrastructure/persistence/seeds.py`), cả `sql/004` (sinh ra bằng script) và SQLite `initial_seeds` đều đọc từ đó. Test: `assert set(pg_terms) == set(sqlite_terms)` — đây là contract test tôi đã đề xuất từ Round 1, vẫn chưa có.

### 🔴 N2 — Noise blacklist loại oan chính các chủ đề nghiên cứu hợp pháp

`_is_garbage` khớp **substring, không word boundary, không phân biệt hashtag với nội dung**. Với danh sách mới (chứa `trending`, `viral`, `game`, `anime`, `dance`, `music`):

```
loại_bỏ=True  'Trending products tren TikTok Shop 2026'    <- khớp ['trending']
loại_bỏ=True  'Viral marketing strategy cho local brand'   <- khớp ['viral']
loại_bỏ=True  'Game development studio can tuyen dung'     <- khớp ['game']
loại_bỏ=True  'Nganh anime merchandise tai Viet Nam'       <- khớp ['anime']
loại_bỏ=True  'Abundance mindset trong ban hang'           <- khớp ['dance']   (!!)
loại_bỏ=True  'Cosplay commerce niche analysis'            <- khớp ['cosplay']
```

Với một sản phẩm **trend intelligence**, việc loại bỏ *"trending products"* và *"viral marketing"* là nghịch lý tự hủy: đó chính là hai truy vấn phổ biến nhất mà người dùng sẽ nhập. `'Abundance'` → `dance` là false positive kinh điển của substring matching. Và `anime`/`cosplay`/`game` là **vertical thị trường thật** ở Nhật/Hàn/Đông Nam Á — chính các thị trường mà bản refactor này muốn mở ra.

**Root cause là kiến trúc, không phải danh sách**: mechanism (substring match) quá yếu để biểu đạt policy cần thiết. Không có cách nào viết một term để nói *"loại `#trending` khi là hashtag, giữ `trending products` khi là chủ đề"*.

**Fix**: nâng cấp mechanism, không phải cắt bớt danh sách.
```python
# thay vì: any(term in title.lower() for term in noise)
NOISE_RULE = {"term": "trending", "match": "hashtag"}   # chỉ khớp #trending
NOISE_RULE = {"term": "haihuoc",  "match": "word"}      # \bhaihuoc\b
NOISE_RULE = {"term": "phim hài", "match": "phrase"}    # cụm nguyên văn
```
Tối thiểu cho beta: dùng `\b{term}\b` (diệt ngay `abundance`) và bỏ `trending`/`viral`/`game` khỏi seed mặc định — chúng thuộc policy của người dùng, không phải mặc định của tool.

### 🟢 N3 — `#namthankinh` thoát trên SQLite

Hệ quả trực tiếp của N1 (`namthankinh` chỉ có trong seed Postgres). Không phải lỗi riêng.

## A.3 PHÁN QUYẾT: 🟢 **RELEASE `v0.1.0-beta` — ĐƯỢC, sau khi sửa N2**

Cả 2 Blocker của Round 3 đã đóng. Không còn lỗi nào làm sập deploy, mất dữ liệu, hay rò rỉ khóa mã hóa. Bốn vòng audit đã đi từ *"7 P0, container không boot, khóa công khai"* xuống *"1 vấn đề precision của filter"*.

**Một việc chặn tag (15 phút)**: N2 — thêm `\b` word boundary vào `_is_garbage` và bỏ `trending`, `viral`, `game`, `gaming` khỏi seed mặc định. Không sửa thì công cụ nghiên cứu xu hướng sẽ loại bỏ từ khóa `trending` — người dùng đầu tiên trên Product Hunt sẽ gặp ngay.

**Làm cùng lúc nếu có thời gian (30 phút)**: N1 — hợp nhất seed về một nguồn.

---

# PHẦN B — ARCHITECTURAL REVIEW: TÍNH TỔNG QUÁT HÓA

## B.1 Câu hỏi 1: Developer quốc tế clone repo về dùng được chưa?

### 🔴 **Chưa. Và bias không nằm ở từ vựng — nó nằm ở lớp guard.**

Đây là phát hiện quan trọng nhất của cả đợt review. Bản refactor đã **mở** `PlatformType`/`GeoCode` bằng `_missing_`, nhưng `_missing_` **không ghi vào `_value2member_map_`** — trong khi **13 call site vẫn dùng đúng cái map đó làm guard**:

```
src/ignis/interfaces/mcp/server.py:185, 418, 672, 731, 787   (geo)
src/ignis/interfaces/mcp/server.py:424                        (platforms)
src/ignis/infrastructure/persistence/postgres_repository.py:346, 347, 429, 430
src/ignis/infrastructure/persistence/sqlite_repository.py:437, 477
```

Mô phỏng **chính xác** logic `mcp/server.py:185`:
```
geo='VN'  -> 'VN'
geo='US'  -> 'US'
geo='JP'  -> 'JP'          (JP có khai báo trong enum)
geo='DE'  -> 'DE'
geo='BR'  -> 'VN'    <-- BỊ ÉP VỀ VIỆT NAM
geo='KR'  -> 'VN'    <-- BỊ ÉP VỀ VIỆT NAM
geo='IN'  -> 'VN'    <-- BỊ ÉP VỀ VIỆT NAM
geo='MX'  -> 'VN'    <-- BỊ ÉP VỀ VIỆT NAM
geo='AU'  -> 'VN'    <-- BỊ ÉP VỀ VIỆT NAM
geo='CA'  -> 'VN'    <-- BỊ ÉP VỀ VIỆT NAM
```

**Một developer ở Brazil gọi `create_research_mission(geo="BR")` sẽ nhận về một mission Việt Nam, không một dòng cảnh báo.** Đây là "Vietnam bias" ở dạng tệ nhất có thể: không phải bias trong từ vựng (cái đó dễ thấy và đã được xử lý), mà là **fallback âm thầm về VN ở ranh giới API**. `GeoCode("BR")` hoạt động hoàn hảo; chính interface layer từ chối nó.

Với platforms — mục tiêu chính của việc mở enum:
```
input=['reddit']                              -> giữ []             BỊ LOẠI ÂM THẦM=['reddit']
input=['youtube','reddit','xiaohongshu']      -> giữ ['youtube']    BỊ LOẠI ÂM THẦM=['reddit','xiaohongshu']

postgres_repository.py:346 (đọc mission từ DB):
  DB lưu ['youtube','reddit','xiaohongshu']  ->  đọc ra ['youtube']   (mất 2/3)
```

Nghĩa là connector cộng đồng bị loại **hai lần**: khi tạo mission, và khi đọc mission từ DB. Ngay cả khi ai đó vá được lớp MCP, dữ liệu vẫn bị cắt ở lớp persistence. **Mục tiêu số 1 của bản refactor — "cộng đồng viết thêm Connector mà không sửa core" — hiện chưa đạt được.**

**Fix**: đây là lỗi một-hàm. Thay 13 guard bằng một resolver duy nhất trong `domain/`:
```python
def resolve_geo(value: str, *, strict: bool = False) -> GeoCode:
    """Resolve a geo code. Never silently substitutes a different market."""
    if not value or not value.strip():
        raise ValueError("geo must not be empty")
    code = value.strip().upper()
    if code not in _ISO_3166_ALPHA2 and code != "GLOBAL":
        if strict:
            raise ValueError(f"Unknown geo code: {code!r}")
        logger.warning("Geo %r is not a recognized ISO-3166-1 alpha-2 code; proceeding as custom region.", code)
    return GeoCode(code)
```
Nguyên tắc: **fallback được phép, thay thế âm thầm bằng một thị trường khác thì không.** Nếu buộc phải fallback, log rõ và ghi vào scorecard flaw.

## B.2 Câu hỏi 2: Điểm nghẽn kiến trúc còn sót

### 🔴 B2-1. `_missing_` mở cửa nhưng không có hợp đồng nào

```
PlatformType('youtub')          -> 'youtub'            ĐƯỢC CHẤP NHẬN
PlatformType('TIKTOKK')         -> 'tiktokk'           ĐƯỢC CHẤP NHẬN
PlatformType("'; DROP TABLE--") -> "'; drop table--"   ĐƯỢC CHẤP NHẬN
PlatformType('')                -> ''                  ĐƯỢC CHẤP NHẬN
GeoCode('Vietnam')              -> 'VIETNAM'           ĐƯỢC CHẤP NHẬN
GeoCode('usa')                  -> 'USA'               ĐƯỢC CHẤP NHẬN
GeoCode('ZZZZ')                 -> 'ZZZZ'              ĐƯỢC CHẤP NHẬN
```

`PlatformType('')` được chấp nhận là một platform. `GeoCode('usa')` thành `'USA'` — không phải ISO-3166 (đúng là `US`) → **phân mảnh dữ liệu**: `trend_signals` sẽ có cả `US` và `USA` như hai thị trường riêng, không ai phát hiện. Một typo trong config của người dùng tạo ra một partition dữ liệu mới, im lặng.

Đây là Open-Closed hiểu chưa đủ: OCP nói *"mở để mở rộng"*, không nói *"mở để nhận bất kỳ chuỗi nào"*. Mở rộng cần **đăng ký tường minh**:
```python
PlatformType.register("reddit")          # cộng đồng gọi 1 lần khi load plugin
PlatformType("reddit")                   # từ đó hợp lệ, có trong _value2member_map_
PlatformType("youtub")                   # -> ValueError, vì chưa đăng ký
```
Cách này giữ nguyên tính mở, xóa 13 guard (vì map đã đầy đủ), và bắt được typo. Chi phí: một classmethod ~8 dòng.

*(Điểm tốt: `hash`/`__eq__` dựa trên `str` nên `Dict[PlatformType, plugin]` của registry vẫn tra cứu đúng dù `a is b == False`. Không có bug ở đây ✓)*

### 🔴 B2-2. `is_localized` bất đối xứng — VN có bộ nhận diện thật, mọi geo khác là con dấu cao su

```python
        if geo_val.upper() == "VN":
            return self.is_vietnamese(title)      # 3 tầng, ~200 dòng heuristic
        if self._custom_noise: ...                # chỉ lọc noise
        return len(title.strip()) >= 3            # <-- "chính sách" cho toàn thế giới
```

Hệ quả đo được:
```
geo=DE  is_localized('Best AI agent tools 2026')      = True
geo=DE  is_localized('Xin chào các bạn hôm nay...')    = True    (tiếng Việt, thị trường Đức)
geo=DE  is_localized('aaa')                            = True
geo=DE  is_localized('日本語のテスト')                     = True

language_precision:  US=100.0  JP=100.0  DE=100.0  BR=100.0
```

`language_precision` chiếm **25% trọng số** của `overall_confidence`. Với mọi thị trường ngoài VN, nó là hằng số 100 — nghĩa là một mission ở Đức nhận **miễn phí 25 điểm** tin cậy, và scorecard không thể phát hiện dữ liệu ngoại ngữ lẫn vào. Một developer Đức sẽ thấy `confidence: HIGH` trên dữ liệu mà hệ thống chưa từng kiểm tra.

**Đây là chỗ "Separation of Mechanism & Policy" chưa thành hiện thực**: policy cho VN được **hardcode thành code**, policy cho các nước khác là **rỗng**. Tách đúng nghĩa phải là: một mechanism duy nhất (`ILanguageDetector`), nhiều policy nạp được (VN heuristic là một plugin, `fasttext`/`langdetect` là một plugin khác, và mặc định trung lập cho geo chưa có policy).

Quan trọng: **trả `None` thay vì `True`** khi không có detector cho geo đó, rồi ghi flaw `"language verification unavailable for DE"` và **loại thành phần này khỏi công thức** (chuẩn hóa lại trọng số trên các thành phần đo được). Trung thực hơn hẳn việc cho điểm 100.

### 🟠 B2-3. Công thức tính điểm hardcode số nền tảng — OCP vỡ ngay trong toán học

`quality_evaluator.py`: `coverage_score = (len(platforms_present) / 5.0) * 100.0`

```
2 platform -> coverage_score =  40.0   overall_confidence = 39.5
5 platform -> coverage_score = 100.0   overall_confidence = 47.0
7 platform -> coverage_score = 140.0   overall_confidence = 52.0   <-- vượt thang 0-100
```

Cộng đồng thêm 2 connector → điểm vượt trần thang đo mà `QualityScorecard` tự khai báo là `(0-100)`, và `overall_confidence` bị thổi theo. Hằng số `5.0` là **số connector built-in tại thời điểm viết code** — nó phải là `len(registry.list_plugins())` hoặc `len(mission.platforms)`.

Cùng loại: `semantic_clusterer._calculate_cross_platform_score` dùng `/5.0` cho diversity và `/7.0` cho log-scale metric — cả hai là magic number gắn với cấu hình cũ.

### 🟠 B2-4. Clean Architecture: 7 import application → infrastructure vẫn còn (R1-P2-1, chưa xử lý qua 4 vòng)

```
application/use_cases/execute_mission.py:7        -> ConnectorPluginRegistry
application/use_cases/ingest_trends.py:5          -> ConnectorPluginRegistry
application/use_cases/autonomous_discovery.py:12  -> ConnectorPluginRegistry
application/use_cases/autonomous_discovery.py:13  -> TikTokCreativeCenterPlugin   (concrete!)
application/use_cases/autonomous_discovery.py:14  -> TikTokPlugin                 (concrete!)
application/use_cases/autonomous_discovery.py:15  -> QualityEvaluator
application/use_cases/autonomous_discovery.py:16  -> StrategicMarketReasoner
```

Nghiêm trọng nhất vẫn là `isinstance(plugin, TikTokPlugin)` để nhặt plugin ra khỏi registry. Với mục tiêu domain-agnostic, điều này nói: *"use case Autonomous Discovery chỉ chạy được nếu bạn dùng đúng TikTok connector của chúng tôi"*. Một cộng đồng viết `XiaohongshuPlugin` với cùng năng lực (`fetch_macro_trends`, `fetch_top_comments_for_keywords`) **không thể** tham gia bước Macro Scan hay VoC. Đây là OCP vỡ ở tầng cao nhất.

Fix đúng: **capability-based lookup** thay vì type-based.
```python
# port
class ISupportsMacroTrends(Protocol):
    async def fetch_macro_trends(self, *, geo, period, limit, industry) -> list[dict]: ...

# use case
for plugin in registry.find_by_capability(ISupportsMacroTrends):
    ...
```
Đồng thời `registry._plugins` vẫn bị truy cập từ **7 chỗ ngoài registry** — dùng `list_plugins()` đã có sẵn.

### 🟠 B2-5. Không có connector auto-discovery — mở rộng vẫn phải sửa core

`grep entry_points|importlib|pkgutil` → **không có kết quả**. Đăng ký plugin là thủ công, ở **hai** nơi phải giữ đồng bộ: `scheduler.start()` và `mcp/server._init_components()`. Một connector cộng đồng bắt buộc phải sửa 2 file core → đúng định nghĩa vi phạm OCP ở tầng wiring. Đây là điểm khác biệt lớn nhất so với Airbyte/LangChain mà sản phẩm tự so sánh: cả hai đều có cơ chế discovery.

### 🟡 B2-6. Geo probe: hướng đúng, độ phủ hẹp

```python
    DEFAULT_GEO_PROBES = {
        "VN": ["{}", "{} là gì", "{} việt nam", "cách dùng {}", "ứng dụng {}"],
        "DEFAULT": ["{}", "what is {}", "how to use {}", "best {} tools", "{} tutorial"],
    }
```
Cấu trúc đúng ✓ nhưng `DEFAULT` là **tiếng Anh**, không phải trung lập. Mission ở Nhật/Đức probe Google Suggest bằng tiếng Anh → `demand_score` đo nhu cầu của người nói tiếng Anh tại thị trường đó, không phải nhu cầu của thị trường. Hằng số vẫn nằm trong code (`DEFAULT_GEO_PROBES` là class attribute) trong khi triết lý mới nói policy phải ở DB — nên đưa vào `market_lexicons` domain `probe_patterns:{geo}`.

## B.3 Câu hỏi 3: Ba khuyến nghị cho `v0.2.0`

### 🥇 #1 — Đóng hợp đồng Extensible Primitives (~1 ngày) · **giá trị cao nhất**

Đây là việc duy nhất tôi coi là **bắt buộc trước khi public repo cho cộng đồng quốc tế**, vì nó vừa là bug hôm nay (mission Brazil thành Việt Nam) vừa là nền cho mọi mở rộng sau.

1. `PlatformType.register(name)` / `GeoCode.register(code)` — đăng ký tường minh, ghi vào `_value2member_map_`.
2. `_missing_` chuyển sang **strict**: chỉ nhận giá trị đã đăng ký, còn lại `ValueError`.
3. Thêm bộ ISO-3166-1 alpha-2 làm tập hợp lệ sẵn cho `GeoCode` (249 mã, ~2KB) → `BR`, `KR`, `IN`, `MX` hợp lệ ngay, `usa`/`Vietnam` bị chặn.
4. **Xóa cả 13 guard `_value2member_map_`**, thay bằng `resolve_geo()` / `resolve_platform()` trong `domain/` — không bao giờ thay thế âm thầm bằng thị trường khác.
5. Test: `resolve_geo("BR").value == "BR"`; `resolve_platform("reddit")` sau `register` thì được, chưa `register` thì raise; round-trip mission có platform cộng đồng qua DB không mất phần tử.

### 🥈 #2 — `ILanguageDetector` port + policy nạp được theo geo (~1.5 ngày)

Giải quyết bias sâu nhất còn lại (B2-2) và biến "Separation of Mechanism & Policy" từ khẩu hiệu thành kiến trúc.

```python
# application/ports/language_port.py
class ILanguageDetector(ABC):
    @property
    @abstractmethod
    def supported_geos(self) -> set[str]: ...

    @abstractmethod
    def score(self, text: str, geo: GeoCode) -> Optional[float]:
        """0.0–1.0 độ tin là ngôn ngữ thị trường mục tiêu. None = không đánh giá được."""
```
- `VietnameseHeuristicDetector` — bọc nguyên logic 3 tầng hiện có, không mất gì.
- `NullDetector` — trả `None` cho geo chưa có policy (**không** trả `True`).
- `FastTextDetector` — optional extra `[lang]`, phủ 176 ngôn ngữ.

Kèm theo: khi detector trả `None`, `evaluate_quality` **loại `language_precision` khỏi công thức và chuẩn hóa lại trọng số**, ghi flaw `"language verification unavailable for {geo}"`. Đồng thời parameterize `coverage_score` (B2-3) theo số platform thực đăng ký. Hai việc này cùng chạm `quality_evaluator` nên làm chung.

### 🥉 #3 — Capability-based Registry + Connector Auto-Discovery (~2 ngày)

Đóng B2-4, B2-5 và trả lại đúng hình dạng Clean Architecture.

1. `IConnectorRegistry` port trong `application/ports/` → 3 use case không còn import `infrastructure`.
2. Capability Protocol (`ISupportsMacroTrends`, `ISupportsComments`, `ISupportsSuggestions`) + `registry.find_by_capability(...)` → xóa `isinstance(plugin, TikTokPlugin)`.
3. Auto-discovery qua entry points:
```toml
[project.entry-points."ignis.connectors"]
reddit = "ignis_reddit:RedditPlugin"
```
Registry quét entry points khi khởi tạo → cộng đồng `pip install ignis-reddit` là xong, **không sửa file core nào**. Đây là điều làm nên khác biệt Airbyte/LangChain mà sản phẩm đang nhắm tới.
4. Bỏ 7 chỗ truy cập `registry._plugins`.

### Không nên làm ở v0.2.0

**Pluggable scoring algorithms** (bạn có nêu): chưa đáng lúc này. `OpportunityIndex` mới vừa ổn định qua 4 vòng audit và chưa có test golden-file nào bảo vệ. Thêm lớp abstraction lên một công thức chưa có test sẽ nhân bản bug thay vì cô lập nó. Trình tự đúng: **golden-file test cho scoring trước → parameterize hằng số (B2-3) → rồi mới pluggable ở v0.3.0.**

---

## B.4 Đánh giá tổng thể mức Abstraction

| Tầng | Mức | Nhận xét |
|---|---|---|
| `domain/` (entities, value_objects) | 🟢 **Tốt** | Không import ra ngoài. Enum đã mở — chỉ thiếu hợp đồng đăng ký |
| `application/ports/` | 🟡 **Khá** | 4 port đúng hình dạng; thiếu `IConnectorRegistry`, `ILanguageDetector` |
| `application/use_cases/` | 🔴 **Yếu** | 7 import ngược tầng, `isinstance` vào concrete plugin |
| `connectors/` | 🟢 **Tốt** | Port rõ, geo động, đã xóa hardcode VN. Thiếu auto-discovery |
| `harness/` | 🟡 **Khá** | Noise/lexicon đã động hóa tốt; nhưng language policy bất đối xứng, scoring còn magic number |
| `interfaces/` | 🔴 **Yếu** | 13 guard đóng chặn mở rộng; ép geo về VN âm thầm |

**Kết luận cho Câu hỏi 1**: kiến trúc đã đi được **khoảng 70%** đường tới domain-agnostic. Phần từ vựng và policy dữ liệu — phần khó nhìn và tốn công nhất — đã làm **rất tốt**: xóa 37 pattern hardcode, noise động từ DB, geo probe theo vùng, bỏ ký tự chung khỏi bộ nhận diện. Phần còn lại là **30% cuối ở lớp guard và wiring**, và nó rẻ hơn nhiều so với phần đã làm: khoảng 1 ngày cho khuyến nghị #1 là đủ để một developer ở Brazil hay Nhật clone repo về mà không bị ép về Việt Nam.

Một lưu ý về thứ tự công bố: nếu launch Product Hunt trước khi xong #1, hãy ghi rõ trong README rằng **danh sách geo hỗ trợ hiện là 10 mã** (`VN US GLOBAL GB JP TH SG ID DE FR`) thay vì hứa "any ISO-3166 region" — vì `_missing_` khiến `GeoCode("BR")` *trông như* hoạt động trong khi API layer thì không. Hứa hẹn ở tài liệu vượt quá hành vi thật là rủi ro uy tín lớn hơn việc chỉ hỗ trợ 10 nước.
