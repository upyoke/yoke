"""Exact-byte golden gates for the installer cold-start shell surfaces.

Each ``APPROVED`` shell/install-log screen in the cold-start spec has one golden
under ``__goldens__/``. A test captures the real shim/installer output with a
forced, deterministic environment (color on/off, fixed ``COLUMNS``, a fake
``uname``/``brew``/``curl``), normalizes the dynamic tokens (version ->
``{{VERSION}}``, the real home -> ``~``, the failure reason -> ``{{REASON}}``),
and asserts the bytes match the committed golden. The operator blesses each
golden once — it IS their approved render — and the gate then enforces it on
every run, including EC2.

Regenerate after an approved copy change:

    YOKE_INSTALLER_GOLDEN_UPDATE=1 pytest tests/installer/test_installer_goldens.py

which rewrites the golden files from the live capture instead of asserting.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
from pathlib import Path

from public_installer_helpers import (
    INSTALL_SHIM_PATH,
    branded_installer_glyphs as branded_installer_glyphs,
    load_installer,
    write_executable,
)


GOLDENS_DIR = Path(__file__).resolve().parent / "__goldens__"
_UPDATE = os.environ.get("YOKE_INSTALLER_GOLDEN_UPDATE") == "1"
# A reported dev version like 0.1.1.dev16368+g8be5987c renders as
# "0.1.1 (dev g8be5987c)"; both the raw and the normalized display collapse to
# the {{VERSION}} placeholder so the golden never drifts with the build.
_VERSION_TOKENS = (
    "0.1.1 (dev g8be5987c)",
    "0.1.1.dev16368+g8be5987c",
)
_REASON_TEXT = "error: failed to resolve yoke-cli from the index"


def _assert_golden(name: str, captured: str) -> None:
    path = GOLDENS_DIR / name
    if _UPDATE:
        GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(captured, encoding="utf-8")
        return
    expected = path.read_text(encoding="utf-8")
    assert captured == expected, (
        f"{name} drifted from its blessed golden. Re-bless with "
        f"YOKE_INSTALLER_GOLDEN_UPDATE=1 if the change is approved.\n"
        f"--- captured ---\n{captured!r}\n--- golden ---\n{expected!r}"
    )


# --------------------------------------------------------------------------- #
# Shell-shim captures
# --------------------------------------------------------------------------- #


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
    force_brew: str,
    os_name: str,
    brew: bool,
    curl: bool,
    answer: str,
) -> str:
    bin_dir = _shim_bin(tmp_path, os_name=os_name, brew=brew, curl=curl)
    prompt_in = tmp_path / "prompt-in"
    prompt_in.write_text(answer, encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "COLUMNS": "80",
        "TERM": "xterm-256color" if force_color == "1" else "dumb",
        "YOKE_INSTALL_BASE_URL": "https://api.upyoke.com",
        "YOKE_INSTALL_FORCE_COLOR": force_color,
        "YOKE_INSTALL_FORCE_BREW": force_brew,
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


def _ansi_strip(line: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", line)


def _slice_from_offer(captured: str) -> str:
    # The declined-consent golden omits the figlet banner and the status line:
    # it starts at the install offer ("Install it with ...") and runs through
    # the decline screen. Find that offer line (ANSI-insensitive) and keep the
    # rest verbatim, preserving each line's color.
    lines = captured.splitlines(keepends=True)
    for index, line in enumerate(lines):
        # The offer line now carries the ☀ gutter ("☀ Install it with …"), so
        # match the offer text anywhere in the (ANSI-stripped) line.
        if "Install it with" in _ansi_strip(line):
            return "".join(lines[index:])
    raise AssertionError("offer line not found in declined-consent capture")


def test_shell_welcome(tmp_path: Path) -> None:
    captured = _run_shim_capture(
        tmp_path, force_color="1", force_brew="1",
        os_name="Darwin", brew=True, curl=False, answer="y\n",
    )
    _assert_golden("shell_welcome.txt", captured)


def test_shell_welcome_astral(tmp_path: Path) -> None:
    captured = _run_shim_capture(
        tmp_path, force_color="1", force_brew="0",
        os_name="Linux", brew=False, curl=True, answer="y\n",
    )
    _assert_golden("shell_welcome_astral.txt", captured)


def test_shell_welcome_plain(tmp_path: Path) -> None:
    captured = _run_shim_capture(
        tmp_path, force_color="0", force_brew="0",
        os_name="Linux", brew=False, curl=True, answer="y\n",
    )
    _assert_golden("shell_welcome_plain.txt", captured)


def test_shell_uv_declined(tmp_path: Path) -> None:
    captured = _run_shim_capture(
        tmp_path, force_color="1", force_brew="0",
        os_name="Linux", brew=False, curl=True, answer="n\n",
    )
    _assert_golden("shell_uv_declined.txt", _slice_from_offer(captured))


_EXIT_REMEDIATION = (
    "Skipped adding Yoke to your PATH.\n"
    "To add it later, run:\n"
    "  ~/.local/bin/yoke path fix\n"
    "\n"
    "Run yoke onboard to finish setting up your machine & projects.\n"
)


def test_exit_remediation() -> None:
    # The exit-remediation golden is the authored two-message screen the spec
    # approved. The shim emits the stop-before-finish line and install.py emits
    # the absolute-path skip-PATH remediation; both load-bearing fragments are
    # asserted present in the surfaces that produce them so the golden can never
    # drift away from live behavior.
    shim_text = INSTALL_SHIM_PATH.read_text(encoding="utf-8")
    assert (
        "Run yoke onboard to finish setting up your machine & projects."
        in shim_text
    )
    install_py = (
        INSTALL_SHIM_PATH.parent / "install.py"
    ).read_text(encoding="utf-8")
    assert "~/.local/bin/yoke path fix" in install_py
    _assert_golden("exit_remediation.txt", _EXIT_REMEDIATION)


# --------------------------------------------------------------------------- #
# install.py setup-log captures
# --------------------------------------------------------------------------- #


def _status_ok(version: str = "0.1.1.dev16368+g8be5987c"):
    payload = json.dumps(
        {
            "runtime": {
                "package_versions": {
                    "yoke-cli": version,
                    "yoke-contracts": version,
                    "yoke-harness": version,
                    "yoke-core": version,
                },
            },
            "connection": {"client_authority": "api"},
        }
    )
    return subprocess.CompletedProcess(["yoke", "status", "--json"], 0, payload, "")


class _Runner:
    """Fake command runner for install.py golden captures.

    Yields a fixed reported version for ``yoke --version`` and a configurable
    uv result (fresh install / already-installed / failure).
    """

    def __init__(self, *, uv_stdout: str, uv_rc: int = 0, uv_stderr: str = "") -> None:
        self.uv_stdout = uv_stdout
        self.uv_rc = uv_rc
        self.uv_stderr = uv_stderr

    def __call__(self, command):
        cmd = list(command)
        if cmd[:3] == ["uv", "tool", "install"]:
            return subprocess.CompletedProcess(
                cmd, self.uv_rc, self.uv_stdout, self.uv_stderr
            )
        if len(cmd) == 2 and cmd[0].endswith("/yoke") and cmd[1] == "--version":
            return subprocess.CompletedProcess(cmd, 0, "0.1.1.dev16368+g8be5987c\n", "")
        if len(cmd) == 2 and cmd[0].endswith("/yoke") and cmd[1] == "--help":
            return subprocess.CompletedProcess(cmd, 0, "help", "")
        if (
            len(cmd) == 3
            and cmd[0].endswith("/yoke")
            and cmd[1:] == ["status", "--json"]
        ):
            return _status_ok()
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _normalize(captured: str) -> str:
    for token in _VERSION_TOKENS:
        captured = captured.replace(token, "{{VERSION}}")
    captured = captured.replace(_REASON_TEXT, "{{REASON}}")
    home = os.path.expanduser("~")
    if home and home != "~":
        captured = captured.replace(home, "~")
    return captured


def _run_install(*, uv_stdout: str, uv_rc: int = 0, uv_stderr: str = "") -> str:
    installer_mod = load_installer("inst_golden")
    output = io.StringIO()
    options = installer_mod.InstallOptions(
        channel="stable",
        version="0.1.1.dev16368+g8be5987c",
        yes=False,
        dry_run=False,
        base_url="https://api.upyoke.com",
        no_onboard=True,
    )
    installer = installer_mod.Installer(
        options,
        runner=_Runner(uv_stdout=uv_stdout, uv_rc=uv_rc, uv_stderr=uv_stderr),
        which=lambda name: f"/usr/bin/{name}",
        stdout=output,
        color=False,
    )
    try:
        installer.run()
    except installer_mod.InstallError:
        pass
    return _normalize(output.getvalue())


def test_install_log() -> None:
    captured = _run_install(uv_stdout="+ yoke-cli==0.1.1")
    _assert_golden("install_log.txt", captured)


def test_install_log_already() -> None:
    captured = _run_install(uv_stdout="yoke-cli v0.1.1 is already installed")
    _assert_golden("install_log_already.txt", captured)


def test_install_log_failure() -> None:
    captured = _run_install(uv_stdout="", uv_rc=1, uv_stderr=_REASON_TEXT)
    _assert_golden("install_log_failure.txt", captured)
