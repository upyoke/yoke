"""Yoke's product UI stays byte-identical to its canonical brand source."""

from __future__ import annotations

from pathlib import Path

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
    ),
)
def test_universe_ui_brand_copy_matches_canonical_source(
    source: str,
    consumer: str,
):
    assert (UI / consumer).read_bytes() == (BRAND / source).read_bytes()
