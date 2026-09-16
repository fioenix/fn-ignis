"""Contracts for two things documentation keeps getting wrong.

**Release state.** Code reaching `main` is not a release. A version is released when a tag exists
and a GitHub Release is published, and those live on the Git and GitHub surface -- not in any file
in this repository. So the work is split in two, and the split is the point:

*a)* the contracts here are an **offline consistency check between tracked documents**. Every
document must agree with the release-state banner in `BACKLOG.md`. The banner is not an authority
on whether a release happened; it is one tracked declaration, and a document contradicting it means
one of the two is wrong. Passing here proves the documents agree, and nothing more.

*b)* whether the version is actually released is decided by `scripts/check_release_state.py`, which
reads the tag list, the published Releases and the repository visibility. Its verdict logic is
exercised below against synthetic surfaces so it stays deterministic; the real surface is queried by
running the script.

**Diagram provenance.** The declared convention is that a diagram is authored as HTML with inline
SVG and exported from there. Nothing enforced it, so the HTML and the standalone SVG were two
hand-edited bodies that happened to agree -- the parallel-source failure the convention exists to
prevent, reintroduced by the tooling meant to serve it. The PNG was outside the gate entirely:
replacing it with a line of text left `--check` reporting success.
"""

import ast
import re
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKLOG = REPO / "BACKLOG.md"
REVIEW_CONTEXT = REPO / "docs" / "PROJECT_REVIEW_CONTEXT.md"
EXPORTER = REPO / "scripts" / "export_diagram.py"
RELEASE_STATE_CHECKER = REPO / "scripts" / "check_release_state.py"

SPEC_DOCS = tuple(sorted((REPO / "specs").glob("*/spec.md"))) + tuple(
    sorted((REPO / "specs").glob("*/tasks.md"))
)
# The review context is the document a reviewer is pointed at first, so a stale current-state claim
# there travels further than the same sentence in a spec.
TRACKED_DOCS = SPEC_DOCS + (REVIEW_CONTEXT,)

# Wording that asserts a release happened. "Shipped in vX" and "the released runtime" both claim
# an event that a tag and a published Release are the evidence for.
RELEASE_CLAIM = re.compile(r"\b(shipped|released)\b", re.IGNORECASE)

# The banner is the one tracked place that states release state in full, so it is the thing other
# documents must not contradict. Matching on its own words keeps this comparison offline.
UNRELEASED_BANNER = re.compile(
    r"(chưa tag|not tagged|untagged)[^.\n]{0,80}(chưa publish|not published|unpublished)"
    r"|(chưa publish|not published)[^.\n]{0,80}(chưa tag|not tagged)",
    re.IGNORECASE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _banner_text() -> str:
    """The release-state banner as one flat string.

    It is a markdown blockquote, so a sentence wraps across lines with a `>` continuation. Matching
    the raw text would make the contract depend on where the line happened to break.
    """
    return re.sub(r"\s*\n>\s*", " ", _read(BACKLOG).split("---", 1)[0])


# --------------------------------------------------------------------------------------------
# a) Offline consistency between tracked documents
# --------------------------------------------------------------------------------------------


def test_release_state_banner_exists_and_is_explicit():
    """The comparisons below need one declaration to compare against; it has to be there."""
    assert UNRELEASED_BANNER.search(_banner_text()), (
        "BACKLOG.md has no explicit release-state banner saying the current version is neither "
        "tagged nor published. That banner is the declaration the wording comparisons below use, "
        "and without it they cannot be evaluated offline."
    )


def test_tracked_documents_do_not_call_an_unreleased_version_shipped():
    """A document that says 'released' while the banner says 'not tagged' is one of them lying."""
    if not UNRELEASED_BANNER.search(_banner_text()):
        pytest.skip("the banner does not declare an unreleased state; nothing to contradict")

    offenders = []
    for path in TRACKED_DOCS:
        for lineno, line in enumerate(_read(path).splitlines(), 1):
            match = RELEASE_CLAIM.search(line)
            if not match:
                continue
            # "must not be released until", "before release" and similar are requirements, not
            # claims that it happened. Only an assertion about the current state is a problem.
            window = line[max(0, match.start() - 60): match.start()]
            if re.search(r"\b(not|never|before|until|once|when|cannot|must)\b", window, re.IGNORECASE):
                continue
            offenders.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()[:110]}")

    assert not offenders, (
        "A tracked document states that the current version shipped or was released, while "
        "BACKLOG.md's banner says it is neither tagged nor published. Say the code is present on "
        "main instead:\n" + "\n".join(offenders)
    )


