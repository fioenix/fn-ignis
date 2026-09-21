-- 017_research_workspace.sql: the durable research boundary and the two analytical surfaces.
--
-- A chat session belongs to the Agent host that opened it. A research has to outlive that, be
-- reopenable from a different host, and keep its evidence attributable to the question it was
-- collected to answer. Three things carry that here:
--
--   research_workspaces     the research identity and its user-visible child folder
--   market_brief_revisions  the immutable, requester-confirmed frame that authorizes a Market run
--   mission_run_journals    one exclusive recovery record per run
--
-- The existing research_missions record is EXTENDED, not replaced. A second mission table would
-- mean two mission identities for one research and two places every later read has to look; the
-- columns added below are what a mission needs to say which research owns it and which question
-- it is answering.
--
-- Nothing here touches sources, observations or mission_evidence. Source identity, observation
-- immutability and the mission-to-observation ledger are unchanged; this migration adds scope
-- and provenance around them.

-- 1. research_workspaces -- one row per research.
--
-- root_path is recorded rather than derived: the same shared database serves several host
-- workspaces, and two of them may legitimately hold a research with the same slug. The slug
-- alone is therefore not the identity; workspace_id is, and UNIQUE is taken over the pair.
CREATE TABLE IF NOT EXISTS research_workspaces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug VARCHAR(64) NOT NULL,
    name TEXT,
    root_path TEXT NOT NULL,
    -- Bumped when a workspace on disk stops being readable by a newer build. A workspace naming
    -- a higher version is reported INCOMPATIBLE rather than opened and partially understood.
    format_version INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'READY',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT research_workspaces_root_slug_key UNIQUE (root_path, slug),
    CONSTRAINT research_workspaces_status_check CHECK (status IN ('READY', 'INCOMPATIBLE'))
);

CREATE INDEX IF NOT EXISTS idx_research_workspaces_slug ON research_workspaces (slug);

-- 2. research_missions gains its workspace, its surface and its lineage.
--
-- All five columns are nullable, and that is the honest shape. Missions written before this
-- migration belong to no workspace and answered no declared surface; a NOT NULL DEFAULT
-- 'MARKET' would retroactively claim they were hypothesis-driven investigations and gate every
-- one of them on a Brief nobody was ever asked to confirm.
ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS workspace_id UUID
    REFERENCES research_workspaces(id) ON DELETE CASCADE;
ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS surface VARCHAR(20);
ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS parent_attention_mission_id UUID
    REFERENCES research_missions(id) ON DELETE SET NULL;
ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS parent_cluster_id UUID
    REFERENCES topic_clusters(id) ON DELETE SET NULL;
ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS brief_revision_id UUID;
-- The Market mission this one revises. One canonical relation for "the requester changed a
-- confirmed Brief", recorded on the new mission rather than on the old one: the old mission is
-- immutable from the moment its Brief was confirmed, and a pointer written onto it afterwards
-- would be an edit to history made by the thing that came later. ON DELETE SET NULL, because
-- losing the revised mission must not cascade away the revision that replaced it.
ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS revises_mission_id UUID
    REFERENCES research_missions(id) ON DELETE SET NULL;

DO $$
BEGIN
    ALTER TABLE research_missions
        ADD CONSTRAINT research_missions_surface_check
        CHECK (surface IS NULL OR surface IN ('ATTENTION', 'MARKET'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- An Attention mission has no Brief, by definition. Stating it as a constraint keeps a caller
-- from binding one and then reading an Opportunity Index off the result.
DO $$
BEGIN
    ALTER TABLE research_missions
        ADD CONSTRAINT research_missions_attention_has_no_brief_check
        CHECK (surface <> 'ATTENTION' OR brief_revision_id IS NULL);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Only a Market mission revises anything. An Attention mission has no Brief to change, so a
-- revision pointer on one would describe a change that cannot have happened.
DO $$
BEGIN
    ALTER TABLE research_missions
        ADD CONSTRAINT research_missions_attention_revises_nothing_check
        CHECK (surface <> 'ATTENTION' OR revises_mission_id IS NULL);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- A mission cannot revise itself: that is a cycle of length one, and it would make the head of
-- a research line unfindable.
DO $$
BEGIN
    ALTER TABLE research_missions
        ADD CONSTRAINT research_missions_revises_another_mission_check
        CHECK (revises_mission_id IS NULL OR revises_mission_id <> id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_research_missions_workspace
    ON research_missions (workspace_id, created_at DESC);

-- 3. market_brief_revisions -- the immutable frame that authorizes one Market mission.
--
-- One confirmed revision per Market mission, enforced by UNIQUE (mission_id). Changing a
-- confirmed Brief therefore cannot update in place: it has to create a new revision under a new
-- mission, which is the whole point. revision_number is monotonic inside a workspace and is
-- never reused, so the lineage of a hypothesis stays readable after the fact.
--
-- There is no draft table and no transcript table. The host Agent runs the Q&A in its own
-- context; only the complete confirmed payload arrives here.
CREATE TABLE IF NOT EXISTS market_brief_revisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL REFERENCES research_workspaces(id) ON DELETE CASCADE,
    mission_id UUID NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    decision TEXT NOT NULL,
    target_user TEXT NOT NULL,
    problem TEXT NOT NULL,
    geo VARCHAR(10) NOT NULL,
    timeframe VARCHAR(20) NOT NULL,
    hypothesis TEXT NOT NULL,
    -- At least one useful disconfirming condition. A Brief with an empty array is a hypothesis
    -- that cannot lose, which is not a hypothesis.
    falsifiers TEXT[] NOT NULL,
    confirmed_by TEXT NOT NULL,
    confirmed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT market_brief_revisions_mission_key UNIQUE (mission_id),
    CONSTRAINT market_brief_revisions_workspace_number_key UNIQUE (workspace_id, revision_number),
    CONSTRAINT market_brief_revisions_falsifiers_check CHECK (array_length(falsifiers, 1) >= 1)
);

CREATE INDEX IF NOT EXISTS idx_market_brief_revisions_workspace
    ON market_brief_revisions (workspace_id, revision_number DESC);

-- 4. mission_run_journals -- one exclusive recovery record per run.
--
-- journal_path is UNIQUE because the filesystem already granted it exclusively: the path is
-- taken with an exclusive create, and this row records the name that was granted rather than
-- reserving one the filesystem has not agreed to. sequence is allocated after the timestamp and
-- is fixed width on disk, so two runs starting in the same second still get distinct names.
CREATE TABLE IF NOT EXISTS mission_run_journals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID NOT NULL REFERENCES research_workspaces(id) ON DELETE CASCADE,
    mission_id UUID NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    journal_path TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'STARTED',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Absent for a run that was interrupted. NULL says the run did not finish; NOW() would say
    -- it finished the moment someone asked.
    completed_at TIMESTAMPTZ,
    CONSTRAINT mission_run_journals_path_key UNIQUE (journal_path)
);

CREATE INDEX IF NOT EXISTS idx_mission_run_journals_mission
    ON mission_run_journals (mission_id, started_at DESC);

-- 5. mission_writer_claims -- at most one active writer per mission.
--
-- A separate table rather than a column on research_missions: the claim is run state, the
-- mission is research state, and an INSERT into a table whose primary key is mission_id is a
-- single atomic operation on both backends. A second writer's INSERT conflicts, which is the
-- clear failure the contract asks for rather than a silently lost update.
CREATE TABLE IF NOT EXISTS mission_writer_claims (
    mission_id UUID PRIMARY KEY REFERENCES research_missions(id) ON DELETE CASCADE,
    run_id UUID NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
