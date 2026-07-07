"""macOS Command Line Tools helpers for Git onboarding."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from yoke_cli.config.project_git_install_advice import IsRoot, Which


Runner = Callable[..., subprocess.CompletedProcess[str]]
MAC_CLT_GIT = Path("/Library/Developer/CommandLineTools/usr/bin/git")
MAC_CLT_ROOT = Path("/Library/Developer/CommandLineTools")
MAC_CLT_PLACEHOLDER = Path(
    "/tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress"
)
MAC_DEVELOPER_DIR_LINK = Path("/var/db/xcode_select_link")


def _which(which: Which | None) -> Which:
    return which or shutil.which


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def developer_git_ready(*, runner: Runner, timeout: int) -> bool:
    """Return true when Apple's developer Git path is usable."""

    if MAC_CLT_GIT.exists():
        return True
    if _developer_dir_git_ready(os.environ.get("DEVELOPER_DIR")):
        return True
    if MAC_DEVELOPER_DIR_LINK.is_symlink():
        return _developer_dir_git_ready(str(MAC_DEVELOPER_DIR_LINK.resolve(
            strict=False,
        )))
    return False


def _developer_dir_git_ready(developer_dir: str | None) -> bool:
    if not developer_dir:
        return False
    return (Path(developer_dir) / "usr/bin/git").exists()


def try_terminal_install(
    *,
    which: Which | None,
    is_root: IsRoot | None,
    runner: Runner,
    timeout: int,
) -> bool:
    """Try the terminal-first CLT install path before GUI handoff."""

    lookup = _which(which)
    privilege = _privilege_prefix(lookup, is_root or _is_root)
    if privilege is None:
        return False
    try:
        MAC_CLT_PLACEHOLDER.touch(exist_ok=True)
        listing = _run(
            ["/usr/sbin/softwareupdate", "-l"],
            runner=runner,
            timeout=timeout,
        )
        label = latest_command_line_tools_label(
            "\n".join((listing.stdout, listing.stderr)),
        )
        if listing.returncode != 0 or not label:
            return False
        if _run(
            [*privilege, "/usr/sbin/softwareupdate", "-i", label],
            runner=runner,
            timeout=timeout,
        ).returncode != 0:
            return False
        if _run(
            [*privilege, "/usr/bin/xcode-select", "--switch", str(MAC_CLT_ROOT)],
            runner=runner,
            timeout=timeout,
        ).returncode != 0:
            return False
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            MAC_CLT_PLACEHOLDER.unlink(missing_ok=True)
        except OSError:
            pass
    return True


def finalize_developer_tools(
    *,
    which: Which | None,
    is_root: IsRoot | None,
    runner: Runner,
    timeout: int,
) -> bool:
    """Select Command Line Tools after Apple's GUI installer completes."""

    if not MAC_CLT_ROOT.exists():
        return False
    privilege = _privilege_prefix(_which(which), is_root or _is_root)
    if privilege is None:
        return False
    try:
        return _run(
            [*privilege, "/usr/bin/xcode-select", "--switch", str(MAC_CLT_ROOT)],
            runner=runner,
            timeout=timeout,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _privilege_prefix(
    which: Which,
    is_root: IsRoot,
) -> tuple[str, ...] | None:
    if is_root():
        return ()
    if which("sudo"):
        return ("sudo", "-n")
    return None


def _run(
    args: list[str],
    *,
    runner: Runner,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return runner(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


def latest_command_line_tools_label(output: str) -> str | None:
    labels: list[str] = []
    previous = ""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "Command Line Tools" in line and "Label:" in line:
            labels.append(line.split("Label:", 1)[1].strip())
        elif "Command Line Tools" in line and previous.startswith("Label:"):
            labels.append(previous.split("Label:", 1)[1].strip())
        elif line.startswith("*") and "Command Line Tools" in line:
            labels.append(line.lstrip("*").strip())
        previous = line
    if not labels:
        return None
    return max(labels, key=_label_version_key)


def _label_version_key(label: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", label))


__all__ = [
    "developer_git_ready",
    "finalize_developer_tools",
    "latest_command_line_tools_label",
    "try_terminal_install",
]
