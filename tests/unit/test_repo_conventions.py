"""Mechanical gate for the two conventions in AGENTS.md Section 3, and for two workspace rules.

A written rule that nothing checks is a suggestion. These tests fail the moment a new
non-English string or a new hardcoded vocabulary constant enters the codebase, while the
pre-existing debt stays visible in the allowlists below instead of being silently accepted.

The same argument covers two rules of the research workspace that are otherwise only stated in
prose: one configured database is canonical for every research, and there is no store for an
unconfirmed framing. Both are guarantees about what the codebase is unable to do, so a static
scan is the form of them a later caller cannot work around at runtime.
"""

import ast
import re
import unicodedata
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SQL = REPO / "sql"
TESTS = Path(__file__).resolve().parents[1]

def _non_ascii_letters(text: str) -> str:
    """Non-ASCII *letters* only: typographic punctuation, currency and emoji are language-neutral."""
    return "".join(ch for ch in text if ord(ch) > 127 and unicodedata.category(ch).startswith("L"))

# Files allowed to carry non-ASCII letters in src/, with the reason each one is legitimate.
# Anything not listed here must be English. Do not extend this list to silence a new violation.
SRC_NON_ASCII_ALLOWLIST = {
    # Character classes are the language-detection algorithm itself.
    "ignis/infrastructure/harness/language_detector.py",
    # Transliterating d-with-stroke is a step of the diacritic folding algorithm, not vocabulary.
    "ignis/infrastructure/clustering/semantic_clusterer.py",
    # Third-party UI selectors that must match TikTok's rendered text verbatim.
    "ignis/infrastructure/auth/tiktok_auth.py",
    "ignis/infrastructure/connectors/tiktok/creative_center_plugin.py",
    "ignis/infrastructure/connectors/meta_browser_ingress.py",
}

# Vocabulary constants that predate the Data-Driven Vocabulary Protocol.
KNOWN_VOCABULARY_CONSTANTS = {
    ("ignis/infrastructure/connectors/reels/reels_plugin.py", "BROWSER_API_MARKERS"),
    ("ignis/infrastructure/harness/strategic_reasoner.py", "RATE_LIMIT_HINTS"),
    ("ignis/infrastructure/harness/strategic_reasoner.py", "AUTH_SENSITIVE_PLATFORMS"),
    ("ignis/infrastructure/harness/strategic_reasoner.py", "VIDEO_PLATFORMS"),
    # Vietnamese written without tones, used to read titles that are themselves untoned, and the
    # loanwords subtracted before that count. Real vocabulary and real debt; listed rather than
    # invisible, which is what "WORDS" in the hint below now guarantees.
    ("ignis/infrastructure/harness/language_detector.py", "VI_CORE_WORDS"),
    ("ignis/infrastructure/harness/language_detector.py", "TECH_LOAN_WORDS"),
}

# BLACKLIST and WORDS were both missing until 09/09/2026. That is how NOTIFICATION_BLACKLIST and
# VI_CORE_WORDS stayed invisible here, while the allowlist carried entries for two constants that
# never existed under those names: NOTIFICATION_NOISE_PATTERNS and PORTUGUESE_MARKERS. A name in
# the allowlist that matches nothing in src/ is worse than no entry, because it reads as covered.
VOCABULARY_NAME_HINT = re.compile(
    r"(SYNONYM|LEXICON|KEYWORD|VOCAB|TERMS|PHRASES|STOPWORD|NOISE|UNIGRAM|MARKERS|PROBES"
    r"|TAXONOM|BLACKLIST|WHITELIST|ALLOWLIST|TRIGGERS|WORDS)"
)


def _relative_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_source_files_are_english_outside_the_allowlist():
    offenders = []
    for path in _relative_python_files(SRC):
        rel = path.relative_to(SRC).as_posix()
        if rel in SRC_NON_ASCII_ALLOWLIST:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _non_ascii_letters(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:90]}")
    assert not offenders, (
        "Non-English text in src/. Emitted strings, log lines and comments are English "
        "(AGENTS.md Section 3):\n" + "\n".join(offenders)
    )


def _is_vietnamese(text: str) -> bool:
    """True when the text carries Vietnamese-specific diacritics."""
    decomposed = unicodedata.normalize("NFD", text)
    return "đ" in text.lower() or any(unicodedata.combining(ch) for ch in decomposed)


