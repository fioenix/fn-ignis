# fn-ignis

Ignis là bộ công cụ tự lưu trữ để nghiên cứu thị trường từ dữ liệu social theo từng nhiệm vụ
được chỉ định. Nó giúp người dùng tự thu thập chứng cứ có thể kiểm tra từ các nguồn tiếp cận
được, rồi phản biện giả thuyết thị trường trước khi ra quyết định. Hai năng lực hoạt động độc
lập: thu thập có thể kết thúc bằng một khung chứng cứ; phân tích có thể kết thúc bằng báo cáo
thiếu chứng cứ thay vì cố đưa ra kết luận.

**Ranh giới phát hành:** Nhánh này đang triển khai Spec 011 và chưa được phát hành. Mã nguồn
và image v0.7.0 đã công bố vẫn thuộc kiến trúc Dual-Track cũ; chúng không có bộ 52 tool theo
nhiệm vụ được mô tả ở đây. Không dùng image đã phát hành để kiểm chứng nhánh này.

## Hợp đồng sản phẩm

Ignis chỉ bắt đầu khi có yêu cầu thăm dò một nguồn hoặc một nhiệm vụ nghiên cứu đã xác nhận.
Không có worker chạy nền, bản tin khám phá hằng ngày, hay kho dữ liệu baseline tự tích lũy.
Mỗi nhiệm vụ ghi lại câu hỏi, phạm vi, nguồn, điều kiện dừng và kết quả của từng kênh. Phân
tích vận dụng Outcome, Design và Critical thinking: xác định quyết định cần đưa ra, hiểu bối
cảnh người dùng, chủ động tìm chứng cứ phản bác và công khai khoảng trống.

Kết luận thị trường cần khung chứng cứ hiện hành đã được đánh giá và Claim Ledger được lưu.
Mỗi nhận định phải truy được quan sát gốc, chứng cứ ngược chiều, giới hạn và điều kiện khiến
kết luận thay đổi. Kênh không truy cập được không đồng nghĩa với nhu cầu bằng không. Dataset
người dùng tải lên hoặc mua từ bên ngoài chỉ là bối cảnh nếu chưa có xuất xứ và đánh giá gắn
với nhiệm vụ. Xem [Spec 011](specs/011-evidence-grounded-product-reset/spec.md) và
[hợp đồng công khai](specs/011-evidence-grounded-product-reset/contracts/mission-bound-public-surface.md).

Ignis không lưu danh tính tác giả: username, ID tài khoản, link hồ sơ, ảnh đại diện, handle trong
link và trong @mention đều bị loại bỏ trước khi lưu; thay vào đó, một marker theo từng nhiệm vụ cho
biết có bao nhiêu người nói khác nhau. Ignis chỉ nêu tên những tài khoản mà người yêu cầu khai báo
cho nhiệm vụ bằng `set_mission_declared_accounts`. Tên người viết trong nội dung tự do không bị loại
bỏ. Xem [Spec 015](specs/015-no-author-identity-at-rest/spec.md).

## Cài đặt từ mã nguồn

Cần Python 3.11 trở lên. Chạy `./scripts/bootstrap.sh` trong checkout mã nguồn. Script tạo
môi trường Python và SQLite cục bộ, nạp từ vựng, cấu hình các MCP client được hỗ trợ và kiểm
tra tổng hợp. Credentials và phiên đăng nhập social thực tế là tùy chọn, phải do người vận
hành cho phép. Kết quả kiểm tra tổng hợp không chứng minh nguồn live truy cập được.

