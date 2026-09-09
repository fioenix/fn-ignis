"""Mechanical gate for the two conventions in AGENTS.md Section 3.

A written rule that nothing checks is a suggestion. These tests fail the moment a new
non-English string or a new hardcoded vocabulary constant enters the codebase, while the
pre-existing debt stays visible in the allowlists below instead of being silently accepted.
"""

import ast
import re
import unicodedata
from pathlib import Path


SRC = Path(__file__).resolve().parents[2] / "src"
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
