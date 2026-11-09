-- Retire historical category identifiers atomically. A populated store must use the
-- explicit projection/apply command; this receipt is a backstop, not authorization.
DO $retire$
DECLARE
    -- Retired data identifiers only, not a runtime lexicon or classification vocabulary.
    former_codes CONSTANT text[] := ARRAY[
        'auto', 'beauty', 'ecommerce', 'education', 'entertainment', 'fashion', 'finance',
        'food', 'health', 'news', 'realestate', 'sports', 'tech', 'travel'
    ];
    zero_counts jsonb;
    changed_count bigint;
BEGIN
    PERFORM set_config('ignis.taxonomy_changed_count', '0', true);
    IF to_regclass('public.industry_taxonomies') IS NULL THEN
        RETURN;
    END IF;
    LOCK TABLE public.topic_clusters IN ACCESS EXCLUSIVE MODE;
    -- Recheck after waiting: another retirement may have committed while we waited.
    IF to_regclass('public.industry_taxonomies') IS NULL THEN
        RETURN;
    END IF;
    LOCK TABLE public.industry_taxonomies IN ACCESS EXCLUSIVE MODE;
    IF EXISTS (SELECT 1 FROM public.topic_clusters) THEN
        IF coalesce(current_setting('ignis.taxonomy_projection_digest', true), '')
            !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'TAXONOMY_PROJECTION_REQUIRED';
        END IF;
    ELSE
        SELECT jsonb_object_agg(code, 0) INTO zero_counts FROM unnest(former_codes) AS code;
        RAISE NOTICE '%', jsonb_build_object(
            'format_version', 'ignis-taxonomy-retirement-v1',
            'migration_id', '039_remove_seeded_taxonomy',
            'reset_counts', zero_counts, 'reset_total', 0,
            'target_digest', '533f4628e97ebef74a27657a8a11a6f9c5d1ba0444968e3d110a9ad23630c011',
            'invariants', jsonb_build_object('category_only', true, 'evidence_unchanged', true)
        );
    END IF;
    UPDATE public.topic_clusters SET category = 'unclassified' WHERE category = ANY(former_codes);
    GET DIAGNOSTICS changed_count = ROW_COUNT;
    PERFORM set_config('ignis.taxonomy_changed_count', changed_count::text, true);
    DROP TABLE public.industry_taxonomies;
END
$retire$;
