#!/usr/bin/env python3
"""Export a diagram from its HTML source to a standalone SVG and a PNG.

The declared convention is that a diagram is authored as HTML with inline SVG and exported from
there. The previous exporter took an SVG and produced a PNG, so it never opened the HTML and
enforced nothing: the HTML body and the standalone SVG were two hand-edited copies that happened
to agree. That is the parallel-source failure the convention exists to prevent, reintroduced by
the tool meant to serve it.

The direction is now explicit and executable:

    HTML with inline SVG  ->  standalone SVG  ->  PNG

Only the HTML is edited. The SVG is generated from it and differs only by an XML declaration and
a webfont import, both added here; the PNG is rasterized from that SVG.

Playwright renders it, which is already a project dependency, and Chromium resolves the webfonts
the diagram asks for -- a plain rasterizer substitutes a fallback face and the export stops
matching what the page shows.

    python scripts/export_diagram.py docs/assets/architecture.html
    python scripts/export_diagram.py docs/assets/architecture.html --check
"""

import argparse
import re
import sys
from pathlib import Path

# Documents embed the PNG at half size, so a 2x raster stays sharp.
SCALE = 2

# The standalone file is loaded outside the page that imported the fonts, so it carries its own
# import. Kept as one literal because the generated SVG is compared byte for byte against the
# committed one; reformatting this is a diff in every exported diagram.
FONT_IMPORT_DEFS = (
    "  <defs>\n"
    "    <style>@import url('https://fonts.googleapis.com/css2?family=Anton&amp;"
    "family=Space+Grotesk:wght@400;500;600;700&amp;"
    "family=JetBrains+Mono:wght@400;500;700&amp;display=swap');</style>\n"
    "  </defs>\n"
)
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'


def extract_inline_svg(html_text: str) -> str:
    """The one inline SVG in the document.

    Fails closed on zero or several. Picking the first of many would publish whichever element
    happened to come first in the file, which is exactly the kind of quiet wrong answer a
    provenance tool must not give.
    """
    matches = re.findall(r"<svg[\s\S]*?</svg>", html_text)
    if not matches:
        raise ValueError("no inline <svg> found in the HTML source")
    if len(matches) > 1:
        raise ValueError(
            f"{len(matches)} inline <svg> elements found; the intended one is ambiguous"
        )
    return matches[0]


def viewbox_size(svg_markup: str) -> tuple[int, int]:
    """Width and height from the viewBox, which is the only declared size the diagram has."""
    match = re.search(
        r'viewBox="\s*[\d.+-]+\s+[\d.+-]+\s+([\d.+-]+)\s+([\d.+-]+)', svg_markup
    )
    if not match:
        raise ValueError("the SVG has no parseable viewBox, so its size cannot be derived")
    return int(float(match.group(1))), int(float(match.group(2)))


def svg_from_html(html_text: str) -> str:
    """The standalone SVG this HTML exports to."""
    svg = extract_inline_svg(html_text)
    viewbox_size(svg)  # fail here rather than during rasterization

    # Immediately before the diagram's own <defs>, which puts it after <title> and <desc> so
    # assistive technology reads those first, and keeps the two defs blocks adjacent.
    insert_at = svg.find("  <defs>")
    if insert_at == -1:
        # No defs of its own: fall back to just after the description, or the opening tag.
        anchor = svg.find("</desc>")
        insert_at = svg.find("\n", anchor) + 1 if anchor != -1 else svg.find(">") + 1
    # Trailing newline: this is a text file, and git treats a missing one as a change.
    return XML_DECLARATION + svg[:insert_at] + FONT_IMPORT_DEFS + svg[insert_at:] + "\n"


def _render_png(svg_path: Path, png_path: Path, width: int, height: int) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=SCALE
            )
            page.goto(svg_path.resolve().as_uri())
            # Rasterizing before the webfonts load swaps in a fallback face.
            page.wait_for_timeout(1500)
            page.screenshot(path=str(png_path), omit_background=False)
        finally:
            browser.close()


def export(html_path: Path, *, render_png: bool = True) -> tuple[Path, Path | None]:
    svg_text = svg_from_html(html_path.read_text(encoding="utf-8"))
    width, height = viewbox_size(svg_text)

    svg_path = html_path.with_suffix(".svg")
    svg_path.write_text(svg_text, encoding="utf-8")

    png_path = html_path.with_suffix(".png")
    if render_png:
        _render_png(svg_path, png_path, width, height)
        print(f"{png_path}: {width * SCALE} x {height * SCALE}")
    else:
        png_path = None
    print(f"{svg_path}: viewBox {width} x {height}")
    return svg_path, png_path


def check(html_path: Path) -> int:
    """Report whether the committed SVG is what this HTML exports to, without writing anything."""
    expected = svg_from_html(html_path.read_text(encoding="utf-8"))
    svg_path = html_path.with_suffix(".svg")
    if not svg_path.exists():
        print(f"{svg_path}: missing")
        return 1
    if svg_path.read_text(encoding="utf-8") != expected:
        print(f"{svg_path}: differs from the SVG exported by {html_path.name}")
        return 1
    print(f"{svg_path}: matches {html_path.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("html", type=Path, help="the diagram's HTML source, which owns the SVG")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed SVG matches the HTML without writing files",
    )
    parser.add_argument("--no-png", action="store_true", help="write the SVG only")
    args = parser.parse_args(argv)

    if not args.html.exists():
        raise SystemExit(f"no such file: {args.html}")
    if args.check:
        return check(args.html)
    export(args.html, render_png=not args.no_png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
