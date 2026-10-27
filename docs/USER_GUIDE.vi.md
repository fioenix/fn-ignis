# Hướng dẫn sử dụng Ignis — v0.8.0

Tài liệu này mô tả v0.8.0, gồm Spec 011 và watchlist. Worker và sơ đồ Dual-Track của v0.7.0
là lịch sử, không mô tả phiên bản này. Xem
[README tiếng Việt](../README.vi.md) để biết hợp đồng sản phẩm và ranh giới phát hành.

## 1. Khởi động và kiểm tra

Cần Python 3.11 trở lên. Chạy `./scripts/bootstrap.sh` trong checkout mã nguồn. Script tạo
SQLite cục bộ và cấu hình MCP client, rồi kiểm tra tổng hợp. Đọc trạng thái từng connector;
việc client đã được cấu hình hoặc kiểm tra tổng hợp đạt không chứng minh nguồn social live
truy cập được. Chỉ cấp credentials hoặc phiên browser cho đúng nguồn và nhiệm vụ đã cho phép.
Không đặt bí mật trong prompt, transcript lệnh hay báo cáo.

Chuỗi migration trong mã nguồn kết thúc ở `sql/036_threads_attribution.sql`. Migration 036 nạp sẵn mẫu câu ghi công tác giả của Threads, dùng để bỏ câu ghi công khỏi trích đoạn khi tìm kiếm qua trình duyệt; nó không sửa bằng chứng đã lưu. Migration 035 lưu lịch sử mục tiêu, kỳ so sánh và nhịp lấy mẫu của watchlist; nó không sửa bằng chứng đã lưu. Migration 034 nạp sẵn
mẫu câu ghi công tác giả của TikTok, dùng để bỏ câu ghi công khỏi trích đoạn khi tìm kiếm qua trình
duyệt host; nó không sửa bằng chứng đã lưu. Migration 033 thêm
bộ đếm số lượt tìm theo từ khóa của từng kênh trong từng ngày, dùng cho trần request theo ngày; nó không
sửa bằng chứng đã lưu. Migration 032 bổ sung watchlist, các phiên
bản không sửa được của watchlist và các lần chạy gắn với từng phiên bản; nó không sửa bằng chứng đã lưu. Migration
031 bổ sung khóa tác
giả riêng cho từng nhiệm vụ, danh sách tài khoản được khai báo và các cột thông tin tác giả trên bằng chứng của nhiệm
vụ. Migration này cũng cho phép lưu quan sát không có mã nội dung ở dạng không kiểm chứng được. Nó không sửa bằng
chứng đã lưu. Migration 030 bổ sung các khoảng trống
gắn với đầu vào hiện tại, hạn mức ngân sách và đơn vị đo rõ ràng, quyền truy cập nguồn đã thu hẹp, receipt của lệnh gốc
và phân bổ tài nguyên theo nguyên tắc thận trọng. Khi nhận nhiệm vụ trên SQLite, hệ thống yêu cầu một bên xác minh
quyền hạn hiện tại được cấu hình độc lập và từ chối nếu thiếu bên này. Bên cấp quyền hạn thực tế của host và việc
thực thi nhiệm vụ con chưa được xác minh. Migration 029 bổ sung liên kết bất biến giữa nhiệm vụ cha và nhiệm vụ con
cùng dữ liệu dự trữ ngân sách. Hai migration này không bổ sung hồi tố bằng chứng hay kế thừa quyền hạn cũ.
Migration 028 (`sql/028_research_work.sql`) bổ sung các bảng lưu hoạt động nghiên cứu
của host trong phạm vi được duyệt và các loại sự kiện tiến độ, không chuyển đổi dữ liệu bằng chứng đã lưu.
Migration 027 chỉ bổ sung các bảng lưu revision, sự kiện tiến độ và receipt của lệnh trên PostgreSQL; dữ liệu bằng chứng
chuẩn được giữ nguyên. SQLite và PostgreSQL hiện ghi dữ kiện thu thập, qualification và claim cùng sự kiện tiến độ
tương ứng trong một giao dịch. Relay cung cấp snapshot giới hạn từ dữ liệu nhiệm vụ đã khởi tạo; Ignis không tự dựng trang theo dõi.
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

