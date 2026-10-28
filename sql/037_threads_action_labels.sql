-- Observed action SVG titles by primary UI locale; no evidence/schema rewrite.
-- Domain suffix is the locale, category is the counter kind. Add locales as rows, never positional guesses.
INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('threads_action_labels_en', 'Like', 'likes', 'system'),
('threads_action_labels_en', 'Reply', 'replies', 'system'),
('threads_action_labels_en', 'Repost', 'reposts', 'system'),
('threads_action_labels_en', 'Share', 'shares', 'system'),
('threads_action_labels_vi', 'Thích', 'likes', 'system'),
('threads_action_labels_vi', 'Trả lời', 'replies', 'system'),
('threads_action_labels_vi', 'Đăng lại', 'reposts', 'system'),
('threads_action_labels_vi', 'Chia sẻ', 'shares', 'system')
ON CONFLICT (domain, term) DO NOTHING;
