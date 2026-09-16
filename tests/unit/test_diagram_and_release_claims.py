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
import subprocess
import sys
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


def test_pre_public_blockers_name_rotation_and_the_threads_authority_gap():
    """A blocker list that omits an open blocker reads as clearance to proceed."""
    section = _visibility_section()
    missing = [
        name
        for name, pattern in (
            ("credential rotation", r"rotat"),
            ("the Threads authority gap", r"Threads"),
        )
        if not re.search(pattern, section, re.IGNORECASE)
    ]
    assert not missing, (
        "The review context's pre-public blocker list does not name: "
        + ", ".join(missing)
        + ". BACKLOG.md carries both as open blockers, so a reader of this document would "
        "conclude fewer things stand in the way than actually do."
    )


def test_pre_public_blockers_are_not_stated_as_a_fixed_count():
    """A written count goes stale the moment a blocker is added, and nothing forces it updated."""
    section = _visibility_section()
    counted = re.search(
        r"\b(one|two|three|four|1|2|3|4)\s+things?\s+block", section, re.IGNORECASE
    )
    assert not counted, (
        "The pre-public blocker list states a fixed count "
        f"({counted.group(0)!r}). Counts drift silently as blockers are opened and closed; list "
        "the blockers and let the list be the count."
    )


def test_backlog_still_carries_both_pre_public_blockers_open():
    """The other half of the agreement: the list above must describe items that are still open."""
    text = _read(BACKLOG)
    open_blockers = [
        line for line in text.splitlines() if line.lstrip().startswith("- [ ]") and "public" in line
    ]
    joined = "\n".join(open_blockers)
    assert re.search(r"Threads", joined), (
        "BACKLOG.md has no open pre-public blocker mentioning Threads, but the review context "
        "lists one. One of the two documents is out of date."
    )


# --------------------------------------------------------------------------------------------
# b) Release acceptance, decided by the real Git/GitHub surface
# --------------------------------------------------------------------------------------------


def _release_checker():
    sys.path.insert(0, str(REPO / "scripts"))
    import check_release_state  # noqa: PLC0415

    return check_release_state


def test_release_acceptance_needs_a_tag_and_a_published_release():
    module = _release_checker()
    surface = module.ReleaseSurface

    released, missing = module.release_verdict(
        "0.4.0", surface(tag_exists=True, release_published=True, repository_public=True)
    )
    assert released and not missing

    released, missing = module.release_verdict(
        "0.4.0", surface(tag_exists=True, release_published=False, repository_public=True)
    )
    assert not released
    assert any("Release" in item for item in missing)

    released, missing = module.release_verdict(
        "0.4.0", surface(tag_exists=False, release_published=False, repository_public=False)
    )
    assert not released
    assert len(missing) == 2


def test_a_public_repository_alone_is_not_a_release():
    """Visibility is a separate fact; flipping it releases nothing."""
    module = _release_checker()
    released, _ = module.release_verdict(
        "0.4.0",
        module.ReleaseSurface(
            tag_exists=False, release_published=False, repository_public=True
        ),
    )
    assert not released


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
