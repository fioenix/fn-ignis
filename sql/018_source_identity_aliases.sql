-- 018_source_identity_aliases.sql: the ledger that reconciles a permalink shortcode to the
-- primary key of the same object.
--
-- sql/016 gave Threads and Instagram two namespaces each -- post/post_shortcode and
-- reel/reel_shortcode -- because the Graph API's numeric primary key and the shortcode in a
-- permalink are different identifier spaces with no arithmetic between them. Filing both under
-- one prefix would have asserted the values are comparable, and an all-digit shortcode would then
-- have collided with somebody else's primary key. The cost of keeping them apart is that a
-- sighting reached only by permalink files a second row for an object the corpus already holds.
--
-- This table closes that gap with evidence rather than with string equality. Every Threads and
-- Reels emission path carries both values on one record -- the Graph responses request `id` and
-- `permalink` together, the browser payloads carry `pk` beside `code` -- so ordinary ingress
-- witnesses the relationship. Nothing else registers an alias: no backfill, no heuristic, and
-- never two values that merely look alike.
--
-- Three properties the columns are chosen for:
--
-- - Directed. alias_external_id is always a shortcode and canonical_external_id always a primary
--   key, enforced by the writer, so the ledger is single-hop by construction. There is no
--   transitive closure to maintain and no way for one canonical object to point at another.
-- - One canonical per alias, forever. UNIQUE (platform, alias_external_id) is the conflict
--   protection: two records claiming one shortcode for different primary keys cannot both be
--   right, the ledger cannot tell which is, so it keeps what it holds and the second record is
--   filed under its own primary key. Two rows are a gap the audit can measure; a merge would be
--   silent and unrecoverable.
-- - Provenance on the row. witnessed_by says what believed this and recorded_at says when, which
--   is what makes a wrong alias reviewable after the fact.
--
-- No foreign key to sources. An alias is a statement about two identifiers, and it stays true
-- whether or not either object currently has a row -- a REFERENCES clause here would make the
-- ledger depend on retention decisions about a different table.
CREATE TABLE IF NOT EXISTS source_identity_aliases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform VARCHAR(30) NOT NULL,
    -- Both carry their namespace, as "<kind>:<value>", exactly as sources.external_id does.
    alias_external_id TEXT NOT NULL,
    canonical_external_id TEXT NOT NULL,
    witnessed_by VARCHAR(40) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT source_identity_aliases_alias_key UNIQUE (platform, alias_external_id),
    -- An identifier aliasing itself is a no-op that would still occupy the alias slot and block
    -- the real reconciliation from ever being recorded.
    CONSTRAINT source_identity_aliases_not_self CHECK (alias_external_id <> canonical_external_id)
);
