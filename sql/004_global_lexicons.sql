-- 004_global_lexicons.sql: Social-noise blacklist; market-domain vocabulary is retired in 040.

INSERT INTO market_lexicons (domain, term, category) VALUES
('noise_blacklist', 'fyp', 'generic_social_noise'),
('noise_blacklist', 'foryou', 'generic_social_noise'),
('noise_blacklist', 'foryoupage', 'generic_social_noise'),
('noise_blacklist', 'xuhuong', 'generic_social_noise'),
('noise_blacklist', 'haihuoc', 'entertainment_noise'),
('noise_blacklist', 'funny', 'entertainment_noise'),
('noise_blacklist', 'troll', 'entertainment_noise'),
('noise_blacklist', 'nhactre', 'entertainment_noise'),
('noise_blacklist', 'vlog', 'entertainment_noise'),
('noise_blacklist', 'chuyenma', 'entertainment_noise'),
('noise_blacklist', 'kinhdi', 'entertainment_noise'),
('noise_blacklist', 'phimngan', 'entertainment_noise'),
('noise_blacklist', 'reviewphim', 'entertainment_noise'),
('noise_blacklist', 'ngontinh', 'entertainment_noise'),
('noise_blacklist', 'namthankinh', 'entertainment_noise'),
('noise_blacklist', 'vietnamvodich', 'entertainment_noise'),
('noise_blacklist', 'golivegrowfast', 'entertainment_noise'),
('noise_blacklist', 'duet', 'entertainment_noise'),
('noise_blacklist', 'chuyenhai', 'entertainment_noise')
ON CONFLICT (domain, term) DO NOTHING;


