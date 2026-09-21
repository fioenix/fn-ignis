# Baseline đối soát: source / observation / mission evidence

**Ngày chạy:** 10/09/2026 · **Backend:** PostgreSQL/TimescaleDB (Supabase)
**Kết quả:** `BALANCED`, 14/14 invariant giữ, exit code `0` · **`schema_version`:** `7`
(sinh lại sau khi canonical hoá route identity — xem cuối mục Digest)
**Lưu ý:** bản baseline đầu tiên của cùng ngày đã bị thay thế — xem mục "Bản sửa" bên dưới.
**Dữ liệu máy đọc:** [`2026-09-10-source-observation-baseline.json`](2026-09-10-source-observation-baseline.json)

Đây là bằng chứng migration lâu dài, không phải ghi chú tạm. Nó tồn tại vì
`sql/008_deduplicate_signal_metrics.sql` từng ghi trong header rằng nó deduplicate `trend_signals`
và giữ dòng sớm nhất làm canonical — và nó không làm cả hai việc đó. Một migration không chứng
minh được nó đã tính đến những gì thì không phân biệt được với một migration lặng lẽ làm mất dữ
liệu. Vì vậy con số đi trước, SQL đi sau.

**Không dùng file JSON đã track làm baseline cho production.** Nó mô tả snapshot corpus dùng để
review và diễn tập ngày 10/09/2026. Bất kỳ observation nào vào sau snapshot đó đều phải làm digest
production khác đi. Reference cho lần apply thật phải được sinh từ **chính snapshot lấy sau khi đã
quiesce ingress**; một mismatch với file cũ khi corpus đã đổi là verifier làm đúng việc, không phải
lỗi migration.

Bản này đã được sanitize: không chứa title, URL, external ID hay mission title. Bản row-level
(có nêu identity, dùng để tự tay kiểm một phép gộp) nằm ngoài git, đi cùng database backup.

Chạy lại:

```bash
python scripts/migration_reconciliation_audit.py \
  --json-out docs/migrations/<ngày>-source-observation-baseline.json \
  --rows-out .handoff/<ngày>-migration-baseline-rows.json
```

## Production cutover runbook

**Đã chạy 20/09/2026.** Cutover hoàn tất, verifier trả `VERIFIED` với bốn digest khớp tuyệt đối,
runtime mới đã khởi động và ingress theo lịch đã mở lại. Mục này vẫn là thứ tự canonical cho lần
sau; bằng chứng của lần chạy nằm trong `BACKLOG.md`.

Đây là thứ tự canonical. Gate runtime và guard của pruner chỉ làm hệ thống fail closed nếu ai đó
vi phạm thứ tự; chúng không phải giấy phép đổi thứ tự.

`scripts/t020_cutover.py` chạy các bước 2–8 dưới đây theo đúng thứ tự này và dừng ở gate đầu tiên
không đạt. Nó tồn tại vì một gate trong danh sách này không có ai gác: `backfill_observations.py
--dry-run` exit 0 dù bốn member count khớp baseline, lệch baseline, hay không tìm thấy schema đích,
nên gate ở bước 6 chỉ nằm trong sự chú ý của người đọc. Script so bốn con số bằng giá trị, đọc lại
snapshot bằng `pg_restore --list` thay vì tin exit code của `pg_dump`, hash toàn bộ legacy
projection ba lần — trước snapshot, sau snapshot và ngay trước khi ghi — rồi dừng nếu có bất kỳ
khác biệt nào, buộc một lần chạy `--start-at` phải khớp journal của lần chạy trước, và ghi journal
JSON cho mọi bước.

**Journal không thể bị ghi đè:** mỗi lần chạy lấy một tên riêng dạng
`t020-run-<YYYYmmdd-HHMMSS>-<NNN>.json`, trong đó `NNN` tăng lên khi tên đã có người giữ, và file
được mở theo chế độ độc quyền (`O_EXCL`) trước khi ghi byte đầu tiên. Hai lần chạy cùng `run-dir`
bắt đầu trong cùng một giây vì thế nhận hai file khác nhau; bằng chứng của lần chạy trước giữ
nguyên từng byte. Nếu cả 999 số thứ tự trong một giây đều đã bị chiếm, lần chạy mới dừng với exit
code 2 và không thay thế file nào.

Không kết nối nào bị từ chối vì tên host. Preflight đo đúng thứ nó cần: một double 17 chữ số có
nghĩa về tới nơi còn nguyên. Dùng một DSN duy nhất cho audit, backfill và verification, vì hai lần
đọc cùng một corpus qua hai đường có thể cho hai digest khác nhau.

```bash
export PRODUCTION_DSN='<DSN nào qua được preflight>'
python scripts/t020_cutover.py --dsn "$PRODUCTION_DSN"
```