Cây mã nguồn hiện có migration tới `sql/034_tiktok_attribution.sql`. Migration 034 nạp sẵn mẫu câu
ghi công tác giả của TikTok, dùng để bỏ câu ghi công khỏi trích đoạn khi tìm kiếm qua trình duyệt
host; nó không sửa bằng chứng đã lưu. Migration 033 thêm bộ đếm số
lượt tìm theo từ khóa của từng kênh trong từng ngày, dùng cho trần request theo ngày; nó không sửa bằng
chứng đã lưu. Migration 032 bổ sung watchlist, các phiên bản
không sửa được của watchlist và các lần chạy gắn với từng phiên bản; nó không sửa bằng chứng đã lưu. Migration 031 bổ sung khóa tác giả
riêng cho từng nhiệm vụ, danh sách tài khoản được khai báo và các cột thông tin tác giả trên bằng chứng của nhiệm vụ.
Migration này cũng cho phép lưu quan sát không có mã nội dung ở dạng không kiểm chứng được. Nó không sửa bằng chứng
đã lưu. Migration 030 bổ sung các khoảng trống
gắn với đầu vào hiện tại, hạn mức ngân sách, quyền truy cập nguồn đã thu hẹp, receipt của lệnh và phân bổ tài nguyên
theo nguyên tắc thận trọng. Migration 029 bổ sung liên kết bất biến giữa nhiệm vụ cha và nhiệm vụ con cùng dữ liệu
dự trữ ngân sách. Hai migration này không bổ sung hồi tố bằng chứng hay kế thừa quyền hạn cũ.
Migration 028 (`sql/028_research_work.sql`) bổ sung các bảng lưu hoạt động nghiên cứu
của host trong phạm vi được duyệt và các loại sự kiện tiến độ, không chuyển đổi dữ liệu bằng chứng đã lưu.
Migration 027 chỉ bổ sung các bảng lưu revision, sự kiện tiến độ và receipt của lệnh trên PostgreSQL; dữ liệu bằng chứng
chuẩn được giữ nguyên. SQLite và PostgreSQL hiện ghi dữ kiện thu thập, qualification và claim cùng sự kiện tiến độ
tương ứng trong một giao dịch. Relay cung cấp giao diện chỉ đọc cục bộ có thời hạn và snapshot giới hạn từ dữ liệu nhiệm vụ đã khởi tạo.
Migration 026 chỉ sửa constraint số quan sát; kết quả DEGRADED
vẫn không phải phép đo hoàn chỉnh. Khởi tạo
SQLite mới đã được kiểm tra cục bộ; rehearsal PostgreSQL tạm không xác minh database hiện hữu
của người vận hành.
Với cơ sở dữ liệu sẵn có, chạy lệnh inventory chỉ đọc
`python scripts/inventory_legacy_baseline.py --dsn sqlite:///ignis.db` (hoặc truyền DSN
PostgreSQL hiện hữu) trước khi quyết định di chuyển hay lưu trữ
corpus cũ. Chỉ áp dụng những migration chưa chạy, theo thứ tự sau khi xem tác động lên dữ liệu và được người
vận hành phê duyệt. Các file trước đó gồm `sql/022_builtin_uuid_defaults.sql`,
`sql/023_evidence_qualification.sql`, `sql/024_youtube_quota_ledger.sql` và
`sql/025_evidence_grounded_claim_ledger.sql`.
Không chạy lại 025 khi đã có hàng DEGRADED chứa kết quả một phần: constraint cũ sẽ chặn chúng
trước khi 026 chạy. Kiểm chứng chạy lại 026 không đồng nghĩa chạy lại toàn bộ lịch sử migration.

OCI image và manifest công khai vẫn trỏ tới v0.7.0. Hãy build nhánh mã nguồn này tại máy để
kiểm chứng Spec 011; đừng giả định image công khai đã có `025` hoặc tool mới. Chưa công bố
gói PyPI. HTML tạo lúc chạy nằm trong `reports/` và không được commit; mã template báo cáo
chỉ nằm tại `src/ignis/infrastructure/templates/html/`.

## Năng lực dành cho agent

MCP server của nhánh hiện có **52 tools**. Mô tả tool do server đang chạy trả về là nguồn
chuẩn cho tham số. Một số thao tác đại diện:

- `create_attention_mission` và `confirm_market_brief` xác lập câu hỏi và phạm vi;
  `execute_mission_ingress` thu thập khung chứng cứ được yêu cầu.