def _visibility_section() -> str:
    """The review context's discussion of whether to publish the repository."""
    text = _read(REVIEW_CONTEXT)
    start = text.find("Whether to make the repository public")
    assert start != -1, "the review context no longer discusses making the repository public"
    end = text.find("\n4. ", start)
    return text[start: end if end != -1 else len(text)]


@dataclass(frozen=True)
class Blocker:
    """One pre-public blocker, named in two documents that word it in two languages.

    The patterns are a naming link, not a state claim: whether the blocker is open is read from
    BACKLOG.md's checkbox, never from either pattern. That is the whole point -- an earlier version
    of this contract searched for the word "Threads" in a blob of text, which stayed green when
    another blocker was closed and when a heading wrapped onto a second line.
    """

    name: str
    backlog: str  # matches the BACKLOG item, which is written in Vietnamese
    review: str  # matches the review context's bullet, which is written in English


PRE_PUBLIC_BLOCKERS = (
    Blocker("credential rotation", r"xoay vòng ba credential", r"rotated or revoked"),
    Blocker("the Threads authority gap", r"verdict quyền của Threads", r"Threads"),
    Blocker("model-driven release acceptance", r"release acceptance v0\.4\.0", r"model-driven"),
)


def _backlog_items() -> list[tuple[bool, str]]:
    """Every checkbox item in BACKLOG.md as (is_open, the item's full block of text).

    Reading the whole block matters: these items run to several paragraphs, and matching a single
    line means a heading that wraps, or a detail recorded one paragraph down, is invisible.
    """
    items: list[tuple[bool, list[str]]] = []
    inside = False
    for line in _read(BACKLOG).splitlines():
        start = re.match(r"^- \[([ x])\] (.*)$", line)
        if start:
            items.append((start.group(1) == " ", [start.group(2)]))
            inside = True
        elif inside and (not line.strip() or line.startswith((" ", "\t"))):
            items[-1][1].append(line.strip())
        else:
            inside = False
    return [(is_open, " ".join(body)) for is_open, body in items]


def _blocker_is_open(blocker: Blocker) -> bool:
    matched = [item for item in _backlog_items() if re.search(blocker.backlog, item[1])]
    assert len(matched) == 1, (
        f"{blocker.backlog!r} matches {len(matched)} BACKLOG items, not one. A pattern matching "
        "none passes every assertion that follows it, which is the failure this count exists to "
        "stop; a pattern matching several means the state read back is ambiguous."
    )
    return matched[0][0]


def _review_blocker_bullets() -> list[str]:
    """The bullets the review context presents as things blocking a visibility change."""
    bullets: list[str] = []
    for line in _visibility_section().splitlines():
        if re.match(r"^ {3}- ", line):
            bullets.append(line.strip())
        elif bullets and re.match(r"^ {5,}\S", line):
            bullets[-1] += " " + line.strip()
        elif bullets:
            break
    return bullets


def test_credential_rotation_is_still_an_open_blocker():
    assert _blocker_is_open(PRE_PUBLIC_BLOCKERS[0]), (
        "BACKLOG.md marks credential rotation done. Nothing may record that rotation happened "
        "until the operator confirms it."
    )


def test_the_threads_authority_gap_is_still_an_open_blocker():
    assert _blocker_is_open(PRE_PUBLIC_BLOCKERS[1])


def test_model_driven_release_acceptance_is_closed():
    """Asserted separately, because it is the one whose state the review context got wrong."""
    assert not _blocker_is_open(PRE_PUBLIC_BLOCKERS[2]), (
        "BACKLOG.md records release acceptance as still open. If that is right, the review "
        "context should list it again; if not, one of the two documents is stale."
    )