Trên macOS, `psql`/`pg_dump`/`pg_restore` đến từ `libpq` keg-only, nên không có trên PATH mặc định:
`brew install libpq` rồi thêm `/opt/homebrew/opt/libpq/bin` vào PATH. Script tự tìm ở đó nếu PATH
thiếu, và từ chối chạy khi `pg_dump` cũ hơn server.

1. Merge PR chứa runtime mới. Có thể stage/build artifact trước, nhưng **không khởi động runtime
   mới**.
2. Quiesce toàn bộ ingress và runtime cũ đang có khả năng ghi.
3. Lấy snapshot. Lần cutover 20/09/2026 chạy `pg_dump` qua chính pooler session mode và nhận về
   archive 844 entry. Ghi chép từ lần diễn tập nói rằng pooler từ chối ở startup protocol, và điều
   đó không đúng với lần chạy này. Nếu endpoint đang dùng thật sự từ chối thì lấy snapshot bằng
   đường khác, rồi truyền `--snapshot` để script chỉ kiểm tra rằng nó đọc lại được.
4. Sinh baseline từ bản snapshot vừa lấy, tốt nhất trên một restore read-only disposable. Nếu audit
   chạy trên database production đang quiesce, phải chứng minh nó vẫn byte-equivalent với snapshot.
   Baseline production và row-level report đều ở `.handoff/` hoặc đi cùng backup, không commit:

   ```bash
   python scripts/migration_reconciliation_audit.py \
     --dsn "$SNAPSHOT_DSN" \
     --json-out .handoff/production-source-observation-baseline.json \
     --rows-out .handoff/production-source-observation-rows.json
   ```

   Chỉ tiếp tục khi audit trả `BALANCED` và exit `0`.
5. Apply `sql/016_source_observation_model.sql`. Migration này chỉ tạo schema, không di chuyển
   dữ liệu.
6. Chạy dry run trên production đang quiesce; bốn member count phải bằng baseline vừa sinh:

   ```bash
   python scripts/backfill_observations.py --dsn "$PRODUCTION_DSN" --dry-run
   ```

7. Apply backfill. Writer chạy trong một transaction và dùng UUIDv5 theo legacy lineage:

   ```bash
   python scripts/backfill_observations.py --dsn "$PRODUCTION_DSN" --apply
   ```

8. Verify bằng **baseline production vừa sinh**, không dùng JSON đã track:

   ```bash
   python scripts/post_migration_verification.py \
     --dsn "$PRODUCTION_DSN" \
     --baseline .handoff/production-source-observation-baseline.json
   ```

   Chỉ `VERIFIED`, exit `0`, raw/projected observation counts bằng nhau, bốn member count và bốn
   digest khớp tuyệt đối mới mở bước sau.
9. Khởi động runtime mới. Xác nhận repository mở được và health check xanh.
10. Mở lại ingress.

Nếu bất kỳ bước nào từ 4 đến 9 không đạt điều kiện, giữ ingress đóng và dừng. Không dùng tracked
baseline để "sửa" mismatch, không bỏ qua foreign observations, và không chạy runtime mới để thử
xem gate có cứu được không.

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

## Bản sửa v4: đường phân giải không được tham gia identity

Bản v3 khoá identity theo **tên field metadata** chứa identifier, tức khoá theo cách audit tìm ra
identifier thay vì theo bản chất object. Hệ quả đo được: `youtube:video_id:x` và `youtube:video:x`
là cùng một video, nhưng bị tính thành hai canonical source. Corpus có **3 cặp** như vậy.

Sửa: identity dùng namespace của object; đường phân giải chuyển sang cột riêng
`sources.identity_source` với ba giá trị `metadata_external_id` / `url_external_id` /
`normalized_url_fallback`. Có test trực tiếp cho cả hai chiều — hai đường phân giải cùng object
phải cho một identity, còn `tiktok:tag:12345` và `tiktok:video:12345` phải khác nhau.

Kèm theo là một sửa về kiến trúc, không phải về số: policy trước đây nằm trong chính script audit.
Nếu commit persistence viết lại mapping thì đó là **định nghĩa identity thứ hai**, và audit sẽ đo
một corpus mà writer không còn tạo ra. Policy giờ nằm ở `src/ignis/domain/source_identity.py`;
audit, backfill và live write path gọi cùng một resolver. Baseline v4 này được sinh bằng chính
resolver đó.

Đổi gì:

| | v3 | v4 |
|---|---|---|
| sources | 1.927 | **1.924** |
| observations | 18.597 | 18.597 |
| provenance `exact` / `legacy` / `unknown` | 1.479 / 17.118 / 0 | không đổi |
| mission_associations | 1.301 | 1.301 |
| cluster_memberships | 15.754 | 15.754 |
| identity nằm nhiều cluster | 172 | **175** |
| `repeat_observation_of_one_source` | 14.089 | **14.095** |
| digest | cả bốn | **cả bốn đổi** |

