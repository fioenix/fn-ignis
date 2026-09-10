# Baseline đối soát: source / observation / mission evidence

**Ngày chạy:** 10/09/2026 · **Backend:** PostgreSQL/TimescaleDB (Supabase)
**Kết quả:** `BALANCED`, 14/14 invariant giữ, exit code `0` · **`schema_version`:** `3`
**Lưu ý:** bản baseline đầu tiên của cùng ngày đã bị thay thế — xem mục "Bản sửa" bên dưới.
**Dữ liệu máy đọc:** [`2026-09-10-source-observation-baseline.json`](2026-09-10-source-observation-baseline.json)

Đây là bằng chứng migration lâu dài, không phải ghi chú tạm. Nó tồn tại vì
`sql/008_deduplicate_signal_metrics.sql` từng ghi trong header rằng nó deduplicate `trend_signals`
và giữ dòng sớm nhất làm canonical — và nó không làm cả hai việc đó. Một migration không chứng
minh được nó đã tính đến những gì thì không phân biệt được với một migration lặng lẽ làm mất dữ
liệu. Vì vậy con số đi trước, SQL đi sau.

Bản này đã được sanitize: không chứa title, URL, external ID hay mission title. Bản row-level
(có nêu identity, dùng để tự tay kiểm một phép gộp) nằm ngoài git, đi cùng database backup.

Chạy lại:

```bash
python scripts/migration_reconciliation_audit.py \
  --json-out docs/migrations/<ngày>-source-observation-baseline.json \
  --rows-out .handoff/<ngày>-migration-baseline-rows.json
```

## Bản sửa: gate cũ cân bằng trên một projection bị mất dữ liệu

Bản baseline đầu tiên của ngày 10/09 tuyên bố `BALANCED` với 11 invariant, và tuyên bố đó **sai
tầng**. Nó chứng minh một projection tự nhất quán, không chứng minh toàn corpus được bảo toàn.

Ba lỗi, đã xác nhận:

1. Member của observation, mission và cluster được dựng bằng `set`, nên **multiplicity bị xoá
   trước khi hash**. `digest_of()` giữ được duplicate nếu nhận list — kiểm trực tiếp: `["a"]` và
   `["a","a"]` cho hai digest khác nhau, còn `{"a","a"}` cho đúng digest của `["a"]`. Chính caller
   làm mất dữ liệu.
2. Audit đọc `signal_metrics` chỉ với `(signal_id, captured_at, metric_value)`, **bỏ
   `growth_velocity`**. Projection cũng không khoá `published_at`, `observed_title`, `geo_code` và
   metadata.
3. Kết luận "683 observation sẽ thực sự bị giảm" **sai**. Không constraint nào buộc hai
   observation phải khác nhau theo bộ ba đó. Đo trên corpus thật: các dòng trùng cả
   `(source_url, raw_title, captured_at, metric_value)` mang **3 giá trị `growth_velocity` khác
   nhau** và 2 biến thể metadata — chúng là những lần thu thập thật sự khác nhau. Surrogate
   observation ID mới là thứ giữ chúng riêng biệt.

Gate hiện tại dựng observation theo **legacy lineage**: một observation cho mỗi dòng
`trend_signals`, cộng một cho mỗi điểm `signal_metrics` **không** lặp lại toàn bộ metric payload
của dòng cha. Chỉ bản copy mà `sql/008` tạo ra là được gộp. Member là **multiset**.

## Projection: 10 field được bảo toàn, 4 mất mát có chủ ý

Một observation member được render trên đúng những field này:

`canonical_source_identity` · `observed_at` · `published_at` · **`time_provenance`** ·
`observed_title` · `metric_value` · `growth_velocity` · `geo_code` · `normalized_source_url` ·
`canonical_metadata`

Field bị bỏ phải được khai báo là mất mát có chủ ý kèm lý do, để câu "digest khớp" không bao giờ
có nghĩa là "digest bỏ qua đúng cột đã đổi":

