-- Table: market_lexicons (Dynamic Domain Vocabulary & Vernacular)
CREATE TABLE IF NOT EXISTS market_lexicons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain VARCHAR(64) NOT NULL,
    term VARCHAR(128) NOT NULL,
    category VARCHAR(64) DEFAULT 'vernacular',
    created_by VARCHAR(64) DEFAULT 'system',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_domain_term UNIQUE (domain, term)
);

CREATE INDEX IF NOT EXISTS idx_market_lexicons_domain ON market_lexicons(domain);
CREATE INDEX IF NOT EXISTS idx_market_lexicons_term ON market_lexicons(term);

-- Table: industry_taxonomies (Dynamic Category Mappings)
CREATE TABLE IF NOT EXISTS industry_taxonomies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    industry_code VARCHAR(64) NOT NULL UNIQUE,
    industry_name VARCHAR(128) NOT NULL,
    keywords TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed Initial Core Lexicons
INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('common_vi', 'huong dan', 'intent', 'system'),
('common_vi', 'cach lam', 'intent', 'system'),
('common_vi', 'kinh nghiem', 'intent', 'system'),
('common_vi', 'danh gia', 'intent', 'system'),
('common_vi', 'review', 'intent', 'system'),
('common_vi', 'chi phi', 'commercial', 'system'),
('common_vi', 'gia bao nhieu', 'commercial', 'system'),
('common_vi', 'xin gia', 'commercial', 'system'),
('common_vi', 'mua o dau', 'commercial', 'system'),
-- Tech, SaaS & Automation Vertical
('tech', 'ai agent', 'topic', 'system'),
('tech', 'chatbot', 'topic', 'system'),
('tech', 'ai agent cskh', 'topic', 'system'),
('tech', 'chatbot chot don', 'topic', 'system'),
('tech', 'zalo', 'platform', 'system'),
('tech', 'token', 'technical', 'system'),
('tech', 'n8n', 'tool', 'system'),
('tech', 'dify', 'tool', 'system'),
('tech', 'make', 'tool', 'system'),
('tech', 'make.com', 'tool', 'system'),
('tech', 'zapier', 'tool', 'system'),
('tech', 'flowise', 'tool', 'system'),
('tech', 'langchain', 'tool', 'system'),
('tech', 'rpa', 'tool', 'system'),
('tech', 'tu dong hoa', 'technical', 'system'),
('tech', 'webhook', 'technical', 'system'),
('tech', 'crm automation', 'technical', 'system'),
('tech', 'quet lead', 'intent', 'system'),
('tech', 'auto inbox', 'intent', 'system'),
('tech', 'auto comment', 'intent', 'system'),
('tech', 'bot ban hang', 'intent', 'system'),
('tech', 'ban hang tu dong', 'intent', 'system'),
('tech', 'cskh', 'domain', 'system'),
('tech', 'phan mem', 'domain', 'system'),
-- E-Commerce & TikTok Shop Vertical
('ecommerce', 'tiktok shop', 'platform', 'system'),
('ecommerce', 'shopee', 'platform', 'system'),
('ecommerce', 'lazada', 'platform', 'system'),
('ecommerce', 'chot don', 'vernacular', 'system'),
('ecommerce', 'kho hang', 'vernacular', 'system'),
('ecommerce', 'van don', 'vernacular', 'system'),
('ecommerce', 'livestream', 'vernacular', 'system'),
('ecommerce', 'affiliate', 'vernacular', 'system'),
('ecommerce', 'gio hang', 'vernacular', 'system'),
('ecommerce', 'gan gio hang', 'vernacular', 'system'),
('ecommerce', 'seeding', 'vernacular', 'system'),
('ecommerce', 'nguon si', 'vernacular', 'system'),
('ecommerce', 'kho si', 'vernacular', 'system'),
('ecommerce', 'dropshipping', 'vernacular', 'system'),
('ecommerce', 'flash sale', 'vernacular', 'system'),
('ecommerce', 'voucher', 'vernacular', 'system'),
('ecommerce', 'ads tiktok', 'vernacular', 'system'),
('ecommerce', 'keo tuong tac', 'vernacular', 'system'),
('ecommerce', 'hoa toc', 'vernacular', 'system'),
('ecommerce', 'hoan don', 'vernacular', 'system'),
('ecommerce', 'bom hang', 'vernacular', 'system'),
-- Fashion & Apparel Vertical
('fashion', 'local brand', 'vernacular', 'system'),
('fashion', 'linen', 'material', 'system'),
('fashion', 'ao linen', 'product', 'system'),
('fashion', 'dam thiet ke', 'product', 'system'),
('fashion', 'thoi trang cong so', 'product', 'system'),
('fashion', 'xuong may', 'supply_chain', 'system'),
('fashion', 'order taobao', 'supply_chain', 'system'),
('fashion', 'si quan ao', 'supply_chain', 'system'),
('fashion', 'set do', 'style', 'system'),
('fashion', 'vai linen', 'material', 'system'),
('fashion', 'phong cach toi gian', 'style', 'system'),
('fashion', 'oversize', 'style', 'system'),
('fashion', 'outfit', 'style', 'system'),
('fashion', 'chan vay', 'product', 'system'),
('fashion', 'blazer', 'product', 'system'),