- `save_watchlist`, `get_watchlist` và `start_watchlist_run` lưu một watchlist gồm chủ đề và
  thương hiệu theo từng phiên bản và tạo một nhiệm vụ Attention trên phiên bản hiện tại cho mỗi
  lần chạy. Ignis không bao giờ tự chạy watchlist. `get_watchlist_period_snapshot` so một ngày,
  tuần hoặc tháng đã trọn vẹn với kỳ liền trước, theo từng kênh và theo đơn vị riêng của kênh đó;
  guide `ignis_listen` dựng kết quả thành bản xem trên máy. Mỗi kênh dừng khi chạm trần request
  theo ngày (bạn có thể nâng trần), và `scripts/prune_expired_observations.py` xóa lịch sử cũ hơn
  13 tháng khi bạn chạy nó. Với guide `ignis_routine`, agent có thể tạo một scheduled task hằng ngày
  trong Claude Code Desktop để chạy một watchlist; bản thân Ignis vẫn không tự lên lịch việc gì.
- Các tool nguồn riêng lẻ như `get_tiktok_search_suggestions` và
  `get_tiktok_video_comments` có thể trả lời câu hỏi cụ thể mà không cần kết luận thị trường.
- Ba tool `prepare_host_browser_search`, `submit_host_browser_search` và
  `cancel_host_browser_search` thu thập lưới video công khai có giới hạn qua trình duyệt được
  cho phép. Đây là đường chủ động chọn, không phải phương án tự động dự phòng;
  xem [phạm vi và giới hạn](docs/USER_GUIDE.vi.md#tìm-kiếm-tiktok-qua-trình-duyệt-host-trên-nhánh-phát-triển).
- `get_mission_evidence_qualification_batch` và
  `submit_mission_evidence_qualifications` lưu đánh giá chứng cứ.
- `submit_mission_claims`, `get_mission_claims` và `get_mission_analysis` kiểm soát
  nhận định còn hiệu lực và báo cáo khoảng trống. `generate_mission_artifact` xuất HTML khi
  người dùng yêu cầu.
- `get_mission_relay_snapshot` đọc snapshot giới hạn của nhiệm vụ được chọn. Ignis không tự
  dựng trang theo dõi: hướng dẫn `ignis-track` (prompt MCP `ignis_track`, resource
  `fn-ignis://guide/ignis-track`) chỉ cho agent cách dùng snapshot đó để dựng artifact theo dõi,
  phản ánh trạng thái tại lúc đọc. Mặc định artifact được lưu thành file cục bộ; agent chỉ công bố
  ra nơi khác khi bạn đồng ý.
- `record_mission_research_work` ghi lệnh có phạm vi của host, kiểm tra quyền của nhiệm vụ,
  revision, epoch và dữ liệu đầu vào. Việc ghi lệnh không chạy agent, gọi provider hay thu thập nguồn.
- `execute_mission_follow_up` thực hiện một công việc đã ghi nhận để bổ sung chứng cứ cho khoảng
  trống cụ thể, trong phạm vi phân công còn hiệu lực và quyền truy cập nguồn được xác minh riêng.
  Công cụ giữ lại nguồn gốc nhiệm vụ con và phần ngân sách đã giữ chỗ; quyền xem không cấp quyền
  thực hiện, còn kết quả chưa rõ thì không dẫn tới lượt thu thập mới.

Hướng dẫn agent nằm trong [AGENTS.md](AGENTS.md); ba skill
[thu thập](.agents/skills/ignis-collect/SKILL.md),
[phân tích](.agents/skills/ignis-analyze/SKILL.md) và
[theo dõi](.agents/skills/ignis-track/SKILL.md) tách biệt. [Hướng dẫn sử dụng](docs/USER_GUIDE.vi.md)
mô tả nhánh mã nguồn hiện tại. Các sơ đồ Dual-Track của v0.7.0 là tài liệu lịch sử, không
biểu diễn nhánh này.

## Kiểm chứng và trạng thái phát hành

Chạy `.venv/bin/pytest tests/unit/` cho kiểm thử cục bộ và `uv lock --check` để kiểm tra
lockfile. Kiểm thử cục bộ đạt không có nghĩa là nhánh đã được merge, đóng gói, công bố hoặc
triển khai. Các cổng pilot và phát hành nằm trong
[danh sách việc Spec 011](specs/011-evidence-grounded-product-reset/tasks.md). Nhánh phát triển
này không tự tăng số phiên bản phát hành.

## Giấy phép

Xem [LICENSE](LICENSE).
