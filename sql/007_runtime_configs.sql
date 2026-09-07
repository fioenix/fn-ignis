-- 007_runtime_configs.sql: Initial Dynamic Runtime Configurations
CREATE TABLE IF NOT EXISTS runtime_configs (
    key VARCHAR(128) PRIMARY KEY,
    value TEXT NOT NULL,
    category VARCHAR(64) DEFAULT 'connector',
    description TEXT,
    updated_by VARCHAR(64) DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO runtime_configs (key, value, category, description, updated_by) VALUES
('self_accounts', '{}', 'ingress', 'Accounts owned by the operator, as {"platform": ["handle_or_id"]}. Market passes exclude their content; discovered automatically from session cookies when possible, set here when no API reports the handle.', 'system'),
('threads_web_client_id', '238260118693652', 'threads', 'Meta internal web client ID for Threads web requests (X-IG-App-ID)', 'system'),
('threads_graphql_endpoint', 'https://www.threads.net/api/graphql', 'threads', 'Meta Threads Web GraphQL endpoint', 'system'),
('threads_doc_id_trending_topics', '', 'threads', 'Persisted GraphQL doc_id for Threads Trending Topics query', 'system'),
('threads_doc_id_search_posts', '', 'threads', 'Persisted GraphQL doc_id for Threads Keyword Search query', 'system'),
('threads_doc_id_search_suggestions', '', 'threads', 'Persisted GraphQL doc_id for Threads Search Suggestions query', 'system')
ON CONFLICT (key) DO NOTHING;
