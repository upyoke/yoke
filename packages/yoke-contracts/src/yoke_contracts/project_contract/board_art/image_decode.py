#!/usr/bin/env python3
"""Image decode + alpha compositing for ``image_to_emoji_art``.

Two decode paths, both compositing over a background (white by default) so
transparency never reads as black:
  * ``load_grid``   — resize to gw x gh (area-average; the 'mean' downsample).
  * ``load_native`` — full-resolution pixels (for 'mode' / majority-vote).

Backend: Pillow if installed, else macOS ``sips`` -> 24/32-bit BMP -> a tiny
stdlib BMP reader.
"""
from __future__ import annotations

import os
import struct
import subprocess
import tempfile
from typing import List, Tuple

RGB = Tuple[int, int, int]


def composite(rgb: RGB, alpha: int, bg: RGB) -> RGB:
    if alpha >= 255:
        return rgb
    return tuple(  # type: ignore[return-value]
        (c * alpha + bc * (255 - alpha)) // 255 for c, bc in zip(rgb, bg)
    )


def image_dimensions(path: str) -> Tuple[int, int]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as im:
            return im.size
    except ImportError:
        out = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
            capture_output=True, text=True, check=True,
        ).stdout
        w = h = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("pixelWidth:"):
                w = int(line.split(":")[1])
            elif line.startswith("pixelHeight:"):
                h = int(line.split(":")[1])
        if w is None or h is None:
            raise SystemExit(f"could not read pixel dimensions of {path}")
        return w, h


def load_grid(path: str, gw: int, gh: int, *, bg: RGB) -> List[List[RGB]]:
    """Resize to gw x gh (area-average) and composite over ``bg``."""
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as im:
            im = im.convert("RGBA").resize((gw, gh))
            px = im.load()
            return [
                [composite(px[x, y][:3], px[x, y][3], bg) for x in range(gw)]
                for y in range(gh)
            ]
    except ImportError:
        return _decode_sips(path, bg=bg, resize=(gw, gh))


def load_native(path: str, *, bg: RGB) -> List[List[RGB]]:
    """Full-resolution pixels (composited over ``bg``), for mode downsampling."""
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as im:
            im = im.convert("RGBA")
            w, h = im.size
            px = im.load()
            return [
                [composite(px[x, y][:3], px[x, y][3], bg) for x in range(w)]
                for y in range(h)
            ]
    except ImportError:
        return _decode_sips(path, bg=bg, resize=None)


def _decode_sips(
    path: str, *, bg: RGB, resize: Tuple[int, int] | None
) -> List[List[RGB]]:
    fd, tmp = tempfile.mkstemp(suffix=".bmp")
    os.close(fd)
    try:
        cmd = ["sips"]
        if resize is not None:
            gw, gh = resize
            cmd += ["-z", str(gh), str(gw)]  # sips -z is height width
        cmd += ["-s", "format", "bmp", path, "--out", tmp]
        subprocess.run(cmd, capture_output=True, check=True)
        return _read_bmp(tmp, bg=bg)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _read_bmp(path: str, *, bg: RGB) -> List[List[RGB]]:
    """Minimal BMP reader: BI_RGB 24/32-bit, top-down or bottom-up.

    32-bit BGRA composites over ``bg`` so transparency renders as ``bg`` (white
    by default), never black."""
    data = open(path, "rb").read()
    if data[:2] != b"BM":
        raise SystemExit("sips did not produce a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    w = struct.unpack_from("<i", data, 18)[0]
    h_signed = struct.unpack_from("<i", data, 22)[0]
    bpp = struct.unpack_from("<H", data, 28)[0]
    if bpp not in (24, 32):
        raise SystemExit(f"unsupported BMP bit depth {bpp}")
    bottom_up = h_signed > 0
    h = abs(h_signed)
    row_bytes = ((bpp * w + 31) // 32) * 4  # padded to a 4-byte boundary
    nbytes = bpp // 8
    rows: List[List[RGB]] = []
    for ry in range(h):  # ry = display row (top -> bottom)
        src = (h - 1 - ry) if bottom_up else ry
        base = offset + src * row_bytes
        row: List[RGB] = []
        for x in range(w):
            p = base + x * nbytes
            b, g, r = data[p], data[p + 1], data[p + 2]
            if bpp == 32:
                row.append(composite((r, g, b), data[p + 3], bg))
            else:
                row.append((r, g, b))
        rows.append(row)
    return rows


__all__ = [
    "RGB", "composite", "image_dimensions", "load_grid", "load_native", "_read_bmp",
]