Dưới đây là một số tool nguồn riêng lẻ đã đăng ký (chữ ký chính xác nằm trong mô tả tool của server
đang chạy). Đây là các lựa chọn đã đăng ký, chưa phải bằng chứng nguồn đang dùng được. Chỉ gọi tool
cho đúng nhiệm vụ có phạm vi mà người dùng đã yêu cầu rõ, và chỉ khi đã có trước quyền cần thiết với
owner, nguồn, trình duyệt hoặc phiên đăng nhập. Credential, phiên trình duyệt hay trạng thái xác
thực đã lưu tự chúng không cấp quyền đó.

- `get_tiktok_video_comments(video_url, limit=30)` đọc bình luận công khai dưới một video TikTok
  bằng trình duyệt headless, dùng phiên TikTok đã lưu nếu có. Kết quả gồm `status`, `video_url`,
  `total_comments` và danh sách bình luận. URL không có đoạn `/video/<id>` hoặc máy chưa cài
  Playwright trả về `SUCCESS` với 0 bình luận. Trang bị chặn hoặc không phân tích được cũng có thể
  cho 0 bình luận, hoặc trả về `ERROR`, tùy chỗ bị lỗi. Vì vậy con số 0 không chứng minh video
  không có thảo luận.
- `get_tiktok_search_suggestions(keywords, geo="VN")` trả về gợi ý tìm kiếm.
  `get_tiktok_creative_center_trends(geo="VN", period=7, limit=20, industry=None)` trả về xu hướng
  vĩ mô (`limit` tối đa 50). Các kết quả này mở rộng chủ đề, không đo nhu cầu.
  Hai chữ ký cũ `get_threads_search_suggestions(keyword, geo="VN", limit=10)` và
  `get_threads_trending_topics(geo="VN", limit=15)` trả về `UNAVAILABLE/HOST_BROWSER_REQUIRED`.
  Không có phương án dự phòng qua browser, cookie hay OAuth.
- `execute_mission_ingress(mission_id)` là lựa chọn riêng cho nhiệm vụ đã xác nhận: tool này chỉ
  chạy kế hoạch đã ghi của nhiệm vụ đó và ghi kết quả cho từng kênh được yêu cầu.

Các tool này không ép theo quy trình thu thập rồi mới phân tích, không tự lên lịch thu thập tiếp
và không cần gọi nối nhau. Mỗi tool vẫn có điều kiện riêng: quyền truy cập nguồn thực tế, phạm vi
nguồn và nhiệm vụ, giới hạn tài nguyên. Riêng `execute_mission_ingress` còn cần nhiệm vụ đã xác
nhận cùng kế hoạch đã ghi (với nhiệm vụ Market là Market Brief đã xác nhận). `verify_connectors_health` chỉ chạy chẩn đoán tổng hợp, còn tool xác thực có thể chạy
probe truy cập, nên đừng gọi chúng chỉ để xem một nguồn có dùng được hay không.

Nếu cần quyết định kinh doanh, hãy nêu quyết định cần đưa ra, đối tượng, địa lý, thời gian,
giả thuyết, cách giải thích thay thế và điều gì khiến quyết định thay đổi. Agent tạo Attention mission
hoặc xác nhận Market Brief với người dùng trước khi thu thập. Sau khi chốt phạm vi,
`execute_mission_ingress` chỉ chạy kế hoạch của nhiệm vụ đó. Không có worker hay lịch tự
thu thập hằng ngày.

[Skill thu thập](../.agents/skills/ignis-collect/SKILL.md) tạo khung chứng cứ có thể kiểm
tra. [Skill phân tích](../.agents/skills/ignis-analyze/SKILL.md) là năng lực riêng để thử
giả thuyết Market. Có thể yêu cầu một trong hai hoặc cả hai.

### Theo dõi một watchlist

