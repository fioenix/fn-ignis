-- English TikTok attribution wording, additive like 038; rewrites no stored evidence.
-- Observed 2026-11-09 on 12 of 12 public search tiles with the interface in English.
INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('tiktok_attribution_en', 'created by {author} with', 'ui_attribution', 'system')
ON CONFLICT (domain, term) DO NOTHING;
