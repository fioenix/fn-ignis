-- 004_global_lexicons.sql: Canonical Global Market Lexicon Seeds for English & International Research

INSERT INTO market_lexicons (domain, term, category) VALUES
-- 1. Global AI, SaaS & Developer Automation
('global_saas_ai', 'mcp server', 'technical_infrastructure'),
('global_saas_ai', 'agentic workflow', 'core_architecture'),
('global_saas_ai', 'ai agent', 'core_architecture'),
('global_saas_ai', 'ai automation agency', 'business_model'),
('global_saas_ai', 'prompt engineering', 'skill_tooling'),
('global_saas_ai', 'langchain', 'framework_ecosystem'),
('global_saas_ai', 'crewai', 'framework_ecosystem'),
('global_saas_ai', 'dify', 'platform_tooling'),
('global_saas_ai', 'n8n workflow', 'workflow_automation'),
('global_saas_ai', 'rag pipeline', 'technical_architecture'),
('global_saas_ai', 'vector database', 'technical_infrastructure'),
('global_saas_ai', 'fine tuning', 'model_optimization'),
('global_saas_ai', 'vibe coding', 'development_trend'),
('global_saas_ai', 'synthetic data', 'data_engineering'),
('global_saas_ai', 'autonomous agent', 'core_architecture'),

-- 2. Global E-Commerce, DTC & TikTok Shop
('global_ecommerce', 'tiktok shop us', 'platform_ecosystem'),
('global_ecommerce', 'winning product', 'product_research'),
('global_ecommerce', 'ugc creator', 'marketing_strategy'),
('global_ecommerce', 'dropshipping', 'business_model'),
('global_ecommerce', 'tiktok ads roas', 'performance_marketing'),
('global_ecommerce', 'affiliate commission', 'creator_economy'),
('global_ecommerce', 'fulfillment by amazon', 'logistics_supply'),
('global_ecommerce', 'print on demand', 'business_model'),
('global_ecommerce', 'tiktok creator rewards', 'monetization'),
('global_ecommerce', 'organic reach', 'growth_marketing'),
('global_ecommerce', 'hooks and call to action', 'creative_strategy'),

-- 3. Global Fashion, Aesthetics & Apparel
('global_fashion', 'quiet luxury', 'aesthetic_trend'),
('global_fashion', 'old money style', 'aesthetic_trend'),
('global_fashion', 'capsule wardrobe', 'lifestyle_trend'),
('global_fashion', 'slow fashion', 'sustainability'),
('global_fashion', 'gorpcore', 'style_category'),
('global_fashion', 'y2k aesthetic', 'style_category'),
('global_fashion', 'oversized linen shirt', 'product_niche'),
('global_fashion', 'minimalist aesthetic', 'style_category'),
('global_fashion', 'streetwear drop', 'marketing_trend'),

-- 4. Generic Social Noise & Non-Strategic Content Blacklist
('noise_blacklist', 'fyp', 'generic_social_noise'),
('noise_blacklist', 'xuhuong', 'generic_social_noise'),
('noise_blacklist', 'trending', 'generic_social_noise'),
('noise_blacklist', 'viral', 'generic_social_noise'),
('noise_blacklist', 'haihuoc', 'entertainment_noise'),
('noise_blacklist', 'funny', 'entertainment_noise'),
('noise_blacklist', 'dance', 'entertainment_noise'),
('noise_blacklist', 'nhactre', 'entertainment_noise'),
('noise_blacklist', 'giaitri', 'entertainment_noise'),
('noise_blacklist', 'thethao', 'entertainment_noise'),
('noise_blacklist', 'bongda', 'entertainment_noise'),
('noise_blacklist', 'troll', 'entertainment_noise'),
('noise_blacklist', 'vlog', 'entertainment_noise'),
('noise_blacklist', 'duet', 'entertainment_noise'),
('noise_blacklist', 'chuyenhai', 'entertainment_noise'),
('noise_blacklist', 'music', 'entertainment_noise'),
('noise_blacklist', 'capcut', 'entertainment_noise'),
('noise_blacklist', 'giadinh', 'entertainment_noise'),
('noise_blacklist', 'namthankinh', 'entertainment_noise'),
('noise_blacklist', 'vietnamvodich', 'entertainment_noise'),
('noise_blacklist', 'golivegrowfast', 'entertainment_noise'),
('noise_blacklist', 'tiktokshop99', 'entertainment_noise')
ON CONFLICT (domain, term) DO NOTHING;

