# Hướng dẫn sử dụng Ignis — nhánh mã nguồn Spec 011

Tài liệu này mô tả nhánh mã nguồn theo nhiệm vụ chưa phát hành, không phải image v0.7.0
đã công bố. Worker và sơ đồ Dual-Track của v0.7.0 là lịch sử, không mô tả nhánh này. Xem
[README tiếng Việt](../README.vi.md) để biết hợp đồng sản phẩm và ranh giới phát hành.

## 1. Khởi động và kiểm tra

Cần Python 3.11 trở lên. Chạy `./scripts/bootstrap.sh` trong checkout mã nguồn. Script tạo
SQLite cục bộ và cấu hình MCP client, rồi kiểm tra tổng hợp. Đọc trạng thái từng connector;
việc client đã được cấu hình hoặc kiểm tra tổng hợp đạt không chứng minh nguồn social live
truy cập được. Chỉ cấp credentials hoặc phiên browser cho đúng nguồn và nhiệm vụ đã cho phép.
Không đặt bí mật trong prompt, transcript lệnh hay báo cáo.

Chuỗi migration trong mã nguồn kết thúc ở `sql/028_research_work.sql`. Migration 028 bổ sung các bảng lưu hoạt động nghiên cứu
của host trong phạm vi được duyệt và các loại sự kiện tiến độ, không chuyển đổi dữ liệu bằng chứng đã lưu.
Migration 027 chỉ bổ sung các bảng lưu revision, sự kiện tiến độ và receipt của lệnh trên PostgreSQL; dữ liệu bằng chứng
chuẩn được giữ nguyên. SQLite và PostgreSQL hiện ghi dữ kiện thu thập, qualification và claim cùng sự kiện tiến độ
tương ứng trong một giao dịch. Relay cung cấp giao diện chỉ đọc cục bộ có thời hạn và snapshot giới hạn từ dữ liệu nhiệm vụ đã khởi tạo.
Migration 026 chỉ sửa constraint số quan sát, giữ kết quả thu thập một phần ở trạng thái
DEGRADED; không coi đó là phép đo hoàn chỉnh hay bằng chứng về sự vắng mặt.
Khởi tạo SQLite mới đã được kiểm tra tại máy; rehearsal PostgreSQL tạm không xác minh database
hiện hữu của người vận hành. Với cơ sở dữ liệu sẵn có, chạy
`python scripts/inventory_legacy_baseline.py --dsn sqlite:///ignis.db` (hoặc truyền DSN
PostgreSQL hiện hữu) để kiểm kê corpus cũ ở chế độ chỉ đọc.
Không xóa hoặc di chuyển nó chỉ vì quy trình mới không sử dụng. Xem tác động lên dữ liệu,
xin phê duyệt rồi chỉ áp dụng những migration chưa chạy, theo thứ tự. Những file trước đó gồm
`sql/022_builtin_uuid_defaults.sql`, `sql/023_evidence_qualification.sql` và
`sql/024_youtube_quota_ledger.sql` và `sql/025_evidence_grounded_claim_ledger.sql`.
Không chạy lại 025 khi đã có hàng DEGRADED chứa kết quả một phần: constraint cũ sẽ chặn chúng
trước khi 026 chạy. Kiểm chứng chạy lại riêng 026 không bao gồm toàn bộ lịch sử migration.

## 2. Chọn nhiệm vụ

Nếu chỉ hỏi một nguồn, hãy chỉ định từ khóa, địa lý, khung thời gian và điều kiện dừng.
Agent gọi tool nguồn riêng lẻ và trả về nguồn, truy vấn, thời điểm thu thập, số quan sát và
trạng thái kênh. Không cần mở nhiệm vụ Market hay cố đưa ra kết luận chiến lược.

Nếu cần quyết định kinh doanh, hãy nêu quyết định cần đưa ra, đối tượng, địa lý, thời gian,
giả thuyết, cách giải thích thay thế và điều gì khiến quyết định thay đổi. Agent tạo Attention mission
hoặc xác nhận Market Brief với người dùng trước khi thu thập. Sau khi chốt phạm vi,
`execute_mission_ingress` chỉ chạy kế hoạch của nhiệm vụ đó. Không có worker hay lịch tự
thu thập hằng ngày.

[Skill thu thập](../.agents/skills/ignis-collect/SKILL.md) tạo khung chứng cứ có thể kiểm
tra. [Skill phân tích](../.agents/skills/ignis-analyze/SKILL.md) là năng lực riêng để thử
giả thuyết Market. Có thể yêu cầu một trong hai hoặc cả hai.

## 3. Đọc chứng cứ và kết quả phân tích

