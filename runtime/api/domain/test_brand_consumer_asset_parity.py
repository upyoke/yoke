"""Yoke's product UI stays byte-identical to its canonical brand source."""

from __future__ import annotations

import base64
from pathlib import Path
import re
import struct

import pytest


ROOT = Path(__file__).resolve().parents[3]
BRAND = ROOT / "brand"
UI = ROOT / "packages" / "yoke-core" / "src" / "yoke_core" / "ui" / "static"
BRAND_FILES = (
    Path("theme.css"),
    Path("shell.css"),
    Path("logo/yoke.svg"),
    Path("logo/yoke-wordmark.svg"),
    Path("favicon/favicon.svg"),
    Path("favicon/favicon.ico"),
    Path("favicon/apple-touch-icon.png"),
    Path("favicon/icon-192.png"),
    Path("favicon/icon-512.png"),
    Path("favicon/og-image.svg"),
    Path("favicon/og-image.png"),
    Path("favicon/site.webmanifest"),
)


@pytest.mark.parametrize(
    ("source", "consumer"),
    (
        ("theme.css", "theme.css"),
        ("shell.css", "shell.css"),
        ("logo/yoke.svg", "yoke.svg"),
        ("logo/yoke-wordmark.svg", "yoke-wordmark.svg"),
        ("favicon/favicon.svg", "favicon.svg"),
        ("favicon/favicon.ico", "favicon.ico"),
        ("favicon/apple-touch-icon.png", "apple-touch-icon.png"),
        ("favicon/icon-192.png", "icon-192.png"),
        ("favicon/icon-512.png", "icon-512.png"),
        ("favicon/og-image.svg", "og-image.svg"),
        ("favicon/og-image.png", "og-image.png"),
        ("favicon/site.webmanifest", "site.webmanifest"),
    ),
)
def test_universe_ui_brand_copy_matches_canonical_source(
    source: str,
    consumer: str,
):
    assert (UI / consumer).read_bytes() == (BRAND / source).read_bytes()


def test_documentation_embeds_the_same_self_hosted_fonts():
    # The installed documentation bundle carries text, so its WOFF2 data lives
    # in CSS while the app serves font files through its closed asset roster.
    names = re.findall(r"url\('\./([^']+\.woff2)'\)", (UI / "fonts.css").read_text())
    embedded = re.findall(
        r"url\('data:font/woff2;base64,([^']+)'\)",
        (ROOT / "docs/public/assets/fonts.css").read_text(),
    )
    assert names
    assert len(names) == len(embedded)
    for name, encoded in zip(names, embedded, strict=True):
        assert base64.b64decode(encoded, validate=True) == (UI / name).read_bytes()


@pytest.mark.parametrize(
    ("name", "size"),
    [("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)],
)
def test_app_icon_dimensions_match_their_declared_sizes(name: str, size: int):
    data = (BRAND / "favicon" / name).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (size, size)