Cả bốn digest đổi vì identity là thành phần đầu tiên của mọi member trong cả bốn tập. Số member
thì chỉ `sources` đổi, và đúng bằng 3 — không có bucket nào khác dịch chuyển theo.

## Bản sửa v5: route phân giải thuộc lần quan sát, không thuộc source

v4 để `identity_source` trên bảng `sources`. Sai theo đúng số đo đã dùng để chốt v4: ba video
YouTube cùng một canonical source đã vào corpus bằng **hai route khác nhau**, nên một cột ở tầng
source chỉ giữ được một route và làm mất route còn lại. Chính docstring của resolver cũng ghi rằng
mechanism được record theo từng observation.

Sửa: `sources` còn đúng ba cột — `id`, `platform`, `external_id`. `identity_source` chuyển xuống
`observations`, `NOT NULL`, `CHECK` ba giá trị `metadata_external_id` / `url_external_id` /
`normalized_url_fallback`, và trở thành **field thứ 11** của projection observation.

Cùng lúc bỏ `canonical_url` khỏi `sources`: URL là thứ một lần quan sát báo về, corpus đã có một
source xuất hiện dưới hai biến thể URL, nên cột đó sẽ thành cache "URL mới nhất" không có rebuild
contract. Citation dùng `observation.source_url`; canonical locator, nếu cần, derive từ
`(platform, external_id)`.

Điểm phân giải mỗi metric point: một điểm `signal_metrics` **thừa hưởng** route của dòng cha, vì
bảng đó không lưu metadata lẫn URL — không có gì trên chính điểm đó để phân giải. Hai dòng của
cùng một source vẫn có thể khác route, và đó chính là trường hợp field này tồn tại để giữ.

| | v4 | v5 |
|---|---|---|
| field trong projection | 10 | **11** |
| sources | 1.924 | 1.924 |
| observations | 18.597 | 18.597 |
| mission_associations | 1.301 | 1.301 |
| cluster_memberships | 15.754 | 15.754 |
| digest `sources` | `69d72aee192bf526` | **giữ nguyên** |
| ba digest còn lại | | **đổi** |

`sources` giữ nguyên vì source member chỉ gồm identity. Ba digest kia đổi vì member của chúng
chứa observation member.

## Bản sửa v6: digest không được phụ thuộc vào session setting

Phát hiện trong lần diễn tập trên bản sao disposable: cùng một corpus, đọc qua hai kết nối, cho
hai digest observation khác nhau. Ba digest kia khớp.

Nguyên nhân: pooler của Supabase trả `extra_float_digits = 0`, tức làm tròn `double` về 15 chữ số
có nghĩa. Giá trị `262600000.00000003` trong `signal_metrics` về tới client thành `262600000.0`.
Bản sao chạy Postgres mặc định (`extra_float_digits = 1`, shortest round-trip) nên giữ đúng giá
trị. Đúng **15 member** lệch, tất cả đều là metric point — vì vậy mission và cluster digest, vốn
chỉ dựng từ dòng cha, không đổi.

Một chi tiết đáng nhớ khi kiểm: câu
`SELECT count(*) FROM signal_metrics WHERE metric_value <> metric_value::text::float8` trả **0**
trên chính kết nối đang mất chính xác. Text *tự* round-trip trong phạm vi một session không có
nghĩa là text đó đúng — phép kiểm đó không phát hiện được gì.

Sửa: cả ba công cụ — audit, backfill, verifier — đều `SET extra_float_digits = 3` ngay khi mở
kết nối Postgres, nên độ chính xác không còn phụ thuộc mặc định của server. Digest observation
đổi từ `b19e7385bf28c51c` sang `301dd36c688c68de`; ba digest còn lại và toàn bộ member count giữ
nguyên `1.924 / 18.597 / 1.301 / 15.754`.

Bài học rộng hơn con số: baseline v5 **không sai ở chỗ dữ liệu**, nó sai ở chỗ *không thể tái lập
ở nơi khác*. Một digest đối soát mà đổi theo session setting thì không đối soát được gì.

## Projection: 11 field được bảo toàn, 4 mất mát có chủ ý

Một observation member được render trên đúng những field này:

`canonical_source_identity` · `observed_at` · `published_at` · **`time_provenance`** ·
`observed_title` · `metric_value` · `growth_velocity` · `geo_code` · `normalized_source_url` ·
`canonical_metadata` · **`identity_source`**

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
| sources | `0eca4a53c92b73d2` | 1.924 |
| observations | `08ecb119070f04d8` | 18.597 |
| mission_associations | `c92fee13d5937b8e` | 1.301 |
| cluster_memberships | `c67c80103be5b144` | 15.754 |

