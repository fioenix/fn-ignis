-- 041_instagram_attribution.sql: Instagram attribution, not public-post content.
--
-- Instagram is Meta's sibling of Threads, whose accessibility wording "Photo by <author> on <date>"
-- G2 observed (036). The 2026-11-11 and 2026-11-12 Instagram keyword grids showed no attribution
-- in the 27 captions read; Spec 025 T029 rechecks this live. Do not add guessed translations.
-- System-owned vocabulary only: replay is idempotent and changes no schema or evidence.

INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('instagram_attribution', 'Photo by {author} on', 'ui_attribution', 'system')
ON CONFLICT (domain, term) DO NOTHING;