Muốn theo dõi cùng một chủ đề qua nhiều lần chạy, hãy nhờ agent lưu một watchlist trong research
workspace đã xác nhận. Mỗi watchlist có tối đa 10 chủ đề; mỗi chủ đề gồm các ngành hàng, tối đa 20
từ khóa và những tài khoản thương hiệu do bạn chỉ định. `save_watchlist` lưu mỗi lần thay đổi thành
một phiên bản mới và phiên bản đã lưu thì không sửa được; `get_watchlist` liệt kê các phiên bản cùng
các lần chạy. Mỗi lần gọi `start_watchlist_run` tạo một nhiệm vụ Attention trên phiên bản hiện tại
và khai báo các thương hiệu đó làm tài khoản của nhiệm vụ. Đây là những tài khoản duy nhất Ignis gọi
tên. Lần chạy nào bạn cũng phải nêu rõ nguồn được phép và quyền hạn; sau đó việc thu thập đi qua
`execute_mission_ingress` như mọi nhiệm vụ khác. Ignis không bao giờ tự chạy watchlist.

`set_watchlist_listening_plan` lưu mục tiêu, kỳ so sánh (`day`, `week`, `month`) và số lần
lấy mẫu trong mỗi kỳ do người dùng chọn. Lịch sử kế hoạch chỉ được thêm, không sửa; lưu lại cùng
kế hoạch không tạo dòng mới. `get_watchlist` trả kế hoạch đang có hiệu lực cùng lịch sử.
Khi bỏ `period_kind`, period view dùng kỳ trong kế hoạch; nếu chưa có kế hoạch, cần truyền kỳ
rõ ràng. Routine hỏi người dùng khi chưa có kế hoạch, trình bày số lượt chạy và request mỗi kỳ,
rồi chờ xác nhận trước khi tạo lịch trên host. Ignis không tự tạo lịch hay chạy thu thập.

Muốn xem một watchlist thay đổi ra sao, hãy nhờ agent mở bản xem theo kỳ.
`get_watchlist_period_snapshot` so một ngày, một tuần (từ thứ Hai đến Chủ nhật) hoặc một tháng đã
trọn vẹn theo giờ Việt Nam với kỳ liền trước, và từ chối kỳ chưa kết thúc. `period_kind` là tham số
tùy chọn: nếu bỏ qua thì dùng kỳ trong kế hoạch đã lưu; nếu chưa có kế hoạch, cần truyền kỳ rõ ràng.
Prompt `ignis_listen` và resource `fn-ignis://guide/ignis-listen` hướng dẫn agent dựng kết quả
thành một file trên máy, trình bày hai trục riêng:

- `seen` trình bày trước: những gì mỗi lần lấy mẫu thành công đã ghi nhận, xếp theo thời điểm kênh
  thu thập xong. Số nội dung liên quan, lượt xem, tương tác, nội dung thấy lần đầu và nội dung đăng
  trong kỳ đều là trung bình trên mỗi lần lấy mẫu. Bài cũ vẫn được tính mỗi lần xuất hiện.
  Mỗi kỳ dùng kế hoạch có hiệu lực lúc kỳ đó bắt đầu. Thiếu tối đa 20% số lần lấy mẫu yêu cầu vẫn
  có thể so sánh; thiếu quá 20%, chưa có nhịp phù hợp hoặc còn quan sát chưa được đánh giá thì
  hiện "không so được" cùng lý do và số lần lấy mẫu, không hiện chỉ số hay mức thay đổi.
- `created` trình bày sau: nội dung được xếp theo ngày đăng; nếu thiếu ngày đăng hợp lý thì dùng
  ngày thu thập và ghi rõ điều đó. Trục này giữ quy tắc bao phủ theo ngày và cửa sổ ghi nhận bảy
  ngày của Spec 016. Kênh thiếu quá 20% số ngày ở một trong hai kỳ, hoặc có ngày chưa đánh giá
  xong, chỉ hiện "không so được" cùng ngày thiếu hay chưa đánh giá. Chỉ những quan sát được đánh
  giá là liên quan mới được tính.

Mỗi kênh giữ đơn vị riêng; kênh đo trên mẫu phải ghi rõ số liệu chỉ tính trên mẫu đã thu thập.
Trạng thái so sánh của
hai trục độc lập với nhau; không cộng dồn giữa các kênh hay hai trục. Chỉ số chưa biết không phải
bằng 0. Google Trends RSS chỉ cung cấp chủ đề vĩ mô và traffic do feed báo; phép đo Trends theo
từ khóa hiện chưa có và trả `DEGRADED`, không phải điểm nhu cầu.

