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

Chuỗi migration trong mã nguồn kết thúc ở `sql/025_evidence_grounded_claim_ledger.sql`.
Khởi tạo SQLite mới đã được kiểm tra tại máy; việc áp dụng `025` trên PostgreSQL chưa được
kiểm chứng. Với cơ sở dữ liệu sẵn có, chạy
`python scripts/inventory_legacy_baseline.py --dsn sqlite:///ignis.db` (hoặc truyền DSN
PostgreSQL hiện hữu) để kiểm kê corpus cũ ở chế độ chỉ đọc.
Không xóa hoặc di chuyển nó chỉ vì quy trình mới không sử dụng. Xem tác động lên dữ liệu,
xin phê duyệt rồi mới áp dụng các migration theo thứ tự. Những file trước đó gồm
`sql/022_builtin_uuid_defaults.sql`, `sql/023_evidence_qualification.sql` và
`sql/024_youtube_quota_ledger.sql`.

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
`generate_mission_artifact` khi cần lưu báo cáo HTML; đầu ra nằm trong `reports/` không
được commit, còn mã template chỉ nằm ở `src/ignis/infrastructure/templates/html/`.

## 4. Ranh giới tool và triển khai

MCP server cục bộ có **41 tools**. Xem mô tả trực tiếp từ server để biết tham số chính xác;
các tool khám phá hằng ngày và nghiên cứu không giới hạn đã bị loại khỏi nhánh này. OCI
manifest công khai vẫn là v0.7.0, nên image công khai không chứng minh Spec 011 đã ship.
Chưa công bố cách cài qua PyPI. Chạy `.venv/bin/pytest tests/unit/` và `uv lock --check`
để kiểm tra cục bộ, rồi xem [danh sách việc](../specs/011-evidence-grounded-product-reset/tasks.md)
cho các cổng PostgreSQL, pilot, tích hợp và phát hành cần chủ sở hữu quyết định.
