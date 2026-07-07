"""macOS PATH helper for ``install_yoke_launcher``."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


MACOS_PATHS_FILE = Path("/etc/paths")
BREW_APPLE_SILICON_BIN = Path("/opt/homebrew/bin")


def _macos_path_fix_skip_reason() -> Optional[str]:
    """Return a reason when the macOS PATH fix is unnecessary."""
    if sys.platform != "darwin":
        return "non-macOS platform"
    if not BREW_APPLE_SILICON_BIN.is_dir():
        return f"{BREW_APPLE_SILICON_BIN} not present (non-Apple-Silicon or brew at a non-canonical prefix)"
    if not MACOS_PATHS_FILE.is_file():
        return f"{MACOS_PATHS_FILE} missing"
    try:
        lines = MACOS_PATHS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return f"cannot read {MACOS_PATHS_FILE}: {exc}"
    if lines and lines[0].strip() == str(BREW_APPLE_SILICON_BIN):
        return f"{BREW_APPLE_SILICON_BIN} already first in {MACOS_PATHS_FILE}"
    return None


def configure_macos_path_for_homebrew(
    *,
    paths_file: Optional[Path] = None,
    brew_bin: Optional[Path] = None,
    stream=None,
) -> bool:
    """Prepend ``/opt/homebrew/bin`` to ``/etc/paths`` so GUI apps see brew first."""
    out = stream if stream is not None else sys.stdout
    paths = paths_file if paths_file is not None else MACOS_PATHS_FILE
    brew = brew_bin if brew_bin is not None else BREW_APPLE_SILICON_BIN

    skip_reason = _macos_path_fix_skip_reason()
    if skip_reason is not None:
        return False

    out.write(
        "\nmacOS PATH fix:\n"
        f"  /etc/paths currently puts /usr/bin before {brew}, which means\n"
        f"  Claude.app/Codex.app subprocesses find Apple's Python 3.9 first\n"
        f"  instead of brew's Python (where Yoke's deps live).\n"
        f"  This step prepends {brew} to /etc/paths (with backup).\n"
        f"  You will be prompted for your sudo password.\n"
        f"  (Pass --skip-macos-path-fix on future runs to opt out.)\n\n"
    )

    timestamp = int(time.time())
    backup = f"{paths}.bak.{timestamp}"
    backup_rc = subprocess.call(["sudo", "cp", str(paths), backup])
    if backup_rc != 0:
        out.write(
            f"  sudo cp failed (rc={backup_rc}) — skipping macOS PATH fix.\n"
            f"  Apply manually later:\n"
            f"    sudo cp {paths} {paths}.bak.<ts>\n"
            f"    sudo sh -c 'printf \"{brew}\\n%s\\n\" \"$(cat {paths})\" > /tmp/p && mv /tmp/p {paths}'\n\n"
        )
        return False

    try:
        new_content = f"{brew}\n" + paths.read_text(encoding="utf-8")
    except OSError as exc:
        out.write(f"  cannot read {paths}: {exc} — skipping\n")
        return False
    write_proc = subprocess.run(
        ["sudo", "tee", str(paths)],
        input=new_content.encode("utf-8"),
        stdout=subprocess.DEVNULL,
    )
    if write_proc.returncode != 0:
        out.write(
            f"  sudo tee failed (rc={write_proc.returncode}) — /etc/paths unchanged\n"
            f"  Backup at {backup}\n\n"
        )
        return False

    try:
        ph_output = subprocess.check_output(
            ["/usr/libexec/path_helper", "-s"],
            text=True,
        )
        parts = ph_output.split('"', 2)
        if len(parts) >= 2:
            subprocess.check_call(["launchctl", "setenv", "PATH", parts[1]])
            out.write(
                f"  /etc/paths updated; backup at {backup}\n"
                f"  launchctl PATH refreshed — new GUI app launches will\n"
                f"  inherit it immediately. (Already-running apps keep their\n"
                f"  cached env until restarted.)\n\n"
            )
            return True
    except (subprocess.CalledProcessError, OSError) as exc:
        out.write(
            f"  /etc/paths updated; backup at {backup}\n"
            f"  launchctl refresh failed ({exc}) — reboot or logout/login\n"
            f"  to apply to GUI apps.\n\n"
        )
        return True

    return True
