-- 013_tiktok_ui_noise.sql: the TikTok notification and inbox wording, out of tiktok_plugin.py.
--
-- The video-grid scraper rejects any card whose text matches one of these, which is how the
-- plugin keeps its promise never to ingest the operator's own notifications, inbox or private
-- interactions. It was a Python list, and that made it a privacy guard that only covered
-- Vietnamese: a Korean or Japanese session got no filtering at all and no way to add any
-- without a release. Adding a locale now means adding rows here.
--
-- System-owned like the 012 domains, so the SQLite bootstrap re-applies it on every start.

INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('tiktok_ui_noise', 'follow bạn', 'ui_notification', 'system'),
('tiktok_ui_noise', 'bắt đầu follow', 'ui_notification', 'system'),
('tiktok_ui_noise', 'thích bình luận', 'ui_notification', 'system'),
('tiktok_ui_noise', 'thích video', 'ui_notification', 'system'),
('tiktok_ui_noise', 'đã thích', 'ui_notification', 'system'),
('tiktok_ui_noise', 'bình luận của bạn', 'ui_notification', 'system'),
('tiktok_ui_noise', 'đăng lại', 'ui_notification', 'system'),
('tiktok_ui_noise', 'follow lại', 'ui_notification', 'system'),
('tiktok_ui_noise', 'tin nhắn', 'ui_inbox', 'system'),
('tiktok_ui_noise', 'hộp thư', 'ui_inbox', 'system'),
('tiktok_ui_noise', 'thông báo', 'ui_inbox', 'system'),
('tiktok_ui_noise', 'live ', 'ui_live', 'system'),
('tiktok_ui_noise', 'đang phát trực tiếp', 'ui_live', 'system')
ON CONFLICT (domain, term) DO NOTHING;

-- The commercial-intent probe fired at Google Suggest while collecting TikTok search guides.
-- Its phrasing was compiled in, in Vietnamese, and ran for every geo: a US keyword was probed
-- with a Vietnamese phrase. One template per geo now, DEFAULT for everywhere else.
INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('tiktok_suggest_templates_vn', 'cách làm {}', 'intent_probe', 'system'),
('tiktok_suggest_templates_default', 'how to make {}', 'intent_probe', 'system')
ON CONFLICT (domain, term) DO NOTHING;