-- Foreign Stopwords (Dynamic Language Filter Seeds)
('foreign_stopwords', 'como', 'stopwords_pt', 'system'),
('foreign_stopwords', 'funcionam', 'stopwords_pt', 'system'),
('foreign_stopwords', 'chegou', 'stopwords_pt', 'system'),
('foreign_stopwords', 'novos', 'stopwords_pt', 'system'),
('foreign_stopwords', 'veja', 'stopwords_pt', 'system'),
('foreign_stopwords', 'agentes', 'stopwords_pt', 'system'),
('foreign_stopwords', 'autonomos', 'stopwords_pt', 'system'),
('foreign_stopwords', 'autônomos', 'stopwords_pt', 'system'),
('foreign_stopwords', 'você', 'stopwords_pt', 'system'),
('foreign_stopwords', 'voce', 'stopwords_pt', 'system'),
('foreign_stopwords', 'fazer', 'stopwords_pt', 'system'),
('foreign_stopwords', 'curso', 'stopwords_pt', 'system'),
('foreign_stopwords', 'formation', 'stopwords_fr', 'system'),
('foreign_stopwords', 'complète', 'stopwords_fr', 'system'),
('foreign_stopwords', 'debutant', 'stopwords_fr', 'system'),
('foreign_stopwords', 'débutant', 'stopwords_fr', 'system'),
('foreign_stopwords', 'cara', 'stopwords_id', 'system'),
('foreign_stopwords', 'yang', 'stopwords_id', 'system'),
('foreign_stopwords', 'untuk', 'stopwords_id', 'system')
ON CONFLICT (domain, term) DO NOTHING;

INSERT INTO industry_taxonomies (industry_code, industry_name, keywords) VALUES
('tech', 'Tech & Electronics', ARRAY['ai', 'software', 'agent', 'bot', 'app', 'tool', 'hardware', 'laptop', 'phone']),
('ecommerce', 'E-Commerce & Retail', ARRAY['shop', 'shopee', 'lazada', 'order', 'shipping', 'don hang', 'chot don']),
('fashion', 'Apparel & Accessories', ARRAY['fashion', 'clothing', 'linen', 'dress', 'shirt', 'outfit', 'style', 'local brand']),
('education', 'Education & Training', ARRAY['course', 'khoa hoc', 'hoc', 'tutorial', 'dao tao', 'huong dan']),
('beauty', 'Beauty & Personal Care', ARRAY['skincare', 'makeup', 'my pham', 'son', 'kem', 'duong da', 'serum']),
('finance', 'Financial Services', ARRAY['finance', 'tai chinh', 'dau tu', 'ngan hang', 'bank', 'chung khoan', 'crypto'])
ON CONFLICT (industry_code) DO NOTHING;
