-- 009: Topic label for display, separate from the cluster's identity key.
--
-- canonical_name is the most informative raw title in the group and stays the identity key:
-- cluster_id is a uuid5 of it, and trend_signals reference that id. It reads as one member's
-- post rather than a topic, so display now uses a summarised label instead. NULL means the row
-- predates this column, and readers fall back to canonical_name.

ALTER TABLE topic_clusters ADD COLUMN IF NOT EXISTS topic_label TEXT;
