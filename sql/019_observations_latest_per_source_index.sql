-- 019_observations_latest_per_source_index.sql: the index the top-cluster reader orders by.
--
-- `get_top_clusters` picks one observation per (cluster, source) -- the most recent in the
-- window -- and both backends express that as an ordering: PostgreSQL with DISTINCT ON, SQLite
-- with ROW_NUMBER(). Neither could serve that ordering from an index. `idx_observations_source`
-- leads on source_id and `idx_observations_cluster` on cluster_id, and neither carries the three
-- tie-break terms, so SQLite reported USE TEMP B-TREE FOR LAST 5 TERMS OF ORDER BY and sorted
-- every row in the window before discarding all but one per pair. Measured on 10,000
-- observations, the statement alone was 26.66 ms of a 34.75 ms read.
--
-- The column list is the ORDER BY, term for term and direction for direction. It has to be: an
-- index whose ordering merely resembles the query's still leaves the sort in place. The two
-- COALESCE terms are written the way the reader writes them, because an index on the bare
-- columns would not match an ORDER BY over the expressions -- metric_value and growth_velocity
-- are nullable, and the reader has always ranked a NULL as zero rather than letting it sort
-- wherever the backend puts nulls.
--
-- Partial, on the same two predicates the reader always applies. That is what keeps the index
-- small where it matters: 17,118 of the 18,597 observations the migration baseline measured are
-- legacy_publish_only, and none of them can ever be read by this path. Excluding them, rather
-- than indexing them and filtering afterwards, is the difference between an index over the
-- readable corpus and an index over the whole table. `observed_at IS NOT NULL` is deliberately
-- not a predicate here: it is implied by the ordering column being usable, and adding it would
-- stop a backend from matching the index unless the query repeats that term verbatim.
--
-- Both backends support partial and expression indexes, so this is one definition rather than
-- two. SQLite restates it in `_ensure_schema` because it does not read the sql/ files.
--
-- Adds no column, drops nothing, and changes no row. Re-applying it is a no-op through
-- IF NOT EXISTS, and dropping it makes the reader slow again rather than wrong.
CREATE INDEX IF NOT EXISTS idx_observations_latest_per_source
    ON observations (
        cluster_id,
        source_id,
        observed_at DESC,
        (COALESCE(metric_value, 0)) DESC,
        (COALESCE(growth_velocity, 0)) DESC,
        id DESC
    )
    WHERE cluster_id IS NOT NULL AND time_provenance = 'exact_ingestion';