def test_every_open_blocker_is_listed_in_the_review_context():
    """A blocker list that omits an open blocker reads as clearance to proceed."""
    bullets = _review_blocker_bullets()
    assert bullets, "the review context's visibility item lists no blockers at all"

    missing = [
        blocker.name
        for blocker in PRE_PUBLIC_BLOCKERS
        if _blocker_is_open(blocker)
        and not any(re.search(blocker.review, text, re.IGNORECASE) for text in bullets)
    ]
    assert not missing, (
        "BACKLOG.md carries these as open pre-public blockers, but the review context's list does "
        "not name them: " + ", ".join(missing)
    )


def test_the_review_context_does_not_list_a_closed_blocker():
    """Reopening a finished item costs the same as hiding an unfinished one: the list stops being read."""
    bullets = _review_blocker_bullets()
    reopened = [
        f"{blocker.name}: {text[:100]}"
        for blocker in PRE_PUBLIC_BLOCKERS
        if not _blocker_is_open(blocker)
        for text in bullets
        if re.search(blocker.review, text, re.IGNORECASE)
    ]
    assert not reopened, (
        "The review context lists a blocker that BACKLOG.md has closed with evidence:\n"
        + "\n".join(reopened)
    )


# Wording that describes where a change currently sits in review rather than what has to be true.
# It is accurate for a day and wrong afterwards, and nothing makes anyone come back to fix it.
TRANSIENT_STATE_WORDING = (
    r"stacked branch",
    r"\bunmerged\b",
    r"not yet merged",
    r"reviewed but",
    r"this documentation pass",
)


def _current_state_header() -> str:
    """The opening summary, which is the other place that has carried review-state wording."""
    text = _read(REVIEW_CONTEXT)
    start = text.index("## Current review target")
    return text[start: text.index("\n## ", start + 1)]


def test_durable_sections_state_conditions_rather_than_review_state():
    """These two passages outlive any branch; a sentence about a branch in them expires unread.

    Scoped to the two passages that make the claim, not to the whole document: elsewhere,
    describing what is merged is a legitimate record of what happened on a date.
    """
    offenders = []
    for name, section in (
        ("the visibility item", _visibility_section()),
        ("the current-state header", _current_state_header()),
    ):
        for pattern in TRANSIENT_STATE_WORDING:
            match = re.search(pattern, section, re.IGNORECASE)
            if match:
                offenders.append(f"{name}: {match.group(0)!r}")
    assert not offenders, (
        "These passages describe where work currently sits in review instead of what must be true "
        "before visibility changes. Such a sentence is wrong the moment the work merges, and "
        "nothing brings anyone back to it:\n" + "\n".join(offenders)
    )


def test_the_visibility_item_states_both_ordering_conditions():
    """The invariants themselves: what must have happened before the switch, in what order."""
    # Flattened first: the prose wraps, so a phrase can straddle two lines and a pattern keyed to
    # the raw text would report a missing invariant that is sitting right there.
    section = re.sub(r"\s+", " ", _visibility_section())
    missing = [
        name
        for name, pattern in (
            ("rotation before the visibility change", r"rotated or revoked before"),
            ("the hardening commits on `main` before the visibility change", r"on `main` before"),
        )
        if not re.search(pattern, section, re.IGNORECASE)
    ]
    assert not missing, (
        "The visibility item no longer states: " + ", ".join(missing) + ". Both are conditions "
        "that hold before and after any branch merges, which is what makes them worth writing."
    )


# A number in front of a noun that stands for a blocker or a precondition. It is deliberately
# blind to the current count: a contract that knew there were three today would have to be edited
# by whoever adds the fourth, which is the same hand-maintenance the count itself fails at.
COUNTED_CONDITIONS = re.compile(
    # At most two words may sit between the number and the noun, and none of them may be a
    # connective: without that, a cross-reference like "see §4 and item 0" reads as a count.
    r"\b(one|two|three|four|five|six|\d+)\s+(?:(?!and\b|or\b|in\b)[\w-]+\s+){0,2}"
    r"(things?|conditions?|blockers?|items?|gates?|requirements?|steps?)\b",
    re.IGNORECASE,
)