| Field | Lý do |
|---|---|
| `trend_signals.id` | surrogate key, migration cấp lại theo thiết kế |
| `signal_metrics.id` | surrogate key, migration cấp lại theo thiết kế |
| `trend_signals.mission_id` | đã nằm trong digest `mission_associations` |
| `trend_signals.cluster_id` | đã nằm trong digest `cluster_memberships` |

## Digest — bốn tập canonical

SHA-256 trên từng tập đã sort, member là **business identity** chứ không phải surrogate key, và
là **multiset** chứ không phải set. Nhãn `algorithm` trong JSON ghi đúng `sorted multiset`.

| Tập | SHA-256 (16 ký tự đầu) | Member |
|---|---|---|
| sources | `cf7bf6501d87b14b` | 1.927 |
| observations | `df14bd481520ad69` | 18.597 |
| mission_associations | `d87299a59340eb9d` | 1.301 |
| cluster_memberships | `532e7834fd44a2f9` | 15.754 |

## Công thức và aggregate

### Source: 1.927 canonical

Phần này không đổi so với bản trước. Identity là `platform` cộng identifier do platform cấp, đọc
từ metadata connector, URL chỉ là fallback. `raw_title` bị loại: 10 URL trong corpus mang hai
title khác nhau.

| Nguồn identity | Số dòng |
|---|---|
| `metadata_external_id` | 15.790 |
| `url_external_id` | 148 |
| `normalized_url_fallback` | 0 |
| `unresolved` | 0 |
| **Tổng** | **15.938** |

Reason code cho mỗi lần một identity giữ nhiều dòng legacy:

| Reason | Số dòng |
|---|---|
| `repeat_observation_of_one_source` | 14.089 |
| `observed_title_changed` | 287 |
| `url_variant_of_one_source` | 12 |
| `unclassified_identity_collision` | **0** |
| identity chỉ giữ một dòng | 1.550 |
| **Tổng** | **15.938** |

### Observation: 18.597, không dòng nào bị giảm

```
observations = một cho mỗi dòng trend_signals
             + một cho mỗi điểm signal_metrics không lặp lại toàn bộ payload của dòng cha
             = 15.938 + 3.677 − 1.018
             = 18.597
```

| | |
|---|---|
| `trend_signals` rows | 15.938 |
| `signal_metrics` rows | 3.677 |
| signal không có metric point nào | 14.920 |
| bản copy do `sql/008` tạo, được gộp | 1.018 |
| tổng thô, để đối chiếu | 19.615 |
| **observation (multiset)** | **18.597** |
| payload phân biệt được | 18.199 |
| `indistinguishable_observation_multiplicity` | **398** |

398 member đó giống nhau trên cả 9 field được bảo toàn. **Đây không phải phần giảm mà migration
thực hiện** — hai lần thu thập có thể hợp lệ giống nhau trên mọi field, và chỉ surrogate
observation ID phân biệt chúng. Con số được báo để bản chạy sau migration xác nhận multiplicity
đó vẫn còn, không phải để gộp bất cứ thứ gì.

Kỳ vọng định hướng trước khi chạy là observation về lại **18.212**. Kết quả thật là **18.597**, và
chênh lệch có lý do: 18.212 là số **payload triple phân biệt được** theo projection cũ, còn 18.597
là số **collection event được bảo toàn**. Overlap `sql/008` vẫn đúng 1.018 sau khi thêm
`growth_velocity` — mọi bản copy do migration đó tạo cũng khớp cả velocity. Con số gần 18.212 nhất
trong bản mới là 18.199, tức số payload phân biệt được sau khi projection đã gồm velocity, geo,
title và metadata.

### Time provenance: 3 bucket, cộng lại đúng 18.597

| Bucket | Observation |
|---|---|
| `exact_ingestion` | 1.479 |
| `legacy_publish_only` | 17.118 |
| `unknown` | 0 |
| **Tổng** | **18.597** |

Đây là khoảng trống mà bản trước để hở, và nó nghiêm trọng hơn nhãn JSON: projection cũ đưa
`captured_at` thẳng vào một field **mang tên `observed_at`**, không có `time_provenance`. Với
YouTube và Google feed lịch sử, `captured_at` chính là publish time — đúng thứ đã quyết là không
được giả làm ingestion time. Schema test chỉ chứng minh cột và constraint tồn tại, nên migration
vẫn có thể gắn sai provenance cho cả 18.597 observation mà bốn digest đều khớp.

