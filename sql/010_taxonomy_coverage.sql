-- 010: Widen industry_taxonomies keyword coverage, and cover general information verticals.
--
-- Scope decision, 09/09/2026: the taxonomy tracks news, sports, entertainment, health, food,
-- travel, real estate and mobility alongside the six commercial verticals, because reading a
-- market means reading the domains around it. `unclassified` therefore keeps a narrower and more
-- useful meaning: no vertical claimed the cluster at all.
--
-- Six verticals held 44 keywords between them, so the classifier left 378 live clusters in
-- `unclassified` even when the topic sat squarely inside a tracked vertical: "chatgpt va gpt-6"
-- and "meo phat am tieng anh" both failed for want of a keyword, not for want of a matcher.
--
-- The keyword arrays here are identical to the seed in sql/003_market_lexicons.sql, which is
-- what a fresh SQLite database bootstraps from. tests/unit/test_taxonomy_coverage.py fails if
-- the two files drift apart, because a drift would leave the two backends classifying
-- differently -- a parity gap this project has been bitten by before.
--
-- Terms are stored WITH diacritics, and matched with diacritics.
--
-- Stripping Vietnamese tones before matching destroys the word. "vang" is both gold and
-- resonant; "toc" is both hair and speed; "chinh phu" is both the government and a prefix of
-- "chinh phuc" (to conquer). Folding first and guessing afterwards produced a run of wrong
-- categories -- a bolero playlist under finance, an esports bracket under beauty, a Roblox
-- cluster under automotive -- each of which was patched separately before the cause was
-- accepted. Accented text is compared to accented terms, which is exact.
--
-- A title the author wrote without tones is matched on folded forms instead. The ambiguity is
-- then in the input rather than introduced by us, and the corroboration and signal-share rules
-- in SemanticClusterer still apply.
--
-- Multi-word terms match on word boundaries. Raw substring matching is what let "o to" fire
-- inside "cho toi": the same anti-pattern recorded on 03/09 when "Abundance" was rejected for
-- containing "dance".

INSERT INTO industry_taxonomies (industry_code, industry_name, keywords) VALUES
('tech', 'Tech & Electronics', ARRAY['ai', 'software', 'agent', 'bot', 'app', 'tool', 'hardware', 'laptop', 'chatgpt', 'gpt', 'claude', 'gemini', 'automation', 'blender', 'figma', 'notion', 'saas', 'api', 'cloud', 'chatbot', 'prompt', 'no code', 'tự động hóa', 'công nghệ', 'máy tính', 'điện thoại', 'phần mềm', 'lập trình']),
('ecommerce', 'E-Commerce & Retail', ARRAY['shop', 'shopee', 'lazada', 'order', 'shipping', 'tiki', 'sendo', 'affiliate', 'freeship', 'tiktok shop', 'đơn hàng', 'chốt đơn', 'bán hàng', 'gian hàng', 'tồn kho', 'giá sỉ', 'nhập hàng', 'mã giảm giá', 'khách hàng', 'doanh thu', 'tỷ lệ chuyển đổi']),
('fashion', 'Apparel & Accessories', ARRAY['fashion', 'clothing', 'linen', 'dress', 'shirt', 'outfit', 'style', 'cotton', 'jeans', 'streetwear', 'local brand', 'quần áo', 'thời trang', 'phối đồ', 'phụ kiện', 'chất liệu', 'mix đồ', 'sơ mi', 'đồ nỉ']),
('education', 'Education & Training', ARRAY['course', 'tutorial', 'ielts', 'toeic', 'khóa học', 'đào tạo', 'hướng dẫn', 'tiếng anh', 'phát âm', 'ngữ pháp', 'từ vựng', 'luyện thi', 'giáo viên', 'học sinh', 'sinh viên', 'bài giảng', 'kỹ năng', 'chứng chỉ', 'lớp học', 'tự học', 'giáo trình', 'đại học']),
('beauty', 'Beauty & Personal Care', ARRAY['skincare', 'makeup', 'serum', 'toner', 'salon', 'spa', 'mỹ phẩm', 'dưỡng da', 'sữa rửa mặt', 'kem chống nắng', 'trị mụn', 'trang điểm', 'nước hoa', 'nhuộm tóc', 'tẩy tóc', 'làm đẹp', 'dưỡng ẩm', 'tẩy trang', 'mặt nạ', 'chăm sóc da']),
('finance', 'Financial Services', ARRAY['finance', 'bank', 'crypto', 'tài chính', 'đầu tư', 'ngân hàng', 'chứng khoán', 'giá vàng', 'lãi suất', 'tín dụng', 'thẻ tín dụng', 'tiết kiệm', 'bảo hiểm', 'cổ phiếu', 'tỷ giá', 'quỹ đầu tư', 'trái phiếu', 'ví điện tử']),
('news', 'News & Current Affairs', ARRAY['thời sự', 'tin nóng', 'tin tức', 'bản tin', 'chính trị', 'pháp luật', 'tòa án', 'công an', 'quốc hội', 'chính phủ', 'thiên tai', 'bão lụt', 'giao thông', 'tai nạn']),
('sports', 'Sports', ARRAY['esports', 'marathon', 'pickleball', 'champions league', 'world cup', 'sea games', 'bóng đá', 'thể thao', 'thi đấu', 'giải đấu', 'tuyển việt nam', 'ngoại hạng anh', 'cầu thủ', 'huấn luyện viên', 'tỷ số', 'vòng bảng', 'bàn thắng', 'chạy bộ']),
('entertainment', 'Entertainment & Media', ARRAY['showbiz', 'netflix', 'kpop', 'idol', 'anime', 'concert', 'gameshow', 'liên quân mobile', 'phim mới', 'diễn viên', 'ca sĩ', 'âm nhạc', 'nghệ sĩ', 'rap việt', 'truyện tranh', 'game mobile', 'phòng vé']),
('health', 'Health & Wellness', ARRAY['wellness', 'yoga', 'vaccine', 'sức khỏe', 'bệnh viện', 'bác sĩ', 'dinh dưỡng', 'tập gym', 'giấc ngủ', 'tâm lý', 'thực phẩm chức năng', 'dịch bệnh', 'giảm cân', 'thiền định', 'khám bệnh']),
('food', 'Food & Beverage', ARRAY['đồ ăn', 'quán ăn', 'nhà hàng', 'ẩm thực', 'công thức nấu', 'nấu ăn', 'cà phê', 'trà sữa', 'ăn uống', 'món ngon', 'đặt món', 'review quán', 'nguyên liệu', 'đồ uống']),
('travel', 'Travel & Hospitality', ARRAY['tour', 'homestay', 'resort', 'visa', 'checkin', 'du lịch', 'khách sạn', 'vé máy bay', 'điểm đến', 'lịch trình', 'hộ chiếu', 'nghỉ dưỡng', 'vé tàu']),
('realestate', 'Real Estate & Construction', ARRAY['bất động sản', 'căn hộ', 'chung cư', 'nhà phố', 'đất nền', 'sổ hồng', 'thuê nhà', 'môi giới', 'xây dựng', 'nội thất', 'quy hoạch', 'giá nhà']),
('auto', 'Automotive & Mobility', ARRAY['vinfast', 'test drive', 'xe máy', 'ô tô', 'xe điện', 'xe hơi', 'lái xe', 'bảng giá xe', 'đăng kiểm', 'phụ tùng', 'xe tải', 'bảo dưỡng xe', 'xe ga'])
ON CONFLICT (industry_code) DO UPDATE SET keywords = EXCLUDED.keywords;