def test_durable_sections_do_not_count_the_pre_public_conditions():
    """One passage said "two conditions" while the decision below listed three.

    A summary that counts has to be re-counted by whoever changes the list, and nothing makes them.
    The two passages are checked together because the contradiction was between them: the count
    sat in the header and the list it was counting sat in the visibility item.
    """
    offenders = []
    for name, section in (
        ("the visibility item", _visibility_section()),
        ("the current-state header", _current_state_header()),
    ):
        for match in COUNTED_CONDITIONS.finditer(re.sub(r"\s+", " ", section)):
            offenders.append(f"{name}: {match.group(0)!r}")
    assert not offenders, (
        "These passages state how many pre-public conditions there are:\n"
        + "\n".join(offenders)
        + "\nName them once, in the visibility decision, and refer to that list rather than "
        "counting it."
    )


# --------------------------------------------------------------------------------------------
# b) Release acceptance, decided by the real Git/GitHub surface
# --------------------------------------------------------------------------------------------


def _release_checker():
    sys.path.insert(0, str(REPO / "scripts"))
    import check_release_state  # noqa: PLC0415

    return check_release_state


def _surface(module, **overrides):
    facts = {"tag_exists": True, "release_published": True, "repository_public": True}
    facts.update(overrides)
    return module.ReleaseSurface(**facts)


def test_release_acceptance_needs_a_tag_and_a_published_release():
    module = _release_checker()

    released, missing, unknown = module.release_verdict("0.4.0", _surface(module))
    assert released and not missing and not unknown

    released, missing, _ = module.release_verdict(
        "0.4.0", _surface(module, release_published=False)
    )
    assert not released
    assert any("Release" in item for item in missing)

    released, missing, _ = module.release_verdict(
        "0.4.0", _surface(module, tag_exists=False, release_published=False)
    )
    assert not released
    assert len(missing) == 2


def test_a_public_repository_alone_is_not_a_release():
    """Visibility is a separate fact; flipping it releases nothing."""
    module = _release_checker()
    released, _, _ = module.release_verdict(
        "0.4.0", _surface(module, tag_exists=False, release_published=False)
    )
    assert not released


def test_an_unread_fact_is_not_a_negative_one():
    """Unknown must not collapse into False: that is how a tool outage becomes a finding."""
    module = _release_checker()
    released, missing, unknown = module.release_verdict(
        "0.4.0", _surface(module, release_published=None)
    )
    assert not released
    assert unknown, "a surface fact that could not be read was reported as known"
    assert not any("no published" in item for item in missing), (
        "an unread Release was listed as missing evidence, which states it is absent"
    )


def test_a_failed_release_lookup_is_unknown_rather_than_unpublished(monkeypatch):
    """gh writes auth and network failures to stderr and leaves stdout empty.

    Inferring "no release" from an empty stdout turns every outage into the same answer as a
    genuinely unreleased version, and the two call for opposite actions.
    """
    module = _release_checker()
    real = module._run

    def failing(command):
        if command[:3] == ["gh", "release", "view"]:
            return module.CommandResult(1, "", "authentication failed")
        return real(command)

    monkeypatch.setattr(module, "_run", failing)
    surface, unknown = module.read_surface("0.4.0")
    assert surface.release_published is None
    assert any("auth" in note.lower() for note in unknown), unknown


def test_a_genuinely_missing_release_is_a_fact_not_an_unknown(monkeypatch):
    """The other side of the same call: gh says 'release not found' when it really is not there."""
    module = _release_checker()
    real = module._run

    def not_found(command):
        if command[:3] == ["gh", "release", "view"]:
            return module.CommandResult(1, "", "release not found")
        return real(command)

    monkeypatch.setattr(module, "_run", not_found)
    surface, unknown = module.read_surface("0.4.0")
    assert surface.release_published is False
    assert not any("release view" in note for note in unknown), unknown


def test_the_report_does_not_state_an_unread_fact(monkeypatch, capsys):
    module = _release_checker()
    real = module._run

    def failing(command):
        if command[:3] == ["gh", "release", "view"]:
            return module.CommandResult(1, "", "authentication failed")
        return real(command)

    monkeypatch.setattr(module, "_run", failing)
    exit_code = module.main(["0.4.0"])
    printed = capsys.readouterr().out

    assert exit_code != 0
    assert "not published" not in printed, (
        "the report states the Release is not published, when the lookup failed and it was never "
        f"read:\n{printed}"
    )
    assert "unknown" in printed.lower()