Mỗi kênh có một trần request theo ngày. Một request là một lần tìm một từ khóa trên kênh đó và
mọi phiên dùng chung một store đều dùng chung bộ đếm của ngày đó theo giờ Việt Nam. Mặc định YouTube
được 200 request, các kênh khác 50; muốn nâng trần thì đặt `connector.<platform>.daily_request_ceiling`
bằng `update_runtime_config`. Lượt tìm nào vượt trần sẽ không gửi gì tới kênh đó và được ghi
`RATE_LIMITED` kèm ghi chú `daily_ceiling`, còn các kênh khác vẫn chạy. Mỗi lượt tìm tính mọi từ
khóa nó tìm (Reels chỉ đọc tối đa 10 từ khóa), nên watchlist có nhiều từ khóa hơn trần của
một kênh sẽ bỏ qua kênh đó cho tới khi bạn nâng trần. Ignis không tự xóa
lịch sử: `scripts/prune_expired_observations.py` liệt kê các quan sát
thu thập cách đây hơn 13 tháng và xóa chúng khi có `--apply`, trừ những quan sát mà một
claim đã lưu hoặc công việc nghiên cứu đã ghi vẫn còn tham chiếu tới.

Muốn watchlist tự chạy mỗi ngày, hãy nhờ agent, chẳng hạn "chạy watchlist matcha mỗi sáng lúc 7
giờ". Prompt `ignis_routine` và resource `fn-ignis://guide/ignis-routine` hướng dẫn agent tạo một
scheduled task trong Claude Code Desktop: mỗi watchlist tối đa một task, chạy tối đa một lần mỗi
ngày, và chỉ được tạo sau khi bạn xác nhận những gì sẽ chạy. Mỗi lần kích hoạt là đúng một lần chạy
watchlist. Hãy tạo task từ một phiên mở trong thư mục repository của research workspace, vì lần kích
hoạt bắt đầu trong thư mục đó. Trước khi tạo, agent kiểm tra từng kênh có thu thập được cho
workspace của bạn không: YouTube cần key trong `.fnignis/.env` riêng của workspace, còn các kênh
browser cần phiên đăng nhập đã lưu. Routine không bao giờ chạy ở chế độ quyền Bypass, và chỉ chạy ở
chế độ Auto khi bạn đồng ý lúc cài đặt. Mỗi lần chạy, agent còn đánh giá xem item nào thu được thuộc
đúng chủ đề của bạn, vì period view chỉ đếm những item đã được đánh giá. Bước cài đặt kết thúc bằng
một lần chạy có bạn theo dõi; ở chế độ có hỏi quyền, bạn chỉ duyệt `start_watchlist_run`,
`execute_mission_ingress`, `get_mission_evidence_qualification_batch` và
`submit_mission_evidence_qualifications`. Bạn tạm dừng hoặc xóa routine trong app, và xóa routine không làm mất
lịch sử của watchlist. Routine chỉ chạy khi app đang mở. Các host khác chưa được hỗ trợ, và bản thân
Ignis vẫn không tự lên lịch việc gì.

## 3. Đọc chứng cứ và kết quả phân tích

Ignis ghi kết quả cho từng kênh được yêu cầu. `HEALTHY`, `EMPTY_NO_DATA`, `AUTH_REQUIRED`,
`RATE_LIMITED`, `DEGRADED`, `FAILED` và `NOT_REQUESTED` có ý nghĩa khác nhau: kênh không truy
cập được hoặc đo thất bại là thiếu bao phủ, còn bề mặt nằm ngoài kế hoạch được yêu cầu thì chưa
được đo; cả hai đều không phải chứng cứ rằng thị trường không có nhu cầu. Agent đánh giá từng quan sát là
ủng hộ, phản bác hay chỉ cung cấp bối cảnh và kiểm tra khung chứng cứ đã đi đến trạng thái
cuối trước khi lập nhận định Market.

