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
a webfont import, both added here; the PNG is rasterized from that SVG and carries the SHA-256 of
that SVG in a `tEXt` chunk, which is what lets `--check` tell a current raster from a stale one
without demanding byte equality across platforms.

Playwright renders it, which is already a project dependency, and Chromium resolves the webfonts
the diagram asks for -- a plain rasterizer substitutes a fallback face and the export stops
matching what the page shows.

    python scripts/export_diagram.py docs/assets/architecture.html
    python scripts/export_diagram.py docs/assets/architecture.html --check
"""

import argparse
import hashlib
import re
import struct
import sys
import zlib
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

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The PNG is the only artifact a document embeds, and it is the one nobody can eyeball for
# staleness: a raster of last week's diagram looks exactly as finished as today's. Byte equality
# would be the obvious gate and is not available -- a different Chromium build on a different OS
# renders the same picture to different bytes. So the PNG carries the digest of the SVG it came
# from, in a tEXt chunk, and `--check` compares that against the SVG the HTML exports to now.
DIGEST_KEYWORD = b"ignis-source-sha256"


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


def source_digest(svg_text: str) -> str:
    """The identity of the canonical SVG, which is itself derived from the HTML."""
    return hashlib.sha256(svg_text.encode("utf-8")).hexdigest()


def _chunks(data: bytes):
    """(type, body, start, end) for every chunk, so a rewrite can splice on real boundaries."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG: the 8-byte signature is missing")
    position = len(PNG_SIGNATURE)
    while position + 8 <= len(data):
        (length,) = struct.unpack(">I", data[position: position + 4])
        chunk_type = data[position + 4: position + 8]
        end = position + 12 + length
        if end > len(data):
            raise ValueError(f"truncated PNG: {chunk_type!r} chunk runs past the end of the file")
        yield chunk_type, data[position + 8: position + 8 + length], position, end
        position = end


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Pixel width and height from IHDR, which is the first chunk of every valid PNG."""
    for chunk_type, body, _, _ in _chunks(data):
        if chunk_type == b"IHDR":
            return struct.unpack(">II", body[:8])
    raise ValueError("no IHDR chunk: the file carries a PNG signature but no header")


def png_source_digest(data: bytes) -> str | None:
    """The source digest stamped into the PNG, or None when it carries no stamp."""
    prefix = DIGEST_KEYWORD + b"\x00"
    for chunk_type, body, _, _ in _chunks(data):
        if chunk_type == b"tEXt" and body.startswith(prefix):
            return body[len(prefix):].decode("latin-1")
    return None


def _build_chunk(chunk_type: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + chunk_type + body + struct.pack(">I", crc)


def stamp_png(data: bytes, digest: str) -> bytes:
    """Return the PNG with `digest` recorded in a tEXt chunk, replacing any earlier stamp."""
    prefix = DIGEST_KEYWORD + b"\x00"
    out = bytearray(data[: len(PNG_SIGNATURE)])
    for chunk_type, body, start, end in _chunks(data):
        if chunk_type == b"tEXt" and body.startswith(prefix):
            continue  # drop the old stamp rather than leaving two
        out += data[start:end]
        if chunk_type == b"IHDR":
            out += _build_chunk(b"tEXt", prefix + digest.encode("ascii"))
    return bytes(out)


def with_ihdr_size(data: bytes, width: int, height: int) -> bytes:
    """Rewrite the declared dimensions. Used to prove the size check fails when it should."""
    out = bytearray(data[: len(PNG_SIGNATURE)])
    for chunk_type, body, start, end in _chunks(data):
        if chunk_type == b"IHDR":
            out += _build_chunk(b"IHDR", struct.pack(">II", width, height) + body[8:])
        else:
            out += data[start:end]
    return bytes(out)


def _render_png(
    svg_path: Path, png_path: Path, width: int, height: int, digest: str
) -> None:
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
    png_path.write_bytes(stamp_png(png_path.read_bytes(), digest))


def export(html_path: Path, *, render_png: bool = True) -> tuple[Path, Path | None]:
    svg_text = svg_from_html(html_path.read_text(encoding="utf-8"))
    width, height = viewbox_size(svg_text)

    svg_path = html_path.with_suffix(".svg")
    svg_path.write_text(svg_text, encoding="utf-8")

    png_path = html_path.with_suffix(".png")
    if render_png:
        _render_png(svg_path, png_path, width, height, source_digest(svg_text))
        print(f"{png_path}: {width * SCALE} x {height * SCALE}")
    else:
        png_path = None
    print(f"{svg_path}: viewBox {width} x {height}")
    return svg_path, png_path


def check(html_path: Path) -> int:
    """Report whether the committed exports are what this HTML produces, writing nothing.

    Both derived artifacts are checked. The SVG is compared byte for byte, because it is generated
    deterministically from the HTML. The PNG cannot be, so the three facts that survive a different
    renderer are: it is a PNG, its declared size is the viewBox at `SCALE`, and it carries the
    digest of the SVG it was rasterized from.
    """
    expected = svg_from_html(html_path.read_text(encoding="utf-8"))
    width, height = viewbox_size(expected)
    failures = []

    svg_path = html_path.with_suffix(".svg")
    if not svg_path.exists():
        failures.append(f"{svg_path}: missing")
    elif svg_path.read_text(encoding="utf-8") != expected:
        failures.append(f"{svg_path}: differs from the SVG exported by {html_path.name}")

    png_path = html_path.with_suffix(".png")
    if not png_path.exists():
        failures.append(f"{png_path}: missing")
    else:
        data = png_path.read_bytes()
        try:
            size = png_dimensions(data)
            stamped = png_source_digest(data)
        except ValueError as error:
            failures.append(f"{png_path}: {error}")
        else:
            if size != (width * SCALE, height * SCALE):
                failures.append(
                    f"{png_path}: {size[0]} x {size[1]}, but the viewBox at {SCALE}x is "
                    f"{width * SCALE} x {height * SCALE}"
                )
            wanted = source_digest(expected)
            if stamped is None:
                failures.append(
                    f"{png_path}: carries no source digest, so nothing ties it to {html_path.name}"
                )
            elif stamped != wanted:
                failures.append(
                    f"{png_path}: rendered from source {stamped[:12]}..., but {html_path.name} "
                    f"now exports {wanted[:12]}...; re-export it"
                )

    for failure in failures:
        print(failure)
    if failures:
        return 1
    print(f"{svg_path.name} and {png_path.name}: both match {html_path.name}")
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
