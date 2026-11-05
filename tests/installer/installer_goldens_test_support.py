# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

import os

import subprocess

from pathlib import Path

from tests.installer.public_installer_helpers import (
    INSTALL_SHIM_PATH,
    branded_installer_glyphs as branded_installer_glyphs,
    load_installer,
    write_executable,
)


def _shim_bin(tmp_path: Path, *, os_name: str, brew: bool, curl: bool) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    write_executable(bin_dir / "uname", f"#!/bin/sh\nprintf {os_name}\n")
    if brew:
        # brew exits 0 but installs no uv, so the welcome capture stops at the
        # consent (the shim then fails to stderr — off the golden).
        write_executable(bin_dir / "brew", "#!/bin/sh\nexit 0\n")
    if curl:
        write_executable(bin_dir / "curl", "#!/bin/sh\nexit 0\n")
    return bin_dir


def _run_shim_capture(
    tmp_path: Path,
    *,
    force_color: str,
    os_name: str,
    brew: bool,
    curl: bool,
    answer: str,
    colorterm: str = "",
) -> str:
    bin_dir = _shim_bin(tmp_path, os_name=os_name, brew=brew, curl=curl)
    prompt_in = tmp_path / "prompt-in"
    prompt_in.write_text(answer, encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "COLUMNS": "80",
        "COLORTERM": colorterm,
        "TERM": "xterm-256color" if force_color == "1" else "dumb",
        "YOKE_INSTALL_BASE_URL": "https://api.upyoke.com",
        "YOKE_INSTALL_FORCE_COLOR": force_color,
        "YOKE_INSTALL_PROMPT_IN": str(prompt_in),
    }
    if force_color == "0":
        env["NO_COLOR"] = "1"
    result = subprocess.run(
        ["/bin/sh", str(INSTALL_SHIM_PATH)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    return result.stdout