Thu thập Threads cần trình duyệt host được cho phép riêng. Credential Graph đã lưu chỉ là trạng
thái tương thích, không chứng minh quyền tìm kiếm công khai. `authenticate_threads`,
`get_threads_auth_status` và `clear_threads_auth` giữ chữ ký cũ; chúng không kích hoạt thu thập
hay probe quyền API. Hãy chuẩn bị host một cách tường minh hoặc báo phần thiếu dữ liệu.

Mỗi nhận định chiến lược phải nằm trong Claim Ledger được lưu. `submit_mission_claims` gắn
nó với quan sát hoặc kết quả không thấy dữ liệu đã được đo hợp lệ;
`get_mission_claims` cho biết nó có được phép hiển thị không. `get_mission_analysis` chỉ
trả các nhận định còn hiệu lực trong khung hiện tại. Nếu độ bao phủ, đánh giá chứng cứ hay
nhận định chưa đạt, hệ thống trả báo cáo khoảng trống, nêu quan sát an toàn và phép thăm dò
nhỏ nhất nên làm tiếp. Điểm số hoặc tín hiệu thô không thay thế được cổng này.

File tải lên và dataset mua ngoài có thể giúp đặt câu hỏi hoặc nhận diện đối thủ. Nếu chưa
có xuất xứ và đánh giá gắn với nhiệm vụ, chúng chỉ là bối cảnh, không phải chứng cứ Market
chính. Phân tích cần nêu chứng cứ phản bác và điều kiện khiến kết luận thay đổi. Chỉ dùng
`generate_mission_artifact` khi cần lưu báo cáo HTML. Giống mọi tool của nhiệm vụ, lệnh này chỉ
được chấp nhận qua đúng một caller root hợp lệ và báo cáo được ghi vào `<root>/.fnignis/reports/`.
Server vẫn giữ phương án dự phòng cho lệnh gọi không có caller root: bản chạy từ mã nguồn ghi vào
`reports/` không được commit; bản cài bằng package ghi vào `~/.ignis/reports/`, hoặc thư mục tạm
nếu cần. Lệnh gọi MCP đã được chấp nhận không dùng phương án này. Mã template chỉ nằm ở
`src/ignis/infrastructure/templates/html/`.

### Danh tính tác giả

Ignis nghiên cứu thị trường ở mức tổng hợp và không lưu danh tính tác giả. Trước khi lưu một quan
sát, Ignis loại bỏ các trường tác giả mà connector trả về (username, ID người dùng và kênh, tên hiển
thị, link hồ sơ, ảnh đại diện), thay link có tên tài khoản bằng link tới nội dung không chứa handle
(`tiktok.com/share/video/<id>`, `threads.com/t/<shortcode>`) hoặc bỏ link nếu không dựng được, và
đổi các @mention trong tiêu đề, chú thích, bình luận thành `@[user]`. Ignis chỉ giữ lại marker tác
giả theo từng nhiệm vụ: một mã băm có khóa, đủ để phân biệt nhiều người nói với một người nói trong
cùng nhiệm vụ, nhưng không nối được các nhiệm vụ với nhau. `get_mission_analysis` trả
`author_concentration` cho từng kênh; nếu chưa cấu hình `IGNIS_ENCRYPTION_KEY` cố định thì Ignis
không đếm được số tác giả và kết quả phân tích nói rõ điều đó. Nội dung không có mã tham chiếu chỉ
được giữ làm bối cảnh, không bao giờ dùng để ủng hộ một nhận định.

Ignis chỉ giữ danh tính của các tài khoản mà người yêu cầu khai báo cho một nhiệm vụ bằng
`set_mission_declared_accounts`, chẳng hạn tài khoản của chính thương hiệu hoặc một đối thủ được nêu
tên, theo dạng `{platform, account, declared_name}`. Mỗi lần gọi thay toàn bộ danh sách của nhiệm
vụ; gửi danh sách rỗng nghĩa là rút mọi khai báo. Nội dung của tài khoản đã khai báo, nếu thu thập
sau `declared_at`, được ghi theo tên đã khai báo, và lời nhắc tới tài khoản đó hiển thị thành
`@<tên đã khai báo>`. Quan sát thu trước đó không bị gán lại; sau khi rút khai báo, tên biến mất khỏi
báo cáo mà chứng cứ không bị viết lại.

