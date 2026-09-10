# Baseline đối soát: source / observation / mission evidence

**Ngày chạy:** 10/09/2026 · **Commit:** `8f9ee89` · **Backend:** PostgreSQL/TimescaleDB (Supabase)
**Kết quả:** `BALANCED`, 11/11 invariant giữ, exit code `0`
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

## Digest — bốn tập canonical

SHA-256 trên từng tập đã sort, các member là **business identity** chứ không phải surrogate key.
Digest khoá trên `trend_signals.id` sẽ đổi ngay khi migration ghi lại dòng, tức là mất giá trị
đúng lúc cần nó nhất. Khoá trên platform identity cộng giá trị quan sát thì bản chạy sau migration
tính lại được cùng một digest từ bảng mới.

| Tập | SHA-256 | Số member |
|---|---|---|
| sources | `cf7bf6501d87b14b2ed268e9cc439cc7a979b6a272e6c135d2548e0c88733d47` | 1.927 |
| observations | `676e7c5a5e144f07339013408140fcc52bd2136a3e155780d1d7ea9194166507` | 17.529 |
| mission_associations | `7124ebccf448647e1bbf5d73ace556649782cebdbfe0ddf1fe19d3ca1acc7c2d` | 1.301 |
| cluster_memberships | `c8da41dd79af9d17b18231b747bf0ce53dbd9dd8e379e41ff67496d6a9e942d0` | 15.168 |

## Công thức và aggregate

### Source: 1.927 canonical

Identity là `platform` cộng identifier do platform cấp, đọc từ metadata connector, URL chỉ là
fallback. `raw_title` bị loại: 10 URL trong corpus mang hai title khác nhau, nên title là thứ được
quan sát về một source, không phải thành phần định danh nó.

| Nguồn identity | Số dòng |
|---|---|
| `metadata_external_id` | 15.790 |
| `url_external_id` | 148 |
| `normalized_url_fallback` | 0 |
| `unresolved` | 0 |
| **Tổng** | **15.938** |

Ba con số từng được nêu trước đây đều không phải kết quả của chính sách này: **1.939** đếm theo
`(platform, source_url, raw_title)`, vẫn dùng title làm key; **1.929** đếm theo
`(platform, source_url)`, chưa gộp URL variant và chưa tách hai loại object TikTok
(`/video/<id>` là một video, `/tag/<hashtag>` là một surface).

Reason code cho mỗi lần một identity giữ nhiều dòng legacy:

| Reason | Số dòng |
|---|---|
| `repeat_observation_of_one_source` | 14.089 |
| `observed_title_changed` | 287 |
| `url_variant_of_one_source` | 12 |
| `unclassified_identity_collision` | **0** |
| identity chỉ giữ một dòng | 1.550 |
| **Tổng** | **15.938** |

### Observation: 18.212, và 683 dòng sẽ gộp lại

```
observations = distinct(signal_id, captured_at, metric_value)
               over signal_metrics UNION trend_signals
             = 15.938 + 3.292 − 1.018 trùng
             = 18.212
```

| | |
|---|---|
| `trend_signals` rows | 15.938 |
| `signal_metrics` rows | 3.677 |
| signal không có metric point nào | 14.920 |
| triple xuất hiện ở cả hai bảng | 1.018 |
| tổng thô, để đối chiếu | 19.615 |
| **distinct theo business identity** | **17.529** |
| **sẽ gộp khi bỏ surrogate id** | **683** |

683 dòng này chia sẻ cùng source, cùng `captured_at` và cùng `metric_value`, nên khi
`trend_signals.id` không còn thì chúng không phân biệt được nữa. Đây là phần giảm **thật** mà
migration sẽ thực hiện, nên nó có số riêng. Nó lộ ra vì digest có 17.529 member trong khi
observation là 18.212 — một chênh lệch mà nếu bỏ qua thì 683 dòng sẽ biến mất không ai biết.

Con số **18.195** từng được nêu không tái hiện được. Năm định nghĩa đã thử: 19.615 (tổng thô),
16.276 (union theo `signal_id, captured_at`), 18.597, 18.365, và 18.212 (định nghĩa đang dùng).

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
| distinct theo business identity | 15.168 |
| sẽ gộp khi bỏ surrogate id | 586 |
| **identity nằm ở nhiều hơn một cluster** | **172** |

172 trường hợp này là bằng chứng đo được cho quyết định đã chốt: cluster membership thuộc
observation, không thuộc source. Đặt `cluster_id` trên bảng source thì 172 identity này buộc phải
chọn một cluster và bỏ phần còn lại.

## 11 invariant

Tất cả đều giữ. Audit exit non-zero nếu bất kỳ điều nào sau đây bị vi phạm:

1. Mọi dòng `trend_signals` rơi vào đúng một resolution bucket.
2. Không dòng nào không resolve được identity.
3. Mọi phép gộp source có reason code (0 `unclassified_identity_collision`).
4. Dòng đã resolve = identity một dòng + dòng trong identity đã gộp.
5. Union observation = a + b − overlap.
6. Tập observation theo business identity không lớn hơn tập theo surrogate key.
7. Không metric point nào trỏ tới `trend_signals` row không tồn tại.
8. Dòng mission-attached = exact + unresolved + dangling.
9. Không dòng nào trỏ tới mission không tồn tại.
10. Mọi dòng = cluster chắc chắn + dangling + không cluster.
11. Không dòng nào trỏ tới cluster không tồn tại.

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

1. Không dòng legacy hay metric point nào biến mất ngoài 683 observation và 586 cluster
   membership đã được khai báo trước là sẽ gộp.
2. Mọi observation trỏ đúng một source.
3. Mọi phép gộp source vẫn có reason code, và `unclassified_identity_collision` vẫn bằng 0.

Digest `sources` và `mission_associations` phải **khớp tuyệt đối**: migration không được đổi tập
source canonical hay tập mission association. Digest `observations` và `cluster_memberships` được
phép đổi chỉ khi số member khớp đúng con số distinct-theo-business-identity ghi ở trên.
