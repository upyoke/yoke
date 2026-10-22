"""Installer color capability and default-foreground regression checks."""

from __future__ import annotations

import re
import subprocess

import pytest

from public_installer_helpers import INSTALL_SHIM_PATH, load_installer
from test_installer_goldens import _run_shim_capture


@pytest.mark.parametrize("colorterm", [None, "", "256color", "truecolor", "24bit"])
def test_python_colors_require_explicit_truecolor(monkeypatch, colorterm):
    if colorterm is None:
        monkeypatch.delenv("COLORTERM", raising=False)
    else:
        monkeypatch.setenv("COLORTERM", colorterm)
    monkeypatch.setenv("YOKE_INSTALL_FORCE_COLOR", "1")
    monkeypatch.setenv("YOKE_INSTALL_FORCE_PLAIN", "0")
    installer = load_installer()
    truecolor = colorterm in {"truecolor", "24bit"}
    for key in ("brand", "bright", "dim", "danger", "amber"):
        painted = installer._paint("instruction", key, enabled=True)
        assert ("38;2;" in painted) == truecolor
        assert installer._paint("instruction", key, enabled=False) == "instruction"
    # Setup log body text must follow the reset after the colored gutter.
    assert installer.Installer._gutter(type("TTY", (), {"isatty": lambda self: True})()).endswith(
        "\033[0m"
    )


@pytest.mark.parametrize("colorterm", ["", "256color", "truecolor", "24bit"])
def test_shell_welcome_colors(tmp_path, colorterm):
    captured = _run_shim_capture(
        tmp_path, force_color="1", os_name="Linux", brew=False, curl=True,
        answer="y\n", colorterm=colorterm,
    )
    assert ("38;2;" in captured) == (colorterm in {"truecolor", "24bit"})
    assert "Your operating system for software delivery" in captured


@pytest.mark.parametrize("colorterm", ["", "truecolor", "24bit"])
@pytest.mark.parametrize("force_color", ["0", "1"])
def test_completion_uses_default_body_foreground(colorterm, force_color):
    # Load the shim's actual function definitions without running installation.
    definitions = INSTALL_SHIM_PATH.read_text().split('while [ "$#" -gt 0 ]; do')[0]
    captured = subprocess.run(
        ["/bin/sh", "-c", definitions + "\nonboard_launched=1\n"
         "inherited_shell_has_bin_dir() { return 1; }\n"
         "print_path_guidance_after_onboard\n"],
        env={"PATH": "/usr/bin:/bin", "TERM": "xterm-256color",
             "COLORTERM": colorterm, "YOKE_INSTALL_FORCE_COLOR": force_color,
             "YOKE_INSTALL_FORCE_PLAIN": "0"},
        text=True, capture_output=True, check=True,
    ).stdout
    assert "open a new terminal" in captured
    assert "/yoke onboard" in captured
    assert "38;2;230;237;243" not in captured
    assert "\033[0m Next: bring your existing work into Yoke." in captured or (
        force_color == "0" and "Next: bring your existing work into Yoke." in captured
    )
    assert ("38;2;" in captured) == (
        force_color == "1" and colorterm in {"truecolor", "24bit"}
    )
    if force_color == "0":
        assert "\033[" not in captured
    elif colorterm not in {"truecolor", "24bit"}:
        codes = re.findall(r"\x1b\[([0-9;]+)m", captured)
        assert all(code in {"0", "1", "32", "33", "39"} for code in codes)