Ignis không loại bỏ tên người viết trong nội dung tự do, chẳng hạn khi người bình luận tự ký tên. Dữ
liệu lưu trước Spec 015 vẫn còn danh tính cho đến khi chủ sở hữu quyết định cách xử lý; mọi báo cáo
và phản hồi của tool đều loại bỏ danh tính khi xuất ra, còn `scripts/inventory_author_identity.py`
chỉ đếm mà không hiển thị giá trị.

### Mission Relay

Ignis không tự dựng trang theo dõi. Muốn theo dõi một nhiệm vụ, hãy yêu cầu agent đọc
`get_mission_relay_snapshot` rồi dựng artifact theo dõi theo hướng dẫn `ignis-track`: prompt MCP
`ignis_track`, resource `fn-ignis://guide/ignis-track` hoặc skill
[`ignis-track`](../.agents/skills/ignis-track/SKILL.md) trong repo. Agent chỉ dựng lại artifact khi
bạn yêu cầu hoặc tại một mốc trong chính lượt làm việc của nó, chứ không đọc lặp theo chu kỳ. Mỗi
artifact là ảnh chụp tại một thời điểm, luôn hiển thị rõ những gì bị giữ lại, đã cũ hoặc chưa có
dữ liệu. Artifact được lưu thành file cục bộ; muốn công bố ở nơi khác, agent phải xin phép bạn
trước mỗi lần. Đọc snapshot không làm khởi động, tạm dừng hay huỷ việc thu thập.

Dùng `get_mission_relay_snapshot` để đọc snapshot giới hạn của nhiệm vụ và run được chọn. Thao tác
đọc kiểm tra storage đã khởi tạo, không khởi tạo database hay chạy collector. Giống mọi tool của
nhiệm vụ, thao tác này chỉ được chấp nhận qua đúng một caller root: thư mục bạn mở agent, cũng là
thư mục làm việc của MCP server lúc khởi động. Chỉ đặt `IGNIS_CALLER_ROOT` (thư mục tuyệt đối,
không đổi kể từ lúc khởi động) khi host khởi động server ở nơi khác. Ignis không dùng danh sách
root do client gửi. Ignis từ chối thư mục khởi động không thể là thư mục của một dự án, gồm: thư
mục gốc của hệ thống; thư mục home hoặc thư mục cha của nó; thư mục ai cũng ghi được hoặc có sticky
bit; thư mục thuộc người dùng khác. Thư mục bị thay thế sau khi khởi động cũng bị từ chối. Mọi trường hợp bị từ
chối đều trả về `ROOT_REQUIRED`. Khi lệnh gọi được chấp
nhận, dữ liệu chuẩn của nhiệm vụ mặc định nằm trong SQLite cục bộ của caller tại
`<root>/.fnignis/canonical.sqlite3`. Có thể khai báo `DATABASE_URL` trong `<root>/.fnignis/.env` để dùng
một file SQLite khác nằm trong root hoặc một database PostgreSQL. Cấu hình, log, báo cáo và file nghiên
cứu của caller vẫn nằm trong `<root>/.fnignis/`.
File này phải là file thường, không cấp quyền cho group hay người dùng khác (Ignis tạo với quyền
0600), tối đa 32 KiB và chỉ chứa giá trị literal (không nội suy `${...}`) cho các khoá có trong file mẫu
`<root>/.fnignis/.env.example` do Ignis tạo. Vi phạm về file, khoá, giá trị hoặc cú pháp trả về
`CALLER_CONFIG_REFUSED`; đường dẫn SQLite tương đối hoặc nằm ngoài root trả về `ROOT_SCOPE_REQUIRED`. File `.env` riêng của server và `DATABASE_URL` do bootstrap ghi không quyết định
storage nhiệm vụ của caller, và cấu hình không bao giờ cấp quyền chạy probe nguồn.
`record_mission_research_work` ghi lệnh có phạm vi được chỉ định của host qua phiên stdio cục bộ,
kiểm tra quyền của nhiệm vụ cùng revision, epoch và dữ liệu đầu vào chính xác. Việc ghi lệnh
không chạy agent, gọi provider hay thu thập nguồn.

