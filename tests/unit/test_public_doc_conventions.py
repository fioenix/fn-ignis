"""Gate for what a public reader receives.

The repository is being prepared to change from private to public. Three kinds of content are
safe while only the maintainer reads them and stop being safe the moment anyone can clone:

1. A security policy that overstates the algorithm it implements, or names a version line the
   project no longer ships.
2. The internal second-person register the maintainer and the agent use with each other, left in
   a document strangers read.
3. Infrastructure identifiers that narrow a production target.

Each rule below states its own reason. These are documentation contracts, so they read files
rather than imports; a test that only checked for the presence of a heading would pass while the
sentence under it said the wrong thing.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SECURITY_POLICY = REPO / "SECURITY.md"
CODE_OF_CONDUCT = REPO / "CODE_OF_CONDUCT.md"
PYPROJECT = REPO / "pyproject.toml"

# Documents a public visitor reads. Regional (.vi) guides are included: a public reader of
# Vietnamese gets the same register problem as a public reader of English.
PUBLIC_DOCS = (
    "README.md",
    "README.vi.md",
    "BACKLOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "docs/PROJECT_REVIEW_CONTEXT.md",
    "docs/USER_GUIDE.md",
    "docs/USER_GUIDE.vi.md",
)

# The informal second-person pair the maintainer and the agent use in chat. Guarded by
# non-alphanumeric boundaries on both sides so the same untoned syllable appearing inside ordinary
# Vietnamese compounds -- "artificial", "training", "create a table" all contain it -- is not
# matched; those are legitimate vocabulary data. Python's \b is wrong next to Vietnamese letters,
# which are non-ASCII word characters here.
INTERNAL_REGISTER = re.compile(r"(?<![0-9A-Za-zÀ-ỹ])(mày|tao|Mày|Tao)(?![0-9A-Za-zÀ-ỹ])")

# A concrete connection endpoint. The pooler host is regional rather than project-specific, but
# published next to a note about which credentials exist it narrows the target for no benefit.
POOLER_HOST = re.compile(r"[A-Za-z0-9.-]*\bpooler\.supabase\.com")


def _read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def _current_minor_series() -> str:
    """`0.4.x` for a project at 0.4.0 -- the shape a supported-version table should name."""
    match = re.search(r'(?m)^version\s*=\s*"(\d+)\.(\d+)\.\d+"', PYPROJECT.read_text(encoding="utf-8"))
    assert match, "pyproject.toml has no parseable project version"
    return f"{match.group(1)}.{match.group(2)}.x"


def test_security_policy_supports_the_version_actually_shipped():
    """A policy naming an unshipped line tells a reporter their version is unsupported."""
    series = _current_minor_series()
    text = _read("SECURITY.md")
    assert series in text, (
        f"SECURITY.md does not name the current supported series {series}. "
        "The supported-version table has to move with pyproject.toml."
    )


def test_security_policy_does_not_overstate_the_cipher():
    """Claiming AES-256-GCM while shipping Fernet promises strength the code does not provide."""
    text = _read("SECURITY.md")
    assert "AES-256-GCM" not in text, (
        "SECURITY.md claims AES-256-GCM. Credential encryption is Fernet, which is "
        "AES-128-CBC with HMAC-SHA256 (src/ignis/infrastructure/auth/crypto.py)."
    )


def test_security_policy_describes_the_cipher_it_ships():
    """Removing the wrong claim is not enough; the right one has to be stated."""
    text = _read("SECURITY.md")
    for token in ("Fernet", "AES-128-CBC", "HMAC-SHA256"):
        assert token in text, (
            f"SECURITY.md does not mention {token}. The policy must describe the encryption "
            "actually implemented, not omit it."
        )


def test_security_policy_states_both_placeholder_styles():
    """PostgreSQL uses %s and SQLite uses ?; naming only one implies the other is unprotected."""
    text = _read("SECURITY.md")
    assert "%s" in text and "?" in text, (
        "SECURITY.md must name the parameter placeholder for both backends: %s for PostgreSQL "
        "and ? for SQLite."
    )


def test_public_documents_carry_no_internal_register():
    """That register is how the maintainer and the agent address each other, not the reader."""
    offenders = []
    for relative in PUBLIC_DOCS:
        for lineno, line in enumerate(_read(relative).splitlines(), 1):
            if INTERNAL_REGISTER.search(line):
                offenders.append(f"{relative}:{lineno}: {line.strip()[:80]}")
    assert not offenders, (
        "Internal second-person register in a document a public reader receives:\n"
        + "\n".join(offenders)
    )


def test_public_documents_do_not_name_a_connection_endpoint():
    offenders = []
    for relative in PUBLIC_DOCS:
        for lineno, line in enumerate(_read(relative).splitlines(), 1):
            if POOLER_HOST.search(line):
                offenders.append(f"{relative}:{lineno}")
    assert not offenders, (
        "A concrete Supabase pooler hostname appears in public documentation. Describe it as "
        "'Supabase pooler' instead:\n" + "\n".join(offenders)
    )


def test_code_of_conduct_offers_a_private_reporting_channel():
    """Contributor Covenant 2.1 requires somewhere to report that is not a public issue."""
    text = _read("CODE_OF_CONDUCT.md")
    assert re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), (
        "CODE_OF_CONDUCT.md gives no private reporting address. A reporter's only option is "
        "then a public issue, which is the wrong channel for a conduct complaint."
    )
    assert re.search(r"(?i)report", text), (
        "CODE_OF_CONDUCT.md never tells a reader how to report a violation."
    )


def test_public_documents_do_not_point_at_ignored_handoff_notes():
    """`.handoff/` is gitignored, so a public reader following the reference finds nothing."""
    offenders = []
    for relative in PUBLIC_DOCS:
        for lineno, line in enumerate(_read(relative).splitlines(), 1):
            if ".handoff/" in line:
                offenders.append(f"{relative}:{lineno}")
    assert not offenders, (
        "Public documentation references .handoff/, which is not published:\n" + "\n".join(offenders)
    )
