-- 034_tiktok_attribution.sql: TikTok's author attribution wording, so host excerpts drop the poster.
--
-- TikTok's public search tile labels its video image with the caption followed by a sentence that
-- names the poster and the sound, for example "<caption> do <author> tạo với bản nhạc <sound>".
-- Spec 012 kept that label verbatim; Constitution VII forbids keeping who said something, and a live
-- trial on 26/10/2026 returned twelve excerpts that each ended in a display name. The host-browser
-- validator removes the rightmost match of a template below and everything after it.
--
-- {author} marks where the display name sits. Only wording observed live is seeded: adding a
-- locale means adding the row TikTok actually renders for it. Host-browser preparation fails
-- closed while this domain is empty, rather than accepting excerpts it cannot clean.
--
-- System-owned like 013, so the SQLite bootstrap re-applies it on every start. Seeds vocabulary
-- rows only; it transforms no stored evidence.

INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('tiktok_attribution', 'do {author} tạo với', 'ui_attribution', 'system')
ON CONFLICT (domain, term) DO NOTHING;