`execute_mission_follow_up(mission_id, follow_up_work_id, expected_research_epoch, idempotency_key)`
thực hiện công việc bổ sung chứng cứ đã ghi nhận qua phiên stdio cục bộ đang sở hữu tài nguyên.
Ignis kiểm tra phân công còn hiệu lực, khung đầu vào chính xác, ngân sách còn lại và quyền truy cập
nguồn được xác minh riêng trước khi tạo nhiệm vụ con hoặc thu thập. Công cụ không nhận truy vấn,
thông tin xác thực hay cờ cấp quyền từ người gọi. Thiếu bộ cung cấp quyền thực hiện thì yêu cầu
bị từ chối trước khi khởi tạo xác thực hoặc thu thập.
Kết quả đã được tiếp nhận nêu đúng nhiệm vụ cha, công việc, khoảng trống, phân công, nhiệm vụ con,
phần ngân sách giữ chỗ, lượt chạy và kết quả từng kênh. Yêu cầu lặp đọc lại cùng nhiệm vụ con;
kết quả chưa rõ vẫn giữ chỗ ngân sách và không mở lượt thu thập mới. Khi người gọi hủy yêu cầu,
Ignis dừng tác vụ đang sở hữu và chờ dọn dẹp. Vòng đời nhiệm vụ cha giữ nguyên; đọc snapshot không
cấp quyền thực hiện.

## 4. Ranh giới tool và triển khai

