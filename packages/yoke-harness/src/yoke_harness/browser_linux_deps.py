"""Linux OS dependency helpers for the product Browser QA runtime."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


AMAZON_LINUX_CHROMIUM_DEPS = (
    "alsa-lib",
    "at-spi2-atk",
    "at-spi2-core",
    "atk",
    "libX11",
    "libXcomposite",
    "libXdamage",
    "libXext",
    "libXfixes",
    "libXrandr",
    "libxcb",
    "libxkbcommon",
    "mesa-libgbm",
)


def is_amazon_linux() -> bool:
    return sys.platform.startswith("linux") and _os_release_id() == "amzn"


def amazon_linux_chromium_deps_command() -> list[str]:
    if not is_amazon_linux() or _packages_installed():
        return []
    manager = shutil.which("dnf") or shutil.which("yum")
    if not manager:
        raise RuntimeError("Amazon Linux Chromium dependencies require dnf or yum")
    prefix = [] if getattr(os, "geteuid", lambda: 1)() == 0 else ["sudo"]
    if prefix and not shutil.which("sudo"):
        raise RuntimeError("Amazon Linux Chromium dependencies require sudo")
    return [*prefix, manager, "install", "-y", *AMAZON_LINUX_CHROMIUM_DEPS]


def _packages_installed() -> bool:
    rpm = shutil.which("rpm")
    if not rpm:
        return False
    result = subprocess.run(
        [rpm, "-q", *AMAZON_LINUX_CHROMIUM_DEPS],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _os_release_id() -> str:
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        if line.startswith("ID="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


__all__ = [
    "AMAZON_LINUX_CHROMIUM_DEPS",
    "amazon_linux_chromium_deps_command",
    "is_amazon_linux",
]