def test_test_prose_is_english_even_when_fixtures_are_vietnamese():
    """Docstrings, comments and assert messages are developer output; fixture data is not."""
    offenders = []
    for path in _relative_python_files(TESTS):
        rel = path.relative_to(TESTS).as_posix()
        source = path.read_text(encoding="utf-8")

        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") and _is_vietnamese(stripped):
                offenders.append(f"{rel}:{lineno}: comment")

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                if doc and _is_vietnamese(doc):
                    offenders.append(f"{rel}:{node.lineno}: docstring")
            if isinstance(node, ast.Assert) and node.msg is not None:
                message = " ".join(
                    part.value for part in ast.walk(node.msg) if isinstance(part, ast.Constant) and isinstance(part.value, str)
                )
                if _is_vietnamese(message):
                    offenders.append(f"{rel}:{node.lineno}: assert message")

    assert not offenders, (
        "Vietnamese prose in tests/. Fixture data may be Vietnamese, prose may not "
        "(AGENTS.md Section 3):\n" + "\n".join(sorted(offenders))
    )


def test_no_new_hardcoded_domain_vocabulary_in_src():
    """A module-level collection of domain terms belongs in market_lexicons, not in Python."""
    offenders = []
    for path in _relative_python_files(SRC):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]

            for name in targets:
                if not name.isupper() or not VOCABULARY_NAME_HINT.search(name):
                    continue
                if (rel, name) in KNOWN_VOCABULARY_CONSTANTS:
                    continue
                value = node.value
                if isinstance(value, (ast.List, ast.Set, ast.Tuple)) and len(value.elts) >= 4:
                    offenders.append(f"{rel}:{node.lineno}: {name}")
                elif isinstance(value, ast.Dict) and len(value.keys) >= 2:
                    offenders.append(f"{rel}:{node.lineno}: {name}")

    assert not offenders, (
        "Hardcoded domain vocabulary in src/. Seed it in sql/ and read it from the database "
        "(AGENTS.md Section 3):\n" + "\n".join(offenders)
    )


def test_vocabulary_debt_allowlists_stay_accurate():
    """The allowlists are debt registers: an entry that no longer exists must be removed."""
    stale = [rel for rel in SRC_NON_ASCII_ALLOWLIST if not (SRC / rel).exists()]
    stale += [f"{rel}:{name}" for rel, name in KNOWN_VOCABULARY_CONSTANTS if not (SRC / rel).exists()]
    assert not stale, f"Allowlist entries pointing at missing files: {stale}"


# ---------------------------------------------------------------------------
# Research workspace: one shared database, and no store for an unconfirmed framing
# ---------------------------------------------------------------------------

# Anything that names part of the `.ignis/research/<slug>/` layout knows where a research folder
# is, and is therefore the only place a per-research database could be opened from.
RESEARCH_LAYOUT_MARKERS = (
    "RESEARCH_ROOT_SEGMENTS",
    "research_root",
    "MANIFEST_FILENAME",
    "JOURNAL_DIRNAME",
)

# Calls that build or open a database. Called with no argument they mean "the one configured
# installation database", which is the contract. Called with an argument they mean a database of
# somebody's choosing, which beside a research folder means a per-research database.
DATABASE_CONSTRUCTORS = {
    "create_repository",
    "SqliteTrendRepository",
    "PostgresTrendRepository",
    "connect",
    "create_engine",
}

DATABASE_FILE_SUFFIXES = (".db", ".sqlite", ".sqlite3")


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def test_the_configured_database_is_never_rebuilt_beside_a_research_folder():
    """A research keeps its manifest and its journals on disk; its records stay in one database.

    The workspace folder is workspace-local storage, not a second record store. A module that
    knows where that folder is may still use the configured installation database, so the gate
    is on the argument: an unqualified `create_repository()` is the shared database, and a
    database opened at a path this module could compute is a per-research one.
    """
    offenders = []
    for path in _relative_python_files(SRC):
        rel = path.relative_to(SRC).as_posix()
        source = path.read_text(encoding="utf-8")
        if not any(marker in source for marker in RESEARCH_LAYOUT_MARKERS):
            continue

        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and _call_name(node) in DATABASE_CONSTRUCTORS:
                if node.args or node.keywords:
                    offenders.append(f"{rel}:{node.lineno}: {_call_name(node)}(...) takes a target")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.strip().lower().endswith(DATABASE_FILE_SUFFIXES):
                    offenders.append(f"{rel}:{node.lineno}: database filename {node.value!r}")

    assert not offenders, (
        "A module that knows the research folder layout opens a database of its own. One "
        "configured database is canonical for every research:\n" + "\n".join(offenders)
    )


