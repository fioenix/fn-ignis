"""Contracts for two things documentation keeps getting wrong.

**Release state.** Code reaching `main` is not a release. A version is released when a tag exists
and a GitHub Release is published; until then the accurate statement is that the code is present.
Writing "shipped" earlier costs nothing until someone plans around it. This checks wording against
the repository's own release-state banner rather than against GitHub, so it runs offline and in CI.

**Diagram provenance.** The declared convention is that a diagram is authored as HTML with inline
SVG and exported from there. Nothing enforced it, so the HTML and the standalone SVG were two
hand-edited bodies that happened to agree -- the parallel-source failure the convention exists to
prevent, reintroduced by the tooling meant to serve it.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKLOG = REPO / "BACKLOG.md"
REVIEW_CONTEXT = REPO / "docs" / "PROJECT_REVIEW_CONTEXT.md"
EXPORTER = REPO / "scripts" / "export_diagram.py"

SPEC_DOCS = tuple(sorted((REPO / "specs").glob("*/spec.md"))) + tuple(
    sorted((REPO / "specs").glob("*/tasks.md"))
)

# Wording that asserts a release happened. "Shipped in vX" and "the released runtime" both claim
# an event that a tag and a published Release are the evidence for.
RELEASE_CLAIM = re.compile(r"\b(shipped|released)\b", re.IGNORECASE)

# The banner is the one tracked place that states release state in full, so it is the thing other
# documents must not contradict. Matching on its own words keeps this test offline.
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


def test_release_state_banner_exists_and_is_explicit():
    """Everything below depends on one canonical declaration; it has to be there to depend on."""
    assert UNRELEASED_BANNER.search(_banner_text()), (
        "BACKLOG.md has no explicit release-state banner saying the current version is neither "
        "tagged nor published. That banner is the canonical declaration the wording contracts "
        "below compare against, and without it they cannot be evaluated offline."
    )


def test_specs_do_not_call_an_unreleased_version_shipped():
    """A spec that says 'released' while the banner says 'not tagged' is one of them lying."""
    if not UNRELEASED_BANNER.search(_banner_text()):
        pytest.skip("the banner does not declare an unreleased state; nothing to contradict")

    offenders = []
    for path in SPEC_DOCS:
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
        "A spec states that the current version shipped or was released, while BACKLOG.md's "
        "banner says it is neither tagged nor published. Say the code is present on main "
        "instead:\n" + "\n".join(offenders)
    )


def _inventory_diagram_paths() -> list[str]:
    """Repository-relative diagram paths named in the review context's inventory."""
    text = _read(REVIEW_CONTEXT)
    section = text.split("## 2. Reading the architecture", 1)
    assert len(section) == 2, "the review context has no architecture-reading section to inventory"
    body = section[1].split("\n## ", 1)[0]

    paths = []
    for match in re.finditer(r"`(docs/[^`]+?\.(?:html|\{[^`]*\}))`", body):
        raw = match.group(1)
        brace = re.search(r"\{([^}]*)\}", raw)
        if brace:
            stem = raw[: brace.start()]
            paths.extend(f"{stem}{ext.strip()}" for ext in brace.group(1).split(","))
        else:
            paths.append(raw)
    return paths


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


# --------------------------------------------------------------------------------------------
# Diagram export provenance
# --------------------------------------------------------------------------------------------

ARCHITECTURE_HTML = REPO / "docs" / "assets" / "architecture.html"
ARCHITECTURE_SVG = REPO / "docs" / "assets" / "architecture.svg"


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