Ignis ghi kết quả cho từng kênh được yêu cầu. `HEALTHY`, `EMPTY_NO_DATA`, `AUTH_REQUIRED`,
`RATE_LIMITED` và `DEGRADED` có ý nghĩa khác nhau: không truy cập được kênh là thiếu bao
phủ, không phải chứng cứ rằng thị trường không có nhu cầu. Agent đánh giá từng quan sát là
ủng hộ, phản bác hay chỉ cung cấp bối cảnh và kiểm tra khung chứng cứ đã đi đến trạng thái
cuối trước khi lập nhận định Market.

Mỗi nhận định chiến lược phải nằm trong Claim Ledger được lưu. `submit_mission_claims` gắn
nó với quan sát hoặc kết quả không thấy dữ liệu đã được đo hợp lệ;
`get_mission_claims` cho biết nó có được phép hiển thị không. `get_mission_analysis` chỉ
trả các nhận định còn hiệu lực trong khung hiện tại. Nếu độ bao phủ, đánh giá chứng cứ hay
nhận định chưa đạt, hệ thống trả báo cáo khoảng trống, nêu quan sát an toàn và phép thăm dò
nhỏ nhất nên làm tiếp. Điểm số hoặc tín hiệu thô không thay thế được cổng này.

File tải lên và dataset mua ngoài có thể giúp đặt câu hỏi hoặc nhận diện đối thủ. Nếu chưa
có xuất xứ và đánh giá gắn với nhiệm vụ, chúng chỉ là bối cảnh, không phải chứng cứ Market
chính. Phân tích cần nêu chứng cứ phản bác và điều kiện khiến kết luận thay đổi. Chỉ dùng
`generate_mission_artifact` khi cần lưu báo cáo HTML. Bản chạy từ mã nguồn ghi vào `reports/`
không được commit; bản cài bằng package ghi vào `~/.ignis/reports/`, hoặc thư mục tạm nếu
cần. Mã template chỉ nằm ở `src/ignis/infrastructure/templates/html/`.

### Mission Relay trên nhánh phát triển

Dùng `get_mission_relay_snapshot` để đọc snapshot giới hạn của nhiệm vụ và run được chọn.
Dùng `open_mission_relay` với thời hạn UTC được chỉ định để mở giao diện chỉ đọc trên localhost.
Các thao tác đọc kiểm tra storage đã khởi tạo, không khởi tạo database hay chạy collector.
`record_mission_research_work` ghi lệnh có phạm vi được chỉ định của host qua phiên stdio cục bộ,
kiểm tra quyền của nhiệm vụ cùng revision, epoch và dữ liệu đầu vào chính xác. Việc ghi lệnh
không chạy agent, gọi provider hay thu thập nguồn.

## 4. Ranh giới tool và triển khai

MCP server cục bộ có **47 tools**. Xem mô tả trực tiếp từ server để biết tham số chính xác;
các tool khám phá hằng ngày và nghiên cứu không giới hạn đã bị loại khỏi nhánh này. OCI
manifest công khai vẫn là v0.7.0, nên image công khai không chứng minh Spec 011 đã ship.
Chưa công bố cách cài qua PyPI. Chạy `.venv/bin/pytest tests/unit/` và `uv lock --check`
để kiểm tra cục bộ, rồi xem [danh sách việc](../specs/011-evidence-grounded-product-reset/tasks.md)
cho các cổng PostgreSQL, pilot, tích hợp và phát hành cần chủ sở hữu quyết định.
### Tìm kiếm TikTok qua trình duyệt host trên nhánh phát triển

Ba tool `prepare_host_browser_search`, `submit_host_browser_search` và
`cancel_host_browser_search` cung cấp đường thu thập chủ động chọn, chỉ trong nhiệm vụ được duyệt.
Host dùng phiên trình duyệt được cho phép, chạy bộ trích xuất đóng gói trên đúng trang tìm kiếm,
rồi chuyển nguyên JSON trong bộ nhớ qua form localhost. MCP nhận kết quả bằng ID; không cần
chép lại bản ghi qua mô hình, xuất cookie hay mở cổng gỡ lỗi.

Chế độ `TACTICAL` không khởi tạo database. Chế độ `MISSION` cần mission đã xác nhận,
`queries=[]` và `result_limit=20`; truy vấn, kể cả truy vấn phản biện, được lấy từ phạm vi đã duyệt.
Ignis kiểm tra lại phạm vi trong khóa ghi, lưu theo luồng evidence hiện có và trả run/frame chuẩn.
Lỗi ghi cần đọc lại journal/frame trước khi thay yêu cầu, không tự gửi lại.

Yêu cầu tối đa một giờ, payload form tối đa 1 MiB. Listener chỉ mở ở localhost, kiểm tra đúng
Host/Origin và đóng khi kết thúc. Chỉ số, ngày đăng và khoảng thời gian chưa đo vẫn là chưa biết.
Lưới video hữu hạn không đại diện cho toàn thị trường, không bao gồm bình luận và không phải
khuyến nghị kinh doanh. Host chỉ đóng tab do nhiệm vụ tạo, giữ nguyên trình duyệt và tab của chủ.
