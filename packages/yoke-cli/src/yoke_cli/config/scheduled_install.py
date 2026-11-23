"""Install a release from the desktop session when SSH's guard blocks the installer.

OpenSSH sessions run under Windows Redirection Guard, so uv cannot follow its
Python link and the installer refuses with ``windows_untrusted_mount_point``.
The same installer command succeeds as a one-shot task in the signed-in user's
desktop session. The installer takes no setup lock (``--no-setup``), so a caller
holding the apply lock can wait for it.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Mapping

from yoke_contracts.machine_config import paths as machine_paths
from yoke_contracts.windows_one_shot_task import OneShotResult, run_one_shot

from yoke_cli.self_host import release_target

UNTRUSTED_MOUNT_POINT = "windows_untrusted_mount_point"
SCHEDULED_INSTALL_LIMIT_SECONDS = int(release_target.INSTALLER_RUN_TIMEOUT_SECONDS)
# What the installer reads that a desktop task's own environment may lack.
# Credentials in the caller's environment never reach the task's wrapper file.
_INSTALLER_ENV_NAMES = (
    "PATH",
    "UV_TOOL_BIN_DIR",
    "XDG_BIN_HOME",
    "YOKE_INSTALL_INHERITED_PATH",
    machine_paths.CONFIG_FILE_ENV,
    machine_paths.HOME_ENV,
)


def blocked_by_redirection_guard(
    completed: subprocess.CompletedProcess[str],
) -> bool:
    """Whether the installer refused with the Redirection Guard code."""
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    return UNTRUSTED_MOUNT_POINT in output


def installer_environment(env: Mapping[str, str] | None) -> dict[str, str]:
    source = os.environ if env is None else env
    return {name: source[name] for name in _INSTALLER_ENV_NAMES if name in source}


def run_installer(
    target: release_target.ReleaseTarget,
    installer_bytes: bytes,
    *,
    env: Mapping[str, str] | None = None,
) -> OneShotResult:
    """Run the same installer command as a one-shot desktop task."""
    with tempfile.TemporaryDirectory(prefix="yoke-installer-") as directory:
        path = Path(directory) / "install.py"
        path.write_bytes(installer_bytes)
        return run_one_shot(
            release_target.installer_command(target, str(path)),
            python=str(Path(sys.executable).with_name("pythonw.exe")),
            environment=installer_environment(env),
            limit_seconds=SCHEDULED_INSTALL_LIMIT_SECONDS,
        )


__all__ = [
    "SCHEDULED_INSTALL_LIMIT_SECONDS",
    "UNTRUSTED_MOUNT_POINT",
    "blocked_by_redirection_guard",
    "installer_environment",
    "run_installer",
]
