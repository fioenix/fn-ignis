-- 014_language_detection_vocabulary.sql: the language detector's phrase lists, out of code.
--
-- HeuristicLanguageDetector held two sets of vocabulary: cross-language phrases that disqualify
-- a title from belonging to any single locale, and Portuguese words distinctive enough that two
-- of them outrank an otherwise English-looking title. Both are vocabulary of specific languages,
-- so extending detection to a new one was a release. The character classes stay in code because
-- there the characters are the algorithm.
--
-- Both drive rejection rules, so missing rows make detection more permissive, not less. The
-- detector logs once when either list is empty.
--
-- System-owned like the 012 and 013 domains: re-applied on every SQLite bootstrap.

-- French, Portuguese and Indonesian phrases. Any one of them present rules the title out.
INSERT INTO market_lexicons (domain, term, category, created_by) VALUES
('foreign_phrases', 'formation complete', 'french', 'system'),
('foreign_phrases', 'formation complète', 'french', 'system'),
('foreign_phrases', 'avec', 'french', 'system'),
('foreign_phrases', 'cours pour', 'french', 'system'),
('foreign_phrases', 'dans le', 'french', 'system'),
('foreign_phrases', 'tuto debutant', 'french', 'system'),
('foreign_phrases', 'tuto débutant', 'french', 'system'),
('foreign_phrases', 'como criar', 'portuguese', 'system'),
('foreign_phrases', 'como funcionam', 'portuguese', 'system'),
('foreign_phrases', 'agentes autonomos', 'portuguese', 'system'),
('foreign_phrases', 'agentes autônomos', 'portuguese', 'system'),
('foreign_phrases', 'para você', 'portuguese', 'system'),
('foreign_phrases', 'para voce', 'portuguese', 'system'),
('foreign_phrases', 'inteligencia artificial', 'portuguese', 'system'),
('foreign_phrases', 'inteligência artificial', 'portuguese', 'system'),
('foreign_phrases', 'todos os', 'portuguese', 'system'),
('foreign_phrases', 'fazer curso', 'portuguese', 'system'),
('foreign_phrases', 'de ia', 'portuguese', 'system'),
('foreign_phrases', 'com ia', 'portuguese', 'system'),
('foreign_phrases', 'para empresas', 'portuguese', 'system'),
('foreign_phrases', 'cara membuat', 'indonesian', 'system'),
('foreign_phrases', 'untuk pemula', 'indonesian', 'system'),

-- Two of these in one title outrank an English reading of it.
('portuguese_words', 'como', 'distinctive', 'system'),
('portuguese_words', 'para', 'distinctive', 'system'),
('portuguese_words', 'com', 'distinctive', 'system'),
('portuguese_words', 'por', 'distinctive', 'system'),
('portuguese_words', 'sobre', 'distinctive', 'system'),
('portuguese_words', 'este', 'distinctive', 'system'),
('portuguese_words', 'esta', 'distinctive', 'system'),
('portuguese_words', 'todos', 'distinctive', 'system'),
('portuguese_words', 'agora', 'distinctive', 'system'),
('portuguese_words', 'fazer', 'distinctive', 'system'),
('portuguese_words', 'curso', 'distinctive', 'system'),
('portuguese_words', 'gratis', 'distinctive', 'system'),
('portuguese_words', 'completo', 'distinctive', 'system'),
('portuguese_words', 'você', 'distinctive', 'system'),
('portuguese_words', 'voce', 'distinctive', 'system'),
('portuguese_words', 'seus', 'distinctive', 'system'),
('portuguese_words', 'suas', 'distinctive', 'system'),
('portuguese_words', 'criar', 'distinctive', 'system'),
('portuguese_words', 'criando', 'distinctive', 'system'),
('portuguese_words', 'ferramenta', 'distinctive', 'system'),
('portuguese_words', 'passo', 'distinctive', 'system'),
('portuguese_words', 'inteligencia', 'distinctive', 'system'),
('portuguese_words', 'artificial', 'distinctive', 'system'),
('portuguese_words', 'inteligência', 'distinctive', 'system'),
('portuguese_words', 'automatizar', 'distinctive', 'system'),
('portuguese_words', 'não', 'distinctive', 'system'),
('portuguese_words', 'nao', 'distinctive', 'system'),
('portuguese_words', 'em', 'distinctive', 'system'),
('portuguese_words', 'do', 'distinctive', 'system'),
('portuguese_words', 'da', 'distinctive', 'system'),
('portuguese_words', 'que', 'distinctive', 'system'),
('portuguese_words', 'uma', 'distinctive', 'system'),
('portuguese_words', 'um', 'distinctive', 'system'),
('portuguese_words', 'automação', 'distinctive', 'system'),
('portuguese_words', 'automacao', 'distinctive', 'system'),
('portuguese_words', 'negócios', 'distinctive', 'system'),
('portuguese_words', 'negocios', 'distinctive', 'system'),
('portuguese_words', 'agentes', 'distinctive', 'system')
ON CONFLICT (domain, term) DO NOTHING;
