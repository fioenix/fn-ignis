#!/usr/bin/env python3
"""Render a diagram's SVG to PNG at exactly twice its viewBox, using Playwright.

The repository keeps diagrams as HTML with inline SVG, exports the SVG standalone, and embeds a
PNG in documents that cannot show vectors. Without a way to regenerate the PNG, editing the
diagram leaves three files claiming to be the same picture and two of them telling the truth --
the duplicated-source failure this project has hit before.

Playwright is already a project dependency for the browser-tier connectors, so this needs no new
tooling. Chromium also resolves the webfonts the diagram asks for, which a plain SVG rasterizer
would substitute.

    python scripts/render_diagram_png.py docs/assets/architecture.svg
"""

import argparse
import re
import sys
from pathlib import Path

SCALE = 2  # documents embed the PNG at half size, so a 2x raster stays sharp


def _viewbox(svg_text: str) -> tuple[float, float]:
    match = re.search(r'viewBox="\s*([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)', svg_text)
    if not match:
        raise SystemExit("the SVG has no parseable viewBox, so the output size cannot be derived")
    return float(match.group(3)), float(match.group(4))


def render(svg_path: Path, png_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    svg_text = svg_path.read_text(encoding="utf-8")
    width, height = _viewbox(svg_text)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": int(width), "height": int(height)},
                device_scale_factor=SCALE,
            )
            page.goto(svg_path.resolve().as_uri())
            # The diagram pulls webfonts; rasterizing before they load swaps in a fallback face.
            page.wait_for_timeout(1500)
            page.screenshot(path=str(png_path), omit_background=False)
        finally:
            browser.close()

    print(f"{png_path}: {int(width) * SCALE} x {int(height) * SCALE}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("svg", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="defaults to the SVG path with .png")
    args = parser.parse_args(argv)

    if not args.svg.exists():
        raise SystemExit(f"no such file: {args.svg}")
    render(args.svg, args.out or args.svg.with_suffix(".png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
