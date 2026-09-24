-- 020_retire_ambiguous_tiktok_ui_noise.sql: three ordinary words leave the TikTok UI-noise guard.
--
-- Measured through the plugin on 15,771 real titles, the grid guard rejected 46, and nearly all
-- were genuine public posts. Three rows did almost all of it: 'live' (40), 'thông báo' (3) and
-- 'tin nhắn' (2). They are everyday words, not TikTok UI strings. The connector crawls the
-- explore and search grids, never the notification or inbox surface this wording came from, so
-- the privacy promise rests on that structure; this text filter is a secondary layer. 'đang phát
-- trực tiếp' fired once and was right, and the remaining phrases are specific UI wording that
-- never fired; all of them stay.
--
-- 013 has shipped and is left as it is. 'live ' was seeded with a trailing space, so rows are
-- matched on trim(term). Only system rows are removed: a term an operator registers again later
-- is a deliberate choice, and this migration should not keep undoing it.
--
-- Idempotent. The SQLite bootstrap re-inserts 013 on every start and runs this right after it,
-- so a restart cannot bring the rows back; on PostgreSQL re-running it deletes nothing.

DELETE FROM market_lexicons
WHERE domain = 'tiktok_ui_noise'
  AND created_by = 'system'
  AND trim(term) IN ('live', 'thông báo', 'tin nhắn');
