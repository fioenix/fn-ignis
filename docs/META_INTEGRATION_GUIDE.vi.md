# Thu thập Threads và đọc dữ liệu Instagram cũ

Trên nhánh Spec 022, Threads chỉ được thu thập qua trình duyệt host mà người dùng đã cho phép.
Ignis đã ngừng thu thập Reels và gỡ các tool đăng nhập riêng theo nền tảng. Quan sát, kết quả từng
kênh và session cũ vẫn đọc được; thay đổi này không xóa dữ liệu. Nhánh có 42 tools, chưa được
phát hành thành phiên bản mới.

## Thu thập Threads

Dùng [hướng dẫn thu thập](../.agents/skills/ignis-collect/SKILL.md) cho yêu cầu có phạm vi rõ ràng.
`prepare_host_browser_search` với `source="threads"` chuẩn bị phạm vi được phép;
`submit_host_browser_search` kiểm tra chứng cứ công khai đã thu được;
`cancel_host_browser_search` hủy phạm vi đó. Chuẩn bị phạm vi không cấp quyền truy cập trình duyệt.
Host dùng khả năng trình duyệt của mình và giữ nguyên các tab của người dùng.

Đường `threads-search-top-v2` lấy mẫu Top hữu hạn đang hiển thị. Trang đang tải, yêu cầu đăng nhập,
challenge hoặc nội dung không đọc được đều là trạng thái không khả dụng, không chứng minh thị
trường rỗng. Credential Graph đã lưu không kích hoạt luồng này. Ignis không probe quyền API và
không tự chuyển sang Graph API hay bộ thu thập Playwright nội bộ. Xem [hướng dẫn sử dụng](USER_GUIDE.vi.md)
về phạm vi, độ chính xác của số đếm, xử lý danh tính và khả năng so sánh giữa các kỳ.

## Session và chứng cứ đã lưu

`get_platform_auth_status` vẫn đọc thông tin trạng thái credential. `clear_platform_auth` chỉ xóa
credential đã lưu khi được yêu cầu rõ ràng; thao tác này không thu hồi session tại nền tảng.
Việc ngừng nguồn không tự xóa session. Bộ lọc nội dung của chính người dùng vẫn có thể đọc danh
tính tài khoản đã lưu; việc đọc này không mở session thu thập hay chứng minh nguồn sẵn sàng.

Mission mới hoặc lượt chạy lại có `reels` trả `BLOCKED / SURFACE_RETIRED` trước khi thu thập.
Lượt chạy watchlist bỏ các nguồn đã ngừng hoạt động khỏi danh sách được yêu cầu và nêu mã lý do;
nếu không còn nguồn nào, lượt chạy bị từ chối. Quan sát và kết quả Reels cũ giữ nguyên nhãn nền tảng.

## Bảo vệ credential

Kho credential dùng Fernet (AES-128-CBC + HMAC-SHA256) với `IGNIS_ENCRYPTION_KEY`.
`key_version` chỉ là nhãn trong bản ghi. Không có giải mã bằng hai khóa hay tự mã hóa lại;
thay khóa khiến bản ghi dùng khóa cũ không đọc được. Không dán credential vào chat. Việc che
thông tin nhạy cảm chỉ bao phủ các đường do dự án kiểm soát, không bao gồm tool hay transcript
bên ngoài. Bộ lọc PII theo mẫu giúp giảm rủi ro nhưng không bảo đảm xóa được mọi tên riêng.

[Quyết định về kết nối nguồn](decisions/2026-11-10-source-connection-boundary.md) áp dụng cho kết
nối sau này: có MCP chính thức do chủ nền tảng công bố thì host dùng MCP đó; nếu chưa có, Ignis
có thể giữ kết nối tích hợp còn thu được chứng cứ. MCP cộng đồng không được tính là chính thức.