Digest v3 không còn dùng được: identity là thành phần đầu tiên của mọi member trong cả bốn tập,
nên đổi chính sách identity thì đổi cả bốn chuỗi băm. Sang v5, `sources` giữ nguyên
`69d72aee192bf526` — source member chỉ gồm identity, mà identity không đổi — còn ba digest kia
đổi vì member của chúng chứa observation member, nơi `identity_source` vừa trở thành field thứ 11.
Số member không đổi ở cả bốn tập.

Bản `schema_version` 7 đổi cả bốn digest, lần này vì chính chuỗi `external_id`. Route không còn được phép làm
biến dạng identifier: Creative Center ghi hashtag là `#aothun` trong metadata nhưng `/tag/aothun`
trong URL, còn explore URL của Google Trends percent-encode đúng cái keyword mà metadata bên cạnh
để nguyên. Sau khi canonical hoá, **110 dòng** trong corpus đổi chuỗi identity — 58 TikTok, 52
Google — và **61 identity** đổi tên. Không dòng nào gộp vào dòng khác: trong corpus này chưa có
object nào từng đến bằng cả hai route, nên lỗi là lỗi tiềm ẩn chứ chưa gây trùng. Số canonical
source vẫn là 1.924 trước và sau.

## Công thức và aggregate

### Source: 1.924 canonical

Identity là `platform`, cộng namespace của object, cộng identifier do platform cấp:
`external_id` mang sẵn dạng `"<kind>:<value>"`. `raw_title` bị loại — 10 URL trong corpus mang
hai title khác nhau, nên title là thứ được quan sát về một source chứ không định danh nó.

Bản v3 đếm 1.927 vì nó khoá identity theo **tên field metadata** đã chứa identifier. Tên field là
cách audit tìm ra identifier, không phải bản chất object: cùng một video YouTube vào corpus hai
lần — một lần có `video_id` trong metadata, một lần chỉ parse được từ URL — bị tính thành hai
canonical source. Có 3 cặp như vậy, và 1.927 − 3 = **1.924**. Đường phân giải vẫn được ghi và
không tham gia key; v5 đặt nó ở `observations.identity_source`, vì route thuộc lần quan sát.

| Nhãn connector | Namespace |
|---|---|
| YouTube `video_id`, `?v=`, `youtu.be/` | `video` |
| TikTok `item_id`, `/video/` | `video` |
| TikTok `hashtag`, `/tag/` | `tag` |
| Threads `post_id`, `/post/`, `/t/` | `post` |
| Reels `reel_id`, `/reel/`, `/p/` | `reel` |
| Google `keyword`, `probe_keyword`, `?q=` | `keyword` |

Namespace nằm **trong** key chứ không nằm cạnh: trên TikTok, một hashtag tên `12345` và item
`12345` là hai object khác nhau, nên gộp chúng vào một cột là điều kiện để
`UNIQUE (platform, external_id)` trở thành identity đầy đủ thay vì gần đầy đủ.

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
| `repeat_observation_of_one_source` | 14.095 |
| `observed_title_changed` | 287 |
| `url_variant_of_one_source` | 12 |
| `unclassified_identity_collision` | **0** |
| identity chỉ giữ một dòng | 1.544 |
| **Tổng** | **15.938** |

So với v3, `repeat_observation_of_one_source` tăng 14.089 → 14.095 và số identity một dòng giảm
1.550 → 1.544: đúng 6 dòng của 3 cặp vừa nhập về chung identity.

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

### Cluster membership: 175 identity nằm nhiều cluster

| | |
|---|---|
| ánh xạ chắc chắn | 15.754 |
| cluster reference dangling | 0 |
| không có cluster | 184 |
| **Tổng** | **15.938** |
| **membership (multiset)** | **15.754** |
| payload phân biệt được | 15.653 |
| `indistinguishable_membership_multiplicity` | 101 |
| **identity nằm ở nhiều hơn một cluster** | **175** |

Membership giờ bằng đúng số dòng ánh xạ chắc chắn: **không membership nào bị xoá chỉ vì hai
observation có cùng business payload**. Con số 586 trong bản trước là hệ quả của cùng lỗi `set`
đã nêu ở mục "Bản sửa".

175 trường hợp này là bằng chứng đo được cho quyết định đã chốt: cluster membership thuộc
observation, không thuộc source. Đặt `cluster_id` trên bảng source thì 175 identity này buộc phải
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

Cả bốn digest phải **khớp tuyệt đối**, và số member phải khớp đúng: 1.924 source, 18.597
observation, 1.301 mission association, 15.754 cluster membership. Ba bucket provenance phải khớp
đúng 1.479 / 17.118 / 0. Migration không được đổi tập
nào trong bốn tập đó. Nếu một digest lệch, phải chỉ ra được field nào đổi và vì sao — và nếu lý do
là một field bị bỏ khỏi projection thì nó phải vào bảng mất mát có chủ ý trước, không phải sau.
