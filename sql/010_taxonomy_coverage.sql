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
-- Terms are stored without diacritics: SemanticClusterer folds both sides before matching. That
-- folding is why a bare short Vietnamese token must never be a keyword here: it erases the
-- distinction between different words, so "vang" covers "vang" (gold) and "vang" (resonant), and
-- "toc" covers "toc" (hair) and "toc" (speed). Adding those filed a bolero playlist under finance
-- and an esports bracket under beauty. Use compounds -- "gia vang", "nhuom toc", "phoi do" -- which
-- have no unaccented twin, and reserve single tokens for unambiguous loanwords and brand names.

INSERT INTO industry_taxonomies (industry_code, industry_name, keywords) VALUES
('tech', 'Tech & Electronics', ARRAY['ai', 'software', 'agent', 'bot', 'app', 'tool', 'hardware', 'laptop', 'phone', 'chatgpt', 'gpt', 'claude', 'gemini', 'automation', 'tu dong hoa', 'cong nghe', 'may tinh', 'dien thoai', 'phan mem', 'lap trinh', 'saas', 'api', 'cloud', 'no code', 'chatbot', 'prompt', 'blender', 'figma', 'notion']),
('ecommerce', 'E-Commerce & Retail', ARRAY['shop', 'shopee', 'lazada', 'order', 'shipping', 'don hang', 'chot don', 'tiki', 'sendo', 'tiktok shop', 'ban hang', 'gian hang', 'ton kho', 'gia si', 'nhap hang', 'affiliate', 'ma giam gia', 'freeship', 'khach hang', 'doanh thu', 'ty le chuyen doi']),
('fashion', 'Apparel & Accessories', ARRAY['fashion', 'clothing', 'linen', 'dress', 'shirt', 'outfit', 'style', 'local brand', 'quan ao', 'thoi trang', 'phoi do', 'phu kien', 'chat lieu', 'cotton', 'jeans', 'streetwear', 'mix do', 'do ni', 'so mi']),
('education', 'Education & Training', ARRAY['course', 'khoa hoc', 'hoc', 'tutorial', 'dao tao', 'huong dan', 'tieng anh', 'phat am', 'ngu phap', 'tu vung', 'luyen thi', 'ielts', 'toeic', 'giao vien', 'hoc sinh', 'sinh vien', 'bai giang', 'ky nang', 'chung chi', 'lop hoc', 'tu hoc', 'giao trinh']),
('beauty', 'Beauty & Personal Care', ARRAY['skincare', 'makeup', 'my pham', 'son', 'kem', 'duong da', 'serum', 'toner', 'sua rua mat', 'kem chong nang', 'tri mun', 'trang diem', 'nuoc hoa', 'nhuom toc', 'salon', 'spa', 'lam dep', 'duong am', 'tay trang', 'mat na', 'cham soc da']),
('finance', 'Financial Services', ARRAY['finance', 'tai chinh', 'dau tu', 'ngan hang', 'bank', 'chung khoan', 'crypto', 'gia vang', 'lai suat', 'tin dung', 'the tin dung', 'tiet kiem', 'bao hiem', 'co phieu', 'ty gia', 'thue', 'quy dau tu', 'trai phieu', 'vi dien tu'])
ON CONFLICT (industry_code) DO UPDATE SET keywords = EXCLUDED.keywords;
