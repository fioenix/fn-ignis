-- 010: Widen industry_taxonomies keyword coverage.
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
-- Terms are stored without diacritics: SemanticClusterer folds both sides before matching.

INSERT INTO industry_taxonomies (industry_code, industry_name, keywords) VALUES
('tech', 'Tech & Electronics', ARRAY['ai', 'software', 'agent', 'bot', 'app', 'tool', 'hardware', 'laptop', 'phone', 'chatgpt', 'gpt', 'claude', 'gemini', 'automation', 'tu dong hoa', 'cong nghe', 'may tinh', 'dien thoai', 'phan mem', 'lap trinh', 'code', 'saas', 'api', 'cloud', 'blender', 'no code', 'chatbot', 'model', 'prompt']),
('ecommerce', 'E-Commerce & Retail', ARRAY['shop', 'shopee', 'lazada', 'order', 'shipping', 'don hang', 'chot don', 'tiki', 'sendo', 'tiktok shop', 'ban hang', 'livestream', 'ship', 'gian hang', 'ton kho', 'gia si', 'nhap hang', 'affiliate', 'ma giam gia', 'freeship', 'khach hang', 'doanh thu', 'chuyen doi']),
('fashion', 'Apparel & Accessories', ARRAY['fashion', 'clothing', 'linen', 'dress', 'shirt', 'outfit', 'style', 'local brand', 'quan ao', 'thoi trang', 'phoi do', 'ao', 'quan', 'vay', 'dam', 'giay', 'tui', 'phu kien', 'size', 'chat lieu', 'cotton', 'jeans', 'streetwear', 'mix do']),
('education', 'Education & Training', ARRAY['course', 'khoa hoc', 'hoc', 'tutorial', 'dao tao', 'huong dan', 'tieng anh', 'phat am', 'ngu phap', 'tu vung', 'luyen thi', 'ielts', 'toeic', 'giao vien', 'hoc sinh', 'sinh vien', 'bai giang', 'ky nang', 'chung chi', 'lop hoc', 'tu hoc', 'giao trinh']),
('beauty', 'Beauty & Personal Care', ARRAY['skincare', 'makeup', 'my pham', 'son', 'kem', 'duong da', 'serum', 'toner', 'sua rua mat', 'kem chong nang', 'tri mun', 'mun', 'trang diem', 'nuoc hoa', 'toc', 'nhuom toc', 'salon', 'spa', 'lam dep', 'duong am', 'tay trang', 'mat na']),
('finance', 'Financial Services', ARRAY['finance', 'tai chinh', 'dau tu', 'ngan hang', 'bank', 'chung khoan', 'crypto', 'vang', 'gia vang', 'lai suat', 'tin dung', 'the tin dung', 'vay', 'tiet kiem', 'bao hiem', 'co phieu', 'ty gia', 'usd', 'thue', 'quy dau tu', 'trai phieu', 'vi dien tu'])
ON CONFLICT (industry_code) DO UPDATE SET keywords = EXCLUDED.keywords;
