"""Select OS authority for an automatic Linux setup command."""

from __future__ import annotations

import os
import shutil
import sys

from yoke_cli import terminal_detached_process
from yoke_cli.config.onboard_terminal import wizard_terminal_owned


def command_authority(unavailable_reason: str) -> tuple[list[str], bool]:
    """Return a command prefix and whether the OS password prompt needs a TTY."""
    if os.geteuid() == 0:
        return [], False
    sudo = shutil.which("sudo")
    if sudo:
        try:
            result = terminal_detached_process.run(
                [sudo, "-n", "true"], capture_output=True, text=True
            )
        except OSError as exc:
            raise RuntimeError(
                f"{unavailable_reason} OS authority probe failed: {exc}"
            ) from exc
        if result.returncode == 0:
            return [sudo, "-n", "--"], False
        if wizard_terminal_owned():
            # A sudo password prompt would fight the wizard for the terminal.
            raise RuntimeError(
                f"{unavailable_reason} setup_wizard_sudo_refused: this step needs "
                "an interactive sudo password, which cannot be asked while the "
                "setup wizard owns the terminal. Run `yoke setup` again: its "
                "preparation step asks for the password before the wizard opens."
            )
        if sys.stdin.isatty() and sys.stderr.isatty():
            return [sudo, "--"], True
    raise RuntimeError(unavailable_reason)
