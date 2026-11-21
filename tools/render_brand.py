#!/usr/bin/env python3
"""Render the brand images of the integration from the SVG source.

Usage: python tools/render_brand.py

Needs `cairosvg` (and the cairo library) and `Pillow`, e.g. in a throw-away virtualenv:
    python -m venv /tmp/brand && /tmp/brand/bin/pip install cairosvg pillow
    /tmp/brand/bin/python tools/render_brand.py

Writes icon.png (256x256) and icon@2x.png (512x512) to custom_components/myindygo/brand/, as
specified by https://github.com/home-assistant/brands#image-specification: square PNG,
transparent background, trimmed (no empty border), losslessly optimised. There is no logo: the
icon is used as the logo fallback.
"""

from __future__ import annotations

import io
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "icon.svg"
TARGET = ROOT / "custom_components" / "myindygo" / "brand"
SIZES = {"icon.png": 256, "icon@2x.png": 512}


def render(size: int) -> Image.Image:
    """Rasterise the SVG at the given size and check that it is trimmed."""
    png = cairosvg.svg2png(url=str(SOURCE), output_width=size, output_height=size)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox != (0, 0, size, size):
        raise SystemExit(f"{SOURCE.name} is not trimmed at {size}px: content box {bbox}")
    return image


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        path = TARGET / name
        # no metadata, maximum lossless zlib compression
        render(size).save(path, format="PNG", optimize=True)
        print(f"{path.relative_to(ROOT)}: {size}x{size}, {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
