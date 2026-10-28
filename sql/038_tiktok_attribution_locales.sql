-- Locale-qualified TikTok attribution vocabulary, mirroring 037's domain suffix.
-- Additive only: preserve 034 and all evidence. Only the observed Vietnamese wording is seeded.
INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('tiktok_attribution_vi', 'do {author} tạo với', 'ui_attribution', 'system')
ON CONFLICT (domain, term) DO NOTHING;
