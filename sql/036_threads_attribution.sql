-- 036_threads_attribution.sql: observed Threads attribution, not public-post content.
--
-- G2 observed the English accessibility wording "Photo by <author> on <date>".
-- This is the only observed locale; do not add guessed translations. The host
-- sanitizer removes the attribution before any receipt or stored observation.
-- System-owned vocabulary only: replay is idempotent and changes no schema or evidence.

INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('threads_attribution', 'Photo by {author} on', 'ui_attribution', 'system')
ON CONFLICT (domain, term) DO NOTHING;