def test_the_acceptance_checker_does_not_read_documents():
    """If it read the prose, it would certify the prose -- which is the failure it exists to catch.

    Docstrings are excluded deliberately: the script has to be able to *explain* why it ignores
    `BACKLOG.md` without that explanation tripping the contract. What matters is whether a path to
    a tracked document can reach an open() call, so only executable string literals are examined.
    """
    tree = ast.parse(_read(RELEASE_STATE_CHECKER))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    for name in ("BACKLOG", "PROJECT_REVIEW_CONTEXT", "specs"):
        offenders = [text for text in literals if name in text]
        assert not offenders, (
            f"scripts/check_release_state.py names {name!r} in executable code ({offenders!r}). "
            "Release acceptance must be read from the Git and GitHub surface only; a checker that "
            "consults tracked documents certifies the documents agreeing with themselves."
        )


# --------------------------------------------------------------------------------------------
# Diagram inventory
# --------------------------------------------------------------------------------------------


def _inventory_section() -> str:
    text = _read(REVIEW_CONTEXT)
    section = text.split("## 2. Reading the architecture", 1)
    assert len(section) == 2, "the review context has no architecture-reading section to inventory"
    return section[1].split("\n## ", 1)[0]


def _expand(raw: str) -> list[str]:
    brace = re.search(r"\{([^}]*)\}", raw)
    if not brace:
        return [raw]
    stem = raw[: brace.start()]
    return [f"{stem}{ext.strip()}" for ext in brace.group(1).split(",")]


def _inventory_entries() -> list[tuple[list[str], str | None]]:
    """Each inventory bullet as (paths it names, the verification date it records)."""
    entries = []
    for match in re.finditer(
        r"^- `(docs/[^`]+)`(.*?)(?=^- `|\Z)", _inventory_section(), re.M | re.S
    ):
        # The bullet wraps, so the phrase and its date can land on different lines.
        flat = re.sub(r"\s+", " ", match.group(2))
        date = re.search(r"footer verified (\d{2}/\d{2}/\d{4})", flat)
        entries.append((_expand(match.group(1)), date.group(1) if date else None))
    return entries


def _inventory_diagram_paths() -> list[str]:
    return [path for paths, _ in _inventory_entries() for path in paths]


def test_every_diagram_the_inventory_names_exists():
    """An inventory pointing at a deleted file sends a reader to a 404 and reads as authoritative."""
    named = _inventory_diagram_paths()
    assert named, "the architecture-reading section names no diagram files at all"

    missing = [p for p in named if not (REPO / p).exists()]
    assert not missing, (
        "The diagram inventory in docs/PROJECT_REVIEW_CONTEXT.md names files that do not exist:\n"
        + "\n".join(missing)
    )


def test_every_diagram_on_disk_is_named_by_the_inventory():
    """The reverse direction: a diagram nobody lists is a diagram nobody maintains."""
    on_disk = {
        p.relative_to(REPO).as_posix()
        for p in list((REPO / "docs" / "diagrams").glob("*.html"))
        + [REPO / "docs" / "assets" / "architecture.html"]
    }
    named = set(_inventory_diagram_paths())
    unlisted = sorted(on_disk - named)
    assert not unlisted, (
        "These diagrams exist but the inventory does not name them:\n" + "\n".join(unlisted)
    )


def test_each_diagram_footer_carries_the_date_the_inventory_records():
    """The inventory says footers carry the verification date, so the two must be one edit.

    Without this, changing a diagram's content and leaving its footer alone dates the new picture
    to the day the old one was checked.
    """
    mismatches = []
    for paths, recorded in _inventory_entries():
        html = next((p for p in paths if p.endswith(".html")), None)
        if html is None:
            continue
        if recorded is None:
            mismatches.append(f"{html}: the inventory records no 'footer verified DD/MM/YYYY'")
            continue
        footer = re.search(r"<footer>(.*?)</footer>", _read(REPO / html), re.S)
        if not footer:
            mismatches.append(f"{html}: no <footer> to carry a verification date")
        elif recorded not in footer.group(1):
            mismatches.append(
                f"{html}: footer reads {footer.group(1).strip()[:80]!r}, "
                f"but the inventory records {recorded}"
            )
    assert not mismatches, "\n".join(mismatches)