# The Q&A that produces a Market Brief belongs to the host Agent. fn-ignis receives the confirmed
# Brief and nothing before it, so an abandoned framing has nowhere to be written down.
UNCONFIRMED_FRAMING_WORDS = (
    "transcript",
    "draft",
    "conversation",
    "chat_turn",
    "question_answer",
)

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(.*?)\n\s*\);", re.IGNORECASE | re.DOTALL
)


def _strip_sql_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def test_the_schema_holds_no_table_for_an_unconfirmed_framing():
    """No table or column exists for a Q&A transcript or a Brief draft, so none can be filled."""
    definitions = []
    for path in sorted(SQL.glob("*.sql")):
        body = _strip_sql_comments(path.read_text(encoding="utf-8"))
        for block in _CREATE_TABLE.findall(body):
            definitions.append((path.name, block))
    assert definitions, "No CREATE TABLE statement was found in sql/; the scan below proves nothing."

    offenders = [
        f"{name}: {word}"
        for name, block in definitions
        for word in UNCONFIRMED_FRAMING_WORDS
        if word in block.lower()
    ]
    assert not offenders, (
        "The schema names storage for an unconfirmed framing. The host Agent owns the Q&A and "
        "sends only the confirmed Brief:\n" + "\n".join(offenders)
    )


# Columns that would store what a model was told or thought. The qualification record keeps a
# bounded reason code and an evaluator identifier; nothing that could hold a prompt, a transcript
# or chain-of-thought.
MODEL_TRANSCRIPT_WORDS = (
    "prompt",
    "transcript",
    "reasoning",
    "chain_of_thought",
    "thought",
    "completion",
    "raw_response",
    "rationale",
)
QUALIFICATION_TABLES = ("mission_probe_outcomes", "mission_evidence_qualifications")


def _qualification_table_definitions() -> list:
    definitions = []
    migration = _strip_sql_comments((SQL / "023_evidence_qualification.sql").read_text(encoding="utf-8"))
    sqlite_source = (SRC / "ignis/infrastructure/persistence/sqlite_repository.py").read_text(
        encoding="utf-8"
    )
    restated = _strip_sql_comments(sqlite_source)
    for origin, body in (("sql/023", migration), ("sqlite restatement", restated)):
        for block in _CREATE_TABLE.findall(body):
            if block.split("(", 1)[0].strip() in QUALIFICATION_TABLES:
                definitions.append((origin, block))
    return definitions


def test_no_qualification_table_can_store_a_prompt_transcript_or_model_reasoning():
    definitions = _qualification_table_definitions()
    names = sorted({(origin, block.split("(", 1)[0].strip()) for origin, block in definitions})
    assert names == sorted(
        (origin, table) for origin in ("sql/023", "sqlite restatement") for table in QUALIFICATION_TABLES
    ), f"both backends must declare both tables; found {names}"

    offenders = [
        f"{origin}: {word}"
        for origin, block in definitions
        for word in MODEL_TRANSCRIPT_WORDS
        if re.search(rf"\b{word}\w*\s+(TEXT|VARCHAR|JSONB?|DOUBLE)", block, re.IGNORECASE)
    ]
    assert not offenders, (
        "A qualification table names storage for model input or reasoning. Judgments are bounded "
        "enums plus an evaluator identifier:\n" + "\n".join(offenders)
    )


def test_the_decision_grade_modules_hold_no_domain_vocabulary():
    """Relevance is judged by the host Agent, never by a keyword list shipped in the policy code."""
    modules = (
        "ignis/application/use_cases/get_evidence_qualification_batch.py",
        "ignis/application/use_cases/submit_evidence_qualifications.py",
        "ignis/domain/research_workspace.py",
        "ignis/infrastructure/config/vocabulary_loader.py",
    )
    offenders = []
    for rel in modules:
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "frozenset":
                value = value.args[0] if value.args else value
            if isinstance(value, (ast.List, ast.Set, ast.Tuple)):
                strings = [
                    e.value for e in value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                if any(_non_ascii_letters(s) or " " in s.strip() for s in strings):
                    offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, "Natural-language terms in qualification code:\n" + "\n".join(offenders)
