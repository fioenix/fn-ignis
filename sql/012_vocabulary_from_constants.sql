-- 012_vocabulary_from_constants.sql: move the last hardcoded vocabulary out of src/.
--
-- Four Python constants held domain vocabulary, which AGENTS.md Section 3 (Data-Driven
-- Vocabulary Protocol) forbids: the clusterer's ambiguous unigrams, the Google Trends probe
-- templates and intent keywords, and the customer-inquiry question markers.
--
-- These four domains are system-owned: no MCP tool writes them, so the SQLite bootstrap
-- re-applies them on every start with INSERT OR IGNORE rather than seeding once. A term
-- deleted by hand therefore comes back; edit this file to change the vocabulary.

-- Generic single words that cannot identify a topic on their own. When two titles share
-- exactly one token and that token is listed here, they are not the same topic.
INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('ambiguous_unigrams', 'người', 'generic', 'system'),
('ambiguous_unigrams', 'đại', 'generic', 'system'),
('ambiguous_unigrams', 'việt', 'generic', 'system'),
('ambiguous_unigrams', 'nam', 'generic', 'system'),
('ambiguous_unigrams', 'mới', 'generic', 'system'),
('ambiguous_unigrams', 'hay', 'generic', 'system'),
('ambiguous_unigrams', 'làm', 'generic', 'system'),
('ambiguous_unigrams', 'nhất', 'generic', 'system'),
('ambiguous_unigrams', 'cực', 'generic', 'system'),
('ambiguous_unigrams', 'quá', 'generic', 'system'),
('ambiguous_unigrams', 'siêu', 'generic', 'system'),
('ambiguous_unigrams', 'top', 'generic', 'system'),
('ambiguous_unigrams', 'tin', 'generic', 'system'),
('ambiguous_unigrams', 'xem', 'generic', 'system'),
('ambiguous_unigrams', 'cho', 'generic', 'system'),
('ambiguous_unigrams', 'của', 'generic', 'system'),
('ambiguous_unigrams', 'và', 'generic', 'system'),
('ambiguous_unigrams', 'các', 'generic', 'system'),
('ambiguous_unigrams', 'những', 'generic', 'system'),
('ambiguous_unigrams', 'một', 'generic', 'system'),
('ambiguous_unigrams', 'hai', 'generic', 'system'),
('ambiguous_unigrams', 'ba', 'generic', 'system'),
('ambiguous_unigrams', 'bốn', 'generic', 'system'),
('ambiguous_unigrams', 'năm', 'generic', 'system'),
('ambiguous_unigrams', 'ngày', 'generic', 'system'),
('ambiguous_unigrams', 'đêm', 'generic', 'system'),
('ambiguous_unigrams', 'giờ', 'generic', 'system'),
('ambiguous_unigrams', 'phút', 'generic', 'system'),
('ambiguous_unigrams', 'vs', 'generic', 'system'),
('ambiguous_unigrams', 'new', 'generic', 'system'),

-- Google Suggest probe templates. '{}' is the bare keyword; the rest measure how a market
-- phrases its questions around that keyword. One domain per geo, matched by geo code.
('probe_templates_vn', '{}', 'probe_template', 'system'),
('probe_templates_vn', '{} là gì', 'probe_template', 'system'),
('probe_templates_vn', '{} việt nam', 'probe_template', 'system'),
('probe_templates_vn', 'cách dùng {}', 'probe_template', 'system'),
('probe_templates_vn', 'ứng dụng {}', 'probe_template', 'system'),
('probe_templates_default', '{}', 'probe_template', 'system'),
('probe_templates_default', 'what is {}', 'probe_template', 'system'),
('probe_templates_default', 'how to use {}', 'probe_template', 'system'),
('probe_templates_default', 'best {} tools', 'probe_template', 'system'),
('probe_templates_default', '{} tutorial', 'probe_template', 'system'),

-- Commercial and practical intent markers. A suggested query carrying one of these is
-- somebody trying to buy, learn or install, not somebody browsing.
('search_intent', 'giá', 'intent', 'system'),
('search_intent', 'cách', 'intent', 'system'),
('search_intent', 'hướng dẫn', 'intent', 'system'),
('search_intent', 'doanh nghiệp', 'intent', 'system'),
('search_intent', 'tự động', 'intent', 'system'),
('search_intent', 'tool', 'intent', 'system'),
('search_intent', 'khóa học', 'intent', 'system'),
('search_intent', 'workflow', 'intent', 'system'),
('search_intent', 'cài đặt', 'intent', 'system'),
('search_intent', 'price', 'intent', 'system'),
('search_intent', 'how', 'intent', 'system'),
('search_intent', 'guide', 'intent', 'system'),
('search_intent', 'tutorial', 'intent', 'system'),
('search_intent', 'best', 'intent', 'system'),
('search_intent', 'tools', 'intent', 'system'),
('search_intent', 'enterprise', 'intent', 'system'),
('search_intent', 'api', 'intent', 'system'),
('search_intent', 'setup', 'intent', 'system'),
('search_intent', 'download', 'intent', 'system'),
('search_intent', 'free', 'intent', 'system'),

-- A comment carrying one of these is a customer asking something, which is what the Voice of
-- Customer pass collects. '?' is punctuation and language-neutral, so it lives here too rather
-- than being special-cased in code. Two call sites had their own copy of this list, one a
-- subset of the other; this is the union, and both read it from here now.
('customer_inquiry', '?', 'question', 'system'),
('customer_inquiry', 'how', 'question', 'system'),
('customer_inquiry', 'what', 'question', 'system'),
('customer_inquiry', 'why', 'question', 'system'),
('customer_inquiry', 'price', 'question', 'system'),
('customer_inquiry', 'cost', 'question', 'system'),
('customer_inquiry', 'where', 'question', 'system'),
('customer_inquiry', 'help', 'question', 'system'),
('customer_inquiry', 'issue', 'question', 'system'),
('customer_inquiry', 'bug', 'question', 'system'),
('customer_inquiry', 'fail', 'question', 'system'),
('customer_inquiry', 'problem', 'question', 'system'),
('customer_inquiry', 'review', 'question', 'system'),
('customer_inquiry', 'làm sao', 'question', 'system'),
('customer_inquiry', 'như thế nào', 'question', 'system'),
('customer_inquiry', 'giá', 'question', 'system'),
('customer_inquiry', 'bao nhiêu', 'question', 'system'),
('customer_inquiry', 'xin', 'question', 'system'),
('customer_inquiry', 'hướng dẫn', 'question', 'system'),
('customer_inquiry', 'ở đâu', 'question', 'system'),
('customer_inquiry', 'mua', 'question', 'system'),
('customer_inquiry', 'dùng được', 'question', 'system'),
('customer_inquiry', 'test', 'question', 'system'),
('customer_inquiry', 'lỗi', 'question', 'system')
ON CONFLICT (domain, term) DO NOTHING;
