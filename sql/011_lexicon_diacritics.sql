-- 011: Restore Vietnamese tone marks on the seeded market_lexicons terms.
--
-- These terms are handed to connectors as search queries, so a tone-stripped term asks the
-- platform a different question than the one a Vietnamese user would type: "gia bao nhieu" is
-- not what anyone searches, "gia bao nhieu" and "gia bao nhieu" are not even the same words.
-- Canonicalising by discarding tones loses the language, and social listening is about hearing
-- the language as it was written.
--
-- Only Vietnamese terms change. English terms, brand names, hashtag noise markers and the
-- foreign stopword list carry no tones by nature and are left untouched. Terms registered at
-- runtime through register_domain_lexicon already arrive with their tones.

UPDATE market_lexicons SET term = 'hướng dẫn' WHERE term = 'huong dan';
UPDATE market_lexicons SET term = 'cách làm' WHERE term = 'cach lam';
UPDATE market_lexicons SET term = 'kinh nghiệm' WHERE term = 'kinh nghiem';
UPDATE market_lexicons SET term = 'đánh giá' WHERE term = 'danh gia';
UPDATE market_lexicons SET term = 'chi phí' WHERE term = 'chi phi';
UPDATE market_lexicons SET term = 'giá bao nhiêu' WHERE term = 'gia bao nhieu';
UPDATE market_lexicons SET term = 'xin giá' WHERE term = 'xin gia';
UPDATE market_lexicons SET term = 'mua ở đâu' WHERE term = 'mua o dau';
UPDATE market_lexicons SET term = 'ai agent CSKH' WHERE term = 'ai agent cskh';
UPDATE market_lexicons SET term = 'chatbot chốt đơn' WHERE term = 'chatbot chot don';
UPDATE market_lexicons SET term = 'tự động hóa' WHERE term = 'tu dong hoa';
UPDATE market_lexicons SET term = 'quét lead' WHERE term = 'quet lead';
UPDATE market_lexicons SET term = 'bot bán hàng' WHERE term = 'bot ban hang';
UPDATE market_lexicons SET term = 'bán hàng tự động' WHERE term = 'ban hang tu dong';
UPDATE market_lexicons SET term = 'phần mềm' WHERE term = 'phan mem';
UPDATE market_lexicons SET term = 'chốt đơn' WHERE term = 'chot don';
UPDATE market_lexicons SET term = 'kho hàng' WHERE term = 'kho hang';
UPDATE market_lexicons SET term = 'vận đơn' WHERE term = 'van don';
UPDATE market_lexicons SET term = 'giỏ hàng' WHERE term = 'gio hang';
UPDATE market_lexicons SET term = 'gắn giỏ hàng' WHERE term = 'gan gio hang';
UPDATE market_lexicons SET term = 'nguồn sỉ' WHERE term = 'nguon si';
UPDATE market_lexicons SET term = 'kho sỉ' WHERE term = 'kho si';
UPDATE market_lexicons SET term = 'kéo tương tác' WHERE term = 'keo tuong tac';
UPDATE market_lexicons SET term = 'hỏa tốc' WHERE term = 'hoa toc';
UPDATE market_lexicons SET term = 'hoàn đơn' WHERE term = 'hoan don';
UPDATE market_lexicons SET term = 'bom hàng' WHERE term = 'bom hang';
UPDATE market_lexicons SET term = 'áo linen' WHERE term = 'ao linen';
UPDATE market_lexicons SET term = 'đầm thiết kế' WHERE term = 'dam thiet ke';
UPDATE market_lexicons SET term = 'thời trang công sở' WHERE term = 'thoi trang cong so';
UPDATE market_lexicons SET term = 'xưởng may' WHERE term = 'xuong may';
UPDATE market_lexicons SET term = 'sỉ quần áo' WHERE term = 'si quan ao';
UPDATE market_lexicons SET term = 'set đồ' WHERE term = 'set do';
UPDATE market_lexicons SET term = 'vải linen' WHERE term = 'vai linen';
UPDATE market_lexicons SET term = 'phong cách tối giản' WHERE term = 'phong cach toi gian';
UPDATE market_lexicons SET term = 'chân váy' WHERE term = 'chan vay';
