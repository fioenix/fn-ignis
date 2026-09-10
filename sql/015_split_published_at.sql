-- 015_split_published_at.sql: captured_at meant two things; give the second one its own column.
--
-- Measured on 09/09/2026: of the fifteen places a connector set captured_at, three set the
-- content's publish time instead of the ingestion time -- both YouTube sites and the Google
-- Trends RSS feed. Those three belong to the connectors holding most of the corpus, so every
-- query filtering on captured_at was mixing two clocks: for YouTube a 30-day window meant
-- "videos published in the last 30 days", for Threads "posts we scraped in the last 30 days".
--
-- It also explains the platform skew in a 30-day window. 14,813 YouTube rows carry publish
-- dates spread over three months, so they fill the whole window at once, while the browser
-- connectors only populate the days a pass actually ran.
--
-- From here: captured_at is always the ingestion time and is the only clock timeframe queries
-- use. published_at is what the platform reports about the content, NULL where the platform
-- reports nothing.

ALTER TABLE trend_signals ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_trend_signals_published_at
    ON trend_signals (published_at DESC NULLS LAST);

-- Backfill, exact where the platform's own value was kept in metadata. YouTube, Threads and
-- Reels all record published_at there, so this is the platform's value, not a guess.
UPDATE trend_signals
SET published_at = (metadata->>'published_at')::timestamptz
WHERE published_at IS NULL
  AND metadata ? 'published_at'
  AND COALESCE(metadata->>'published_at', '') <> ''
  AND (metadata->>'published_at') ~ '^\d{4}-\d{2}-\d{2}';

-- The Google Trends RSS rows have no metadata copy: for them captured_at IS the feed's pubDate,
-- so it moves across. The keyword-probe rows on the same platform are excluded -- they were
-- always stamped with the ingestion time and have no publish concept at all.
UPDATE trend_signals
SET published_at = captured_at
WHERE published_at IS NULL
  AND platform = 'google'
  AND raw_title NOT LIKE 'Google Search Trends:%';

-- What captured_at cannot be given back: for rows written before this migration by those three
-- code paths it still holds the publish time, and the true ingestion time was never recorded.
-- Those rows are left as they are rather than being stamped with an invented time. Windows over
-- them stay approximate until they age out; everything written from here is correct.
