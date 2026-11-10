-- 040_retire_market_domain_vocabulary.sql: retire seeded market-domain vocabulary.
--
-- Measured on 2026-11-11: 104 system rows across seven domains, including the 69
-- local-market rows and 35 global-market rows. These buckets created false synonyms
-- and false Vietnamese-language evidence. The matching mechanisms are retired too.
-- The owner approved deleting these vocabulary rows without a backup; observations,
-- signals, missions and claims are not changed. Machinery domains stay intact.
--
-- 003 and 004 no longer seed these rows. Only system rows are removed; operator rows
-- remain stored and listed, inert. Idempotent: SQLite runs this after vocabulary replay
-- on every bootstrap; reapplying it on PostgreSQL deletes nothing further.

DELETE FROM market_lexicons
WHERE created_by = 'system'
  AND domain IN (
      'tech', 'ecommerce', 'fashion', 'common_vi',
      'global_saas_ai', 'global_ecommerce', 'global_fashion'
  );