Provenance là field thứ 10 của digest, nên việc gắn lại nhãn làm digest lệch ngay. Test chứng minh
điều đó gọi **thẳng serializer**, giữ nguyên mọi field khác và chỉ đổi `time_provenance` — bản test
đầu tiên đổi platform để dịch bucket, kéo theo đổi cả canonical identity, URL, metadata và
`observed_at`, nên nó sẽ khác digest **ngay cả khi bỏ hẳn** `time_provenance`. Verify ngược: xoá
`time_provenance` khỏi member thì đúng một test fail, chính test isolation đó.

**Rule suy ra từ bằng chứng, không từ mốc ngày tự chọn.** `sql/015` ghi lại chính xác code path
nào từng viết publish time vào `captured_at` — hai đường YouTube và feed Google Trends — rồi
backfill `published_at` từ giá trị của platform trong metadata cho YouTube, và chuyển `captured_at`
sang cho các dòng feed Google. Vì vậy dòng viết **trước** bản sửa để lại `published_at` bằng
`captured_at`, còn dòng viết **sau** có `captured_at` là ingestion và `published_at` khác. Đẳng
thức đó là signature, và nó đo được:

| platform | n | `published_at == captured_at` | khác | NULL |
|---|---|---|---|---|
| youtube | 14.869 | **14.737** | 132 | 0 |
| google feed | 72 | **72** | 0 | 0 |
| google probe | 117 | 0 | 0 | 117 |
| threads | 517 | 0 | 486 | 31 |
| tiktok | 333 | 0 | 0 | 333 |
| reels | 30 | 0 | 29 | 1 |

Dòng probe của Google được `sql/015` loại khỏi backfill vì chúng luôn được đóng dấu ingestion time
và không có khái niệm publish, nên chúng là `exact_ingestion`.

**Provenance quyết theo từng event, không theo dòng.** `trend_signals` là snapshot hiện tại và
có thể ghi lại: cả hai repository đều cập nhật `captured_at` mỗi lần poll
(`postgres_repository.py` và `sqlite_repository.py`, nhánh UPDATE), trong khi mỗi dòng
`signal_metrics` giữ `captured_at` của đúng lần poll đã ghi nó. Nên một dòng cha có thể đang mang
ingestion time chứng minh được, còn metric history của nó vẫn chứa point đóng dấu publish time.
Quyết một lần cho cả dòng là xếp sai point đó.

Đo mức ảnh hưởng bằng cách chạy cả hai cách derivation trên corpus thật: **13 observation chuyển
`legacy_publish_only` → `exact_ingestion`**, không có chiều ngược lại. Tổng vẫn 18.597. Con số nhỏ,
nhưng audit phải đúng theo thiết kế chứ không đúng nhờ hình dạng dữ liệu hiện tại.

Trong corpus hiện tại có **1 signal** mà metric history trộn hai loại clock, và **0** ca "dòng cha
exact nhưng point legacy". Cả hai đều được test phủ, vì cấu trúc cho phép chúng xảy ra.

Ở đâu `captured_at` là publish time thì `observed_at` là **NULL**. Thời điểm thu thập thật chưa
từng được ghi, và đóng dấu publish time vào một cột tên `observed_at` chính là phép thay thế mà
toàn bộ việc này tồn tại để chặn.

### Mission evidence: 1.301, phục dựng chính xác toàn bộ

| | |
|---|---|
| dòng mission-attached | 1.301 |
| phục dựng chính xác | 1.301 |
| identity không resolve được | 0 |
| mission reference dangling | 0 |
| **mission chứa nhiều dòng cho cùng một identity** | **2** |

Cả 1.301 dòng đều ánh xạ tới đúng một identity với mission tồn tại. Nhưng 2 mission quan sát cùng
một source nhiều hơn một lần — đúng trường hợp mà constraint phải là
`UNIQUE (mission_id, observation_id)`, không phải `UNIQUE (mission_id, source_id)`.

