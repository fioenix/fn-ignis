-- 016_source_observation_model.sql: the three entities the corpus already contains.
--
-- trend_signals conflated three things: the external object, the act of observing it, and one
-- mission's claim on that observation. The baseline in docs/migrations/ measured what that
-- conflation costs -- 1,927 canonical objects hidden inside 15,938 rows, 10 URLs reporting two
-- titles, 172 identities sitting under more than one cluster, and 2 missions each holding two
-- observations of one source that any UNIQUE(mission_id, source_id) would silently delete.
--
-- This migration creates the tables only. It moves no data: the backfill is a separate step that
-- has to reconcile against the four digests in
-- docs/migrations/2026-09-10-source-observation-baseline.json, and a CREATE that also backfills
-- cannot be reviewed against them one at a time.
--
-- No hypertable here. Timescale needs its partitioning column NOT NULL, and observed_at is
-- deliberately nullable: a legacy_publish_only observation has no known ingestion time, and a
-- NULL says so where NOW() would have invented one.

-- 1. sources -- one row per external object, keyed on what the platform calls it.
--
-- external_id carries the object namespace, as "<kind>:<value>" (video:dQw4w9WgXcQ,
-- hashtag:aothun, keyword:ao thun). The namespace has to be inside the key, not beside it: on
-- TikTok a hashtag and a video are different objects on one platform, so a hashtag literally
-- named "12345" and item 12345 must not become one row. Keeping it in the same column is what
-- lets UNIQUE(platform, external_id) be the whole identity rather than most of it.
CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform VARCHAR(30) NOT NULL,
    external_id TEXT NOT NULL,
    -- How the identity was resolved, for audit only: 'metadata_external_id' where the connector
    -- recorded the platform's id, 'url_external_id' where it was parsed back out of the URL.
    -- Never part of the key -- the same video reached the corpus by both routes 3 times, and
    -- keying on the route would file it as two objects.
    identity_source VARCHAR(30),
    canonical_url TEXT,
    CONSTRAINT sources_platform_external_id_key UNIQUE (platform, external_id)
);

-- No first_seen_at or last_seen_at here. When a source was seen is already in observations, one
-- row per sighting, and a pair of columns summarising them is a second copy of that truth that
-- every write would have to keep in step. The backfill could not fill them honestly either:
-- 17,118 of the 18,597 observations have no known ingestion time, so NOW() would invent a
-- lifecycle rather than record one. If a query needs the range, derive it from the
-- exact_ingestion observations, or build a projection with its own rebuild contract.

-- No title and no cluster_id on this table, by measurement rather than by taste: 10 URLs in the
-- corpus reported two different titles, and 172 identities appear under more than one cluster.
-- Both are things observed about a source at a point in time, so both live on the observation.

-- 2. observations -- one row per collection event, immutable once written.
CREATE TABLE IF NOT EXISTS observations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    cluster_id UUID REFERENCES topic_clusters(id) ON DELETE SET NULL,
    -- When this harness collected the observation. NULL only where that time was never recorded.
    observed_at TIMESTAMPTZ,
    -- What the platform says about the content. NULL where the platform reports nothing.
    published_at TIMESTAMPTZ,
    -- Which clock observed_at came from. 17,118 of the 18,597 observations the baseline
    -- reconstructed are legacy_publish_only: written before sql/015 by a code path that stamped
    -- captured_at with the publish time. Labelling them is the only honest option, because the
    -- true collection time was never written down and cannot be recovered.
    time_provenance VARCHAR(30) NOT NULL,
    observed_title TEXT,
    metric_value DOUBLE PRECISION DEFAULT 0,
    growth_velocity DOUBLE PRECISION DEFAULT 0,
    geo_code VARCHAR(10) DEFAULT 'VN',
    source_url TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT observations_time_provenance_check CHECK (
        time_provenance IN ('exact_ingestion', 'legacy_publish_only', 'unknown')
    ),
    -- exact_ingestion is a claim about a known clock, so it has to have one.
    CONSTRAINT observations_exact_ingestion_has_a_clock CHECK (
        time_provenance <> 'exact_ingestion' OR observed_at IS NOT NULL
    )
);

-- Deliberately no UNIQUE over (source_id, observed_at, metric_value) or any subset of it. It
-- would look tidy and would delete real data: rows in the corpus matching on those three carry
-- three distinct growth_velocity values, and two collection events are allowed to be identical
-- on every field. The surrogate id is what keeps them apart.
CREATE INDEX IF NOT EXISTS idx_observations_source ON observations (source_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_observations_cluster ON observations (cluster_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_observations_observed_at ON observations (observed_at DESC);

-- 3. mission_evidence -- which observation a mission actually looked at.
--
-- UNIQUE on (mission_id, observation_id), never on (mission_id, source_id). Two missions may
-- claim one source, and one mission may claim two observations of it; the baseline found 2
-- missions in exactly that state, so the narrower key is a measured requirement.
CREATE TABLE IF NOT EXISTS mission_evidence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mission_id UUID NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    observation_id UUID NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT mission_evidence_mission_observation_key UNIQUE (mission_id, observation_id)
);

CREATE INDEX IF NOT EXISTS idx_mission_evidence_observation ON mission_evidence (observation_id);
