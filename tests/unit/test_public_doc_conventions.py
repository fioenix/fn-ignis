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
    "docs/META_INTEGRATION_GUIDE.md",
    "docs/META_INTEGRATION_GUIDE.vi.md",
)

# Documents that describe what the encryption, logging and sanitization layers actually do. A
# capability claimed here is read as a guarantee by anyone deciding what to store in this system.
SECURITY_CLAIM_DOCS = (
    "SECURITY.md",
    "BACKLOG.md",
    "README.md",
    "README.vi.md",
    "docs/META_INTEGRATION_GUIDE.md",
    "docs/META_INTEGRATION_GUIDE.vi.md",
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


# --- Claims the runtime does not implement -------------------------------------------------
#
# `key_version` is written into the ciphertext envelope on encrypt and echoed back in status
# payloads. `decrypt_credentials` builds one Fernet from the current key and never reads it, so
# there is no old-key detection, no dual-key path and no re-encryption. Any wording that implies
# otherwise tells an operator a key swap is recoverable when it is not.
# Matched as affirmative capability claims, each listed on its own rather than by proximity to
# "key_version". The first draft of this pattern keyed on key_version within one sentence and
# missed the Vietnamese guide, where the label is introduced in one sentence and the capability
# asserted in the next. Stating an absence -- "there is no dual-key decryption path" -- must keep
# passing, so nothing here matches a negated form.
KEY_ROTATION_OVERCLAIM = re.compile(
    r"key[_ ]version[^.\n]{0,200}?"
    r"(rotat|old key|previous key|nâng cấp|automatic|migrat|re-?encrypt)"
    r"|(ready for|sẵn sàng cho)[^.\n]{0,40}key rotation"
    r"|nhận biết[^.\n]{0,40}(bản ghi )?cũ"
    r"|tự động[^.\n]{0,30}giải mã"
    r"|giải mã[^.\n]{0,30}tự động"
    r"|automatic(ally)?[^.\n]{0,30}(decrypt|re-?encrypt|upgrad|migrat)"
    r"|(decrypt|re-?encrypt|upgrad|migrat)[^.\n]{0,30}automatic(ally)?",
    re.IGNORECASE | re.DOTALL,
)

# Credentials are encrypted at rest and selected outputs are scrubbed. "Never" promises a property
# of every future code path, which no pattern-based layer can hold.
NEVER_IN_LLM_CONTEXT = re.compile(
    r"(never|không bao giờ)[^.\n]{0,120}(LLM|prompt context|model context)"
    r"|plaintext credentials?[^.\n]{0,60}(never|không bao giờ)",
    re.IGNORECASE | re.DOTALL,
)

# The sanitizer matches patterns. It cannot certify that every identifier in third-party content
# has been found.
ABSOLUTE_PII_CLAIM = re.compile(
    r"(all|every|mọi|toàn bộ)[^.\n]{0,80}"
    r"(payload|content|PII|dữ liệu)[^.\n]{0,80}"
    r"(strip|scrub|sanitiz|remov|loại|xoá|xóa)"
    r"|(strip|scrub|sanitiz|remov|loại|xoá|xóa)[^.\n]{0,40}"
    r"(all|every|mọi|toàn bộ)[^.\n]{0,60}(PII|payload)",
    re.IGNORECASE | re.DOTALL,
)


# Denying a capability has to keep passing, or the rule forbids the correction it demands. Saying
# "there is no dual-key decryption" names the same words as claiming one exists, so the words alone
# cannot decide; the negation in front of them is what separates the two.
NEGATION_BEFORE_CLAIM = re.compile(
    r"\b(no|not|never|without|cannot|does not|do not|is not|are not)\b"
    r"|(không|chưa|không được|không phải|thay vì)",
    re.IGNORECASE,
)


def _claim_is_denied(line: str, match: re.Match) -> bool:
    """True when the text immediately before the match turns it into a denial."""
    window = line[max(0, match.start() - 80): match.start()]
    return bool(NEGATION_BEFORE_CLAIM.search(window))


def test_no_document_claims_key_version_enables_rotation():
    """key_version is an envelope label, not a mechanism. Saying otherwise invites data loss."""
    offenders = []
    for relative in SECURITY_CLAIM_DOCS:
        for lineno, line in enumerate(_read(relative).splitlines(), 1):
            match = KEY_ROTATION_OVERCLAIM.search(line)
            if match and not _claim_is_denied(line, match):
                offenders.append(f"{relative}:{lineno}: {line.strip()[:110]}")
    assert not offenders, (
        "Documentation implies key_version supports key rotation, old-key decryption or automatic "
        "re-encryption. decrypt_credentials() builds one Fernet from the current key and never "
        "reads key_version:\n" + "\n".join(offenders)
    )


def test_no_document_promises_credentials_never_reach_llm_context():
    """A 'never' about future code paths is not a property this codebase can enforce."""
    offenders = []
    for relative in SECURITY_CLAIM_DOCS:
        for lineno, line in enumerate(_read(relative).splitlines(), 1):
            if NEVER_IN_LLM_CONTEXT.search(line):
                offenders.append(f"{relative}:{lineno}: {line.strip()[:110]}")
    assert not offenders, (
        "Documentation promises plaintext credentials never reach an LLM context. State what the "
        "runtime does -- encrypt at rest, sanitize selected outputs -- and tell operators not to "
        "paste long-lived credentials into a chat:\n" + "\n".join(offenders)
    )


def test_no_document_promises_every_identifier_is_removed():
    """PII filtering is pattern-based; wording must not read as a guarantee."""
    offenders = []
    for relative in SECURITY_CLAIM_DOCS:
        for lineno, line in enumerate(_read(relative).splitlines(), 1):
            if ABSOLUTE_PII_CLAIM.search(line):
                offenders.append(f"{relative}:{lineno}: {line.strip()[:110]}")
    assert not offenders, (
        "Documentation claims all PII is stripped. The sanitizer matches patterns and cannot "
        "certify completeness over third-party content:\n" + "\n".join(offenders)
    )


def test_security_policy_separates_deployment_config_from_stored_credentials():
    """Two different stores with two different risks; collapsing them misleads an operator.

    Static deployment configuration -- the database connection settings and the encryption key --
    comes from the environment file. Platform OAuth and browser-session credentials are encrypted
    and held in the database. A policy that says every secret lives in one file describes only the
    first and leaves the operator unaware of the second.
    """
    text = _read("SECURITY.md")
    # Either order: the scoping words may introduce the file or follow it.
    scoped = re.search(
        r"\.env[^.]{0,200}(deployment|connection|configuration)"
        r"|(deployment|connection|configuration)[^.]{0,200}\.env",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    assert scoped, (
        "SECURITY.md does not scope the .env claim to static deployment configuration."
    )
    assert re.search(
        r"(encrypted|encryption)[^.]{0,200}(database|stored)"
        r"|(database|stored)[^.]{0,200}encrypted",
        text,
        re.IGNORECASE | re.DOTALL,
    ), (
        "SECURITY.md does not say that platform/session credentials are encrypted and stored in "
        "the database, separately from the environment file."
    )


def test_security_policy_binds_each_placeholder_to_its_backend():
    """`?` appears in ordinary prose, so presence alone proves nothing about SQLite."""
    text = _read("SECURITY.md")
    postgres_bound = re.search(r"`%s`[^.\n]{0,60}postgres|postgres[^.\n]{0,60}`%s`", text, re.IGNORECASE)
    sqlite_bound = re.search(r"`\?`[^.\n]{0,60}sqlite|sqlite[^.\n]{0,60}`\?`", text, re.IGNORECASE)
    assert postgres_bound, "SECURITY.md does not associate the `%s` placeholder with PostgreSQL."
    assert sqlite_bound, "SECURITY.md does not associate the `?` placeholder with SQLite."


def test_handoff_rule_does_not_reach_local_output_paths_in_migration_docs():
    """The migration runbook legitimately writes audit output into a local .handoff/ directory.

    That is an operator command, not a cross-reference a reader is expected to follow, so the
    published-reference rule must not be extended across docs/ blindly. This test pins the
    exception so a later tightening has to be deliberate.
    """
    runbook = Path("docs/migrations/2026-09-10-source-observation-baseline.md")
    assert runbook.as_posix() not in PUBLIC_DOCS, (
        "The migration runbook was added to PUBLIC_DOCS. Its .handoff/ mentions are local output "
        "paths in operator commands; adding it here would flag legitimate usage."
    )
    assert ".handoff/" in (REPO / runbook).read_text(encoding="utf-8"), (
        "The migration runbook no longer writes to .handoff/. If that changed on purpose, remove "
        "this exception rather than leaving a test that guards nothing."
    )
