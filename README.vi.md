# fn-ignis

Ignis là bộ công cụ tự lưu trữ để nghiên cứu thị trường từ dữ liệu social theo từng nhiệm vụ
được chỉ định. Nó giúp người dùng tự thu thập chứng cứ có thể kiểm tra từ các nguồn tiếp cận
được, rồi phản biện giả thuyết thị trường trước khi ra quyết định. Hai năng lực hoạt động độc
lập: thu thập có thể kết thúc bằng một khung chứng cứ; phân tích có thể kết thúc bằng báo cáo
thiếu chứng cứ thay vì cố đưa ra kết luận.

**Ranh giới phát hành:** Nhánh này đang triển khai Spec 011 và chưa được phát hành. Mã nguồn
và image v0.7.0 đã công bố vẫn thuộc kiến trúc Dual-Track cũ; chúng không có bộ 44 tool theo
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

## Cài đặt từ mã nguồn

Cần Python 3.11 trở lên. Chạy `./scripts/bootstrap.sh` trong checkout mã nguồn. Script tạo
môi trường Python và SQLite cục bộ, nạp từ vựng, cấu hình các MCP client được hỗ trợ và kiểm
tra tổng hợp. Credentials và phiên đăng nhập social thực tế là tùy chọn, phải do người vận
hành cho phép. Kết quả kiểm tra tổng hợp không chứng minh nguồn live truy cập được.

Cây mã nguồn hiện có migration tới `sql/027_mission_progress.sql`. Migration 027 chỉ bổ sung
các bảng lưu revision, sự kiện tiến độ và receipt của lệnh trên PostgreSQL; dữ liệu bằng chứng
chuẩn được giữ nguyên. SQLite và PostgreSQL hiện ghi dữ kiện thu thập, qualification và claim cùng sự kiện tiến độ
tương ứng trong một giao dịch. Viewer Relay chỉ đọc chưa được triển khai. Migration 026 chỉ sửa constraint số quan sát; kết quả DEGRADED
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

MCP server của nhánh hiện có **44 tools**. Mô tả tool do server đang chạy trả về là nguồn
chuẩn cho tham số. Một số thao tác đại diện:

- `create_attention_mission` và `confirm_market_brief` xác lập câu hỏi và phạm vi;
  `execute_mission_ingress` thu thập khung chứng cứ được yêu cầu.
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

Hướng dẫn agent nằm trong [AGENTS.md](AGENTS.md); hai skill
[thu thập](.agents/skills/ignis-collect/SKILL.md) và
[phân tích](.agents/skills/ignis-analyze/SKILL.md) tách biệt. [Hướng dẫn sử dụng](docs/USER_GUIDE.vi.md)
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