# --------------------------------------------------------------------------------------------
# Diagram export provenance
# --------------------------------------------------------------------------------------------

ARCHITECTURE_HTML = REPO / "docs" / "assets" / "architecture.html"
ARCHITECTURE_SVG = REPO / "docs" / "assets" / "architecture.svg"
ARCHITECTURE_PNG = REPO / "docs" / "assets" / "architecture.png"


def _exported_diagrams() -> list[Path]:
    """Every diagram that has exports, read from disk rather than listed here.

    Naming them would mean the contract covered whatever was true the day it was written. When
    `ignis-source-map` and `ignis-pipeline` gained exports, a hand-written list would have kept
    testing `architecture` alone and reported that as full coverage.
    """
    found = sorted(
        html
        for html in list((REPO / "docs" / "diagrams").glob("*.html"))
        + [REPO / "docs" / "assets" / "architecture.html"]
        if html.with_suffix(".svg").exists() or html.with_suffix(".png").exists()
    )
    assert found, "no diagram has exports; the provenance gate would be testing nothing"
    return found


def _png_chunk(chunk_type: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + chunk_type + body + struct.pack(">I", crc)


def _exporter():
    sys.path.insert(0, str(REPO / "scripts"))
    import export_diagram  # noqa: PLC0415

    return export_diagram


def test_exporter_takes_the_html_as_its_input():
    """The HTML is the authored artifact; an exporter starting from the SVG enforces nothing."""
    module = _exporter()
    assert hasattr(module, "svg_from_html"), (
        "scripts/export_diagram.py exposes no svg_from_html(); the exporter cannot be starting "
        "from the HTML artifact."
    )
    completed = subprocess.run(
        [sys.executable, str(EXPORTER), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "html" in completed.stdout.lower(), (
        f"the exporter's own help does not mention HTML input:\n{completed.stdout}"
    )


def test_committed_svg_equals_the_one_exported_from_the_html():
    """The parity gate. Two hand-edited bodies that agree today are the drift that starts tomorrow."""
    module = _exporter()
    exported = module.svg_from_html(_read(ARCHITECTURE_HTML))
    committed = _read(ARCHITECTURE_SVG)
    assert exported == committed, (
        "docs/assets/architecture.svg is not what the HTML exports to. Regenerate it with "
        "scripts/export_diagram.py rather than editing the SVG by hand; the difference means the "
        "two files are being maintained separately again."
    )


def test_inline_svg_extraction_fails_closed():
    """Guessing which SVG was meant is how the wrong picture gets published."""
    module = _exporter()
    with pytest.raises(ValueError):
        module.extract_inline_svg("<html><body><p>no diagram here</p></body></html>")
    with pytest.raises(ValueError):
        module.extract_inline_svg("<html><svg viewBox='0 0 1 1'></svg><svg></svg></html>")


def test_output_size_comes_from_the_viewbox():
    module = _exporter()
    assert module.viewbox_size('<svg viewBox="0 0 1232 640"></svg>') == (1232, 640)
    with pytest.raises(ValueError):
        module.viewbox_size("<svg></svg>")


def test_committed_png_is_a_png_of_the_expected_size():
    """Byte equality across platforms is not available, so the checkable facts are checked.

    A rasterizer on another machine produces different bytes for the same picture; its header does
    not move. Dimensions catch a PNG rendered from a differently-sized diagram, and the signature
    catches a file that is not a PNG at all -- which is how this gap was found.
    """
    module = _exporter()
    data = ARCHITECTURE_PNG.read_bytes()
    assert data.startswith(module.PNG_SIGNATURE), (
        "docs/assets/architecture.png does not begin with the PNG signature, so whatever it is, "
        "it is not the exported raster."
    )
    width, height = module.viewbox_size(_read(ARCHITECTURE_SVG))
    assert module.png_dimensions(data) == (width * module.SCALE, height * module.SCALE)


def test_committed_png_is_stamped_with_the_digest_of_the_svg_it_came_from():
    """The PNG is a derived artifact; without a stamp there is nothing tying it to its source."""
    module = _exporter()
    stamped = module.png_source_digest(ARCHITECTURE_PNG.read_bytes())
    expected = module.source_digest(module.svg_from_html(_read(ARCHITECTURE_HTML)))
    assert stamped == expected, (
        "docs/assets/architecture.png carries source digest "
        f"{stamped!r}, but the current HTML exports to an SVG with digest {expected!r}. The PNG "
        "was rendered from an older source; re-export it."
    )


def _check_exit_code(tmp_path: Path, *, png: bytes | None) -> int:
    """Run `--check` over a copy of the diagram whose PNG has been tampered with."""
    module = _exporter()
    html = tmp_path / "architecture.html"
    html.write_text(_read(ARCHITECTURE_HTML), encoding="utf-8")
    (tmp_path / "architecture.svg").write_text(
        module.svg_from_html(_read(ARCHITECTURE_HTML)), encoding="utf-8"
    )
    if png is not None:
        (tmp_path / "architecture.png").write_bytes(png)
    return module.check(html)


def test_check_accepts_a_faithfully_exported_diagram(tmp_path):
    assert _check_exit_code(tmp_path, png=ARCHITECTURE_PNG.read_bytes()) == 0


def test_check_rejects_a_png_that_is_not_a_png(tmp_path):
    assert _check_exit_code(tmp_path, png=b"this is not a png\n") == 1


def test_check_rejects_a_missing_png(tmp_path):
    assert _check_exit_code(tmp_path, png=None) == 1


def test_check_rejects_a_png_carrying_an_older_source_digest(tmp_path):
    module = _exporter()
    stale = module.stamp_png(ARCHITECTURE_PNG.read_bytes(), "0" * 64)
    assert _check_exit_code(tmp_path, png=stale) == 1


def test_check_rejects_a_png_whose_dimensions_do_not_match_the_viewbox(tmp_path):
    module = _exporter()
    data = bytearray(ARCHITECTURE_PNG.read_bytes())
    width, height = module.png_dimensions(bytes(data))
    resized = module.stamp_png(
        module.with_ihdr_size(bytes(data), width + 8, height),
        module.source_digest(module.svg_from_html(_read(ARCHITECTURE_HTML))),
    )
    assert _check_exit_code(tmp_path, png=resized) == 1


def _with_image_data(data: bytes, raw: bytes) -> bytes:
    """Rebuild the PNG around new decompressed image data, with a valid stream and CRC."""
    module = _exporter()
    out = bytearray(module.PNG_SIGNATURE)
    written = False
    for chunk_type, _, start, end in module._chunks(data):
        if chunk_type != b"IDAT":
            out += data[start:end]
        elif not written:
            out += _png_chunk(b"IDAT", zlib.compress(raw, 9))
            written = True
    return bytes(out)


def _decompressed_image_data(data: bytes) -> bytearray:
    module = _exporter()
    return bytearray(
        zlib.decompress(
            b"".join(body for kind, body, _, _ in module._chunks(data) if kind == b"IDAT")
        )
    )


def test_committed_png_decodes_to_its_declared_size():
    """The positive case: the committed raster is an image a viewer can actually open."""
    module = _exporter()
    assert module.decode_png(ARCHITECTURE_PNG.read_bytes()) == module.png_dimensions(
        ARCHITECTURE_PNG.read_bytes()
    )


def test_check_rejects_a_png_with_a_header_and_no_image(tmp_path):
    """A signature, an IHDR and the right digest are metadata; a viewer gets naturalWidth 0."""
    module = _exporter()
    svg = module.svg_from_html(_read(ARCHITECTURE_HTML))
    width, height = module.viewbox_size(svg)
    header = struct.pack(">IIBBBBB", width * module.SCALE, height * module.SCALE, 8, 2, 0, 0, 0)
    metadata_only = (
        module.PNG_SIGNATURE
        + _png_chunk(b"IHDR", header)
        + _png_chunk(
            b"tEXt", module.DIGEST_KEYWORD + b"\x00" + module.source_digest(svg).encode()
        )
    )
    assert _check_exit_code(tmp_path, png=metadata_only) == 1


def test_check_rejects_a_png_with_a_corrupt_chunk_crc(tmp_path):
    """A flipped byte a stamping tool wrote back without recomputing the checksum."""
    data = bytearray(ARCHITECTURE_PNG.read_bytes())
    data[-1] ^= 0xFF  # the IEND chunk's CRC
    assert _check_exit_code(tmp_path, png=bytes(data)) == 1


def test_check_rejects_a_png_whose_image_data_does_not_decompress(tmp_path):
    """Structurally intact, zlib stream destroyed -- exactly what a truncated write leaves."""
    module = _exporter()
    rebuilt = bytearray(module.PNG_SIGNATURE)
    for chunk_type, body, start, end in module._chunks(ARCHITECTURE_PNG.read_bytes()):
        if chunk_type == b"IDAT":
            rebuilt += _png_chunk(b"IDAT", b"\x00" * len(body))
        else:
            rebuilt += ARCHITECTURE_PNG.read_bytes()[start:end]
    assert _check_exit_code(tmp_path, png=bytes(rebuilt)) == 1


def test_check_rejects_bytes_after_the_end_marker(tmp_path):
    """Anything past IEND means two writers touched the file, and only one of them is known."""
    assert _check_exit_code(tmp_path, png=ARCHITECTURE_PNG.read_bytes() + b"appended") == 1


def test_check_rejects_a_scanline_with_an_undefined_filter_byte(tmp_path):
    """PNG defines filter types 0 to 4. A fifth is not a filter, so the row cannot be unpacked.

    Everything else about the file stays valid -- the zlib stream inflates, the CRC matches, the
    byte count is exactly what the header calls for. Only the per-row filter is wrong, and that is
    enough for the picture a viewer draws to stop being the picture that was exported.
    """
    data = ARCHITECTURE_PNG.read_bytes()
    raw = _decompressed_image_data(data)
    raw[0] = 5
    assert _check_exit_code(tmp_path, png=_with_image_data(data, bytes(raw))) == 1


def test_check_accepts_every_defined_filter_byte(tmp_path):
    """The other side: 0 to 4 are all legal, so the check must not narrow to whatever this file uses."""
    module = _exporter()
    data = ARCHITECTURE_PNG.read_bytes()
    width, _ = module.png_dimensions(data)
    stride = 1 + width * 3  # colour type 2: three channels
    raw = _decompressed_image_data(data)
    for row, filter_byte in enumerate((0, 1, 2, 3, 4)):
        raw[row * stride] = filter_byte
    assert _check_exit_code(tmp_path, png=_with_image_data(data, bytes(raw))) == 0


def test_check_rejects_an_iend_that_carries_a_body(tmp_path):
    """IEND is empty by definition; bytes inside it are a payload riding in the end marker."""
    module = _exporter()
    data = ARCHITECTURE_PNG.read_bytes()
    out = bytearray(module.PNG_SIGNATURE)
    for chunk_type, _, start, end in module._chunks(data):
        out += _png_chunk(b"IEND", b"junk") if chunk_type == b"IEND" else data[start:end]
    assert _check_exit_code(tmp_path, png=bytes(out)) == 1


@pytest.mark.parametrize(
    "html", _exported_diagrams(), ids=lambda p: p.stem
)
def test_every_exported_diagram_matches_its_html(html):
    """The parity gate, applied to whatever has exports rather than to one named file."""
    module = _exporter()
    assert module.check(html) == 0, (
        f"{html.relative_to(REPO)} and its exports disagree. Regenerate them with "
        "scripts/export_diagram.py rather than editing the SVG or PNG by hand."
    )


def test_a_diagram_a_readme_embeds_has_exports():
    """The convention's own condition: embedding as an image is what earns a diagram its exports."""
    embedded = set()
    for readme in (REPO / "README.md", REPO / "README.vi.md"):
        for match in re.finditer(r'<img src="(docs/[^"]+\.png)"', _read(readme)):
            embedded.add(match.group(1))
    assert embedded, "neither README embeds a diagram; the convention has nothing to enforce"

    missing = [
        path
        for path in sorted(embedded)
        if not (REPO / path).exists() or not (REPO / path).with_suffix(".html").exists()
    ]
    assert not missing, (
        "A README embeds these images, but the PNG or its authored HTML source is absent:\n"
        + "\n".join(missing)
    )