MCP server cục bộ có **53 tools**. Xem mô tả trực tiếp từ server để biết tham số chính xác;
các tool khám phá hằng ngày và nghiên cứu không giới hạn đã bị loại.
Workflow phát hành tạo image `ghcr.io/fioenix/fn-ignis:0.8.0` khi tag `v0.8.0` được push.
Image v0.7.0 không có quy trình được mô tả ở đây.
Chưa công bố cách cài qua PyPI. Chạy `.venv/bin/pytest tests/` (đúng phạm vi CI; các ca kiểm thử PostgreSQL bị bỏ qua nếu
`IGNIS_TEST_POSTGRES_DSN` không trỏ tới một database kiểm thử dùng một lần) và `uv lock --check`
để kiểm tra cục bộ. Bộ kiểm thử tự thay credential bằng giá trị trơ; nếu muốn tách hẳn khỏi
`.env` của checkout, dùng [cách cô lập cấu hình](../specs/014-evidence-factory/quickstart.md#isolated-settings). Xem [danh sách việc của Spec 011](../specs/011-evidence-grounded-product-reset/tasks.md)
cho các cổng PostgreSQL, pilot, tích hợp và phát hành cần chủ sở hữu quyết định. Các cổng còn mở
của Mission Relay, công việc nghiên cứu và bổ sung chứng cứ nằm trong
[danh sách việc của Spec 014](../specs/014-evidence-factory/tasks.md).
### Tìm kiếm TikTok qua trình duyệt host trên nhánh phát triển

Ba tool `prepare_host_browser_search`, `submit_host_browser_search` và
`cancel_host_browser_search` cung cấp đường thu thập chủ động chọn, chỉ trong nhiệm vụ được duyệt.
Host dùng phiên trình duyệt được cho phép và mở trang relay localhost. Nút "Open search" trên relay
mở đúng trang tìm kiếm công khai; `tab_script` do bước chuẩn bị trả về, chạy trong từng tab vừa mở, gửi kết quả về
relay và chỉ trả lại số đếm. Relay tự stage khi mọi truy vấn đã có kết quả; vẫn có thể điền form bằng
JSON giữ trong bộ nhớ như trước. MCP nhận kết quả bằng ID; không cần chép lại bản ghi qua mô hình,
xuất cookie hay mở cổng gỡ lỗi. Câu ghi công tác giả của TikTok bị bỏ khỏi trích đoạn trước khi trả
về hoặc lưu; nếu chưa nạp mẫu câu ghi công, bước chuẩn bị bị từ chối với mã
`AUTHOR_ATTRIBUTION_VOCABULARY_MISSING`.

Chế độ `TACTICAL` không khởi tạo database. Chế độ `MISSION` cần mission đã xác nhận,
`queries=[]` và `result_limit=20`; truy vấn, kể cả truy vấn phản biện, được lấy từ phạm vi đã duyệt.
Ignis kiểm tra lại phạm vi trong khóa ghi, lưu theo luồng evidence hiện có và trả run/frame chuẩn.
Lỗi ghi cần đọc lại journal/frame trước khi thay yêu cầu, không tự gửi lại.

Yêu cầu tối đa một giờ, payload form tối đa 1 MiB. Listener chỉ mở ở localhost, kiểm tra đúng
Host/Origin và đóng khi kết thúc. Chỉ số, ngày đăng và khoảng thời gian chưa đo vẫn là chưa biết.
Lưới video hữu hạn không đại diện cho toàn thị trường, không bao gồm bình luận và không phải
khuyến nghị kinh doanh. Host chỉ đóng tab do nhiệm vụ tạo, giữ nguyên trình duyệt và tab của chủ.

### Thu thập Threads qua host và so sánh đường thu thập

`prepare_host_browser_search` có tham số tùy chọn `source="threads"`. Khi bỏ qua tham số này,
tool giữ `source="tiktok"`. Submit và cancel vẫn nhận ba tham số ID. Tổng số tool vẫn là 53.
Threads chỉ thu thập qua trình duyệt host được cho phép. Phần thu thập Threads bằng Playwright
đã bị loại bỏ. Hai tool gợi ý và xu hướng cũ trả về `UNAVAILABLE/HOST_BROWSER_REQUIRED`.
Credential Threads đã lưu không chứng minh có thể thu thập. Ignis không kích hoạt đường API,
không probe quyền API và không tự chuyển sang cách thu thập dự phòng khi lỗi.

Reels vẫn dùng Playwright, không dùng cờ che giấu tự động hóa. Trang yêu cầu đăng nhập,
checkpoint, challenge, phản hồi không đọc được hoặc thiếu search envelope đều là kết quả
không khả dụng có lý do, không phải số 0 đã đo. Search envelope rỗng, đúng cấu trúc và đã được
xác minh có thể trả về `EMPTY_NO_DATA` cho từ khóa đã chạy. Kết quả này không chứng minh đã
bao phủ từ khóa khác hay biết rõ khoảng thời gian.

Threads `threads-search-top-v1` chỉ lấy mẫu Top hữu hạn đang hiển thị trên
`www.threads.com/search`. Hiện chỉ hỗ trợ cấu trúc trang tiếng Anh đã quan sát được.
Trang đang tải, khung trang rỗng hoặc toàn bộ bản ghi bị loại không chứng minh thị trường rỗng.
Thời điểm chụp và thời điểm đăng được giữ riêng. Chỉ số giữ nguyên chữ hiển thị và độ chính xác:
`1.4K` là số làm tròn, ô trống là chưa biết; shares không phải quotes. Số làm tròn không trở thành
tổng chính xác trong kỳ. Tiêu đề tác giả và câu ghi công bị bỏ trước khi trả receipt hoặc lưu.
Link dùng tham chiếu nội dung không chứa danh tính. Tên người trong văn bản tự do vẫn là một
giới hạn của bước làm sạch.

Trên cả trục seen và created, `collection_path_changed` từ chối hai đường thu thập đã xác định
nhưng khác nhau. `collection_path_unknown` từ chối một đường đã xác định so với một đường chưa biết.
`collection_path_mixed` từ chối khi một kỳ trộn nhiều đường đã xác định, hoặc trộn đường đã xác định
với đường chưa biết. Các ô này không có chỉ số hay chênh lệch. Hai đường đã xác định giống nhau
vẫn có thể so sánh. Khi cả hai kỳ chỉ có đường chưa biết, quy tắc và kết quả so sánh cũ được giữ
nguyên. Nhịp lấy mẫu, độ bao phủ, cách xếp theo ngày đăng và điều kiện đánh giá vẫn áp dụng.