1.301 chỉ là những gì **đã được persist**. Evidence mà mission thu trong bộ nhớ nhưng chưa bao giờ
gắn vào DB thì không phục dựng được, và audit không đoán.

### Cluster membership: 172 identity nằm nhiều cluster

| | |
|---|---|
| ánh xạ chắc chắn | 15.754 |
| cluster reference dangling | 0 |
| không có cluster | 184 |
| **Tổng** | **15.938** |
| **membership (multiset)** | **15.754** |
| payload phân biệt được | 15.653 |
| `indistinguishable_membership_multiplicity` | 101 |
| **identity nằm ở nhiều hơn một cluster** | **172** |

Membership giờ bằng đúng số dòng ánh xạ chắc chắn: **không membership nào bị xoá chỉ vì hai
observation có cùng business payload**. Con số 586 trong bản trước là hệ quả của cùng lỗi `set`
đã nêu ở mục "Bản sửa".

172 trường hợp này là bằng chứng đo được cho quyết định đã chốt: cluster membership thuộc
observation, không thuộc source. Đặt `cluster_id` trên bảng source thì 172 identity này buộc phải
chọn một cluster và bỏ phần còn lại.

## 14 invariant

Tất cả đều giữ. Audit exit non-zero nếu bất kỳ điều nào sau đây bị vi phạm:

1. Mọi dòng `trend_signals` rơi vào đúng một resolution bucket.
2. Không dòng nào không resolve được identity.
3. Mọi phép gộp source có reason code (0 `unclassified_identity_collision`).
4. Dòng đã resolve = identity một dòng + dòng trong identity đã gộp.
5. Số observation = số dòng + số metric point − số bản copy `sql/008` được gộp.
6. Số payload phân biệt được không vượt quá multiset observation.
7. Ba bucket `time_provenance` cộng lại bằng đúng số observation.
8. Số cluster membership không vượt quá số dòng ánh xạ tới một cluster.
9. Không metric point nào trỏ tới `trend_signals` row không tồn tại.
10. Dòng mission-attached = exact + unresolved + dangling.
11. Không dòng nào trỏ tới mission không tồn tại.
12. Mọi dòng = cluster chắc chắn + dangling + không cluster.
13. Không dòng nào trỏ tới cluster không tồn tại.
14. Dòng đã resolve = identity một dòng + dòng trong identity đã gộp.

## Guard: read-only do engine cưỡng chế

Postgres reader chạy `SET TRANSACTION READ ONLY`; SQLite mở `file:...?mode=ro`. Kiểm bằng cách
thử ghi thật, mỗi lệnh một session riêng để một lần abort không che lệnh sau:

```
DDL CREATE : refused -> ReadOnlySqlTransaction: cannot execute CREATE TABLE in a read-only transaction
DML UPDATE : refused -> ReadOnlySqlTransaction: cannot execute UPDATE in a read-only transaction
```

Sau khi kiểm: corpus vẫn 15.938 dòng, bảng probe không tồn tại. Có test khẳng định `DELETE` trên
SQLite raise `readonly`, và một test so file byte-by-byte trước/sau khi audit chạy.

## Điều kiện đối soát sau migration

So bản chạy sau với JSON này. Ba điều kiện để coi là thành công:

1. Không dòng legacy hay metric point nào biến mất. Không có phần gộp nào được cho phép: 398
   observation và 101 cluster membership có payload giống nhau là **multiplicity phải bảo toàn**,
   không phải phần được gộp.
2. Mọi observation trỏ đúng một source.
3. Mọi phép gộp source vẫn có reason code, và `unclassified_identity_collision` vẫn bằng 0.

Cả bốn digest phải **khớp tuyệt đối**, và số member phải khớp đúng: 1.927 source, 18.597
observation, 1.301 mission association, 15.754 cluster membership. Ba bucket provenance phải khớp
đúng 1.479 / 17.118 / 0. Migration không được đổi tập
nào trong bốn tập đó. Nếu một digest lệch, phải chỉ ra được field nào đổi và vì sao — và nếu lý do
là một field bị bỏ khỏi projection thì nó phải vào bảng mất mát có chủ ý trước, không phải sau.
