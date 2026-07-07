"""Platform-specific Git install commands for project onboarding."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GitInstallAdvice:
    """Best-effort, platform-aware guidance for installing git."""

    platform_label: str
    command: str | None
    note: str
    run_steps: tuple[tuple[str, ...], ...] = ()
    requires_user_completion: bool = False


@dataclass(frozen=True)
class _CommandPlan:
    command: str
    run_steps: tuple[tuple[str, ...], ...]
    needs_manual_privilege: bool = False


Which = Callable[[str], str | None]
IsRoot = Callable[[], bool]


def _which(which: Which | None) -> Which:
    return which or shutil.which


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _sudo_plan(
    *args: str,
    which: Which,
    is_root: IsRoot,
) -> _CommandPlan:
    if is_root():
        return _CommandPlan(" ".join(args), (args,))
    if which("sudo"):
        return _CommandPlan(
            " ".join(("sudo", *args)),
            (("sudo", "-n", *args),),
        )
    return _CommandPlan(" ".join(args), (), needs_manual_privilege=True)


def _doas_plan(
    *args: str,
    which: Which,
    is_root: IsRoot,
) -> _CommandPlan:
    if is_root():
        return _CommandPlan(" ".join(args), (args,))
    if which("doas"):
        return _CommandPlan(
            " ".join(("doas", *args)),
            (("doas", "-n", *args),),
        )
    return _CommandPlan(" ".join(args), (), needs_manual_privilege=True)


def _note_with_privilege(note: str, *plans: _CommandPlan) -> str:
    if any(plan.needs_manual_privilege for plan in plans):
        return f"{note} Run it as root or ask an administrator."
    return note


def install_advice(
    *,
    platform_name: str | None = None,
    which: Which | None = None,
    is_root: IsRoot | None = None,
) -> GitInstallAdvice:
    """Return the best install command for this host."""

    name = (platform_name or sys.platform).lower()
    lookup = _which(which)
    root_check = is_root or _is_root
    if name == "darwin":
        if lookup("brew"):
            return GitInstallAdvice(
                "macOS",
                "brew install git",
                "Homebrew is available on this Mac.",
                (("brew", "install", "git"),),
            )
        return GitInstallAdvice(
            "macOS",
            "xcode-select --install",
            "Apple's Command Line Tools include git; macOS may open an "
            "installer before returning here.",
            (("/usr/bin/xcode-select", "--install"),),
            requires_user_completion=True,
        )

    if name.startswith("win") or name in {"cygwin", "msys"}:
        return GitInstallAdvice(
            "Windows",
            None,
            "Native Windows onboarding is not supported yet. Use WSL/Linux or "
            "macOS; inside WSL, install git with that distro's package manager.",
        )

    if "linux" in name:
        dnf = _sudo_plan(
            "dnf", "install", "-y", "git",
            which=lookup, is_root=root_check,
        )
        yum = _sudo_plan(
            "yum", "install", "-y", "git",
            which=lookup, is_root=root_check,
        )
        apt_update = _sudo_plan(
            "apt-get", "update",
            which=lookup, is_root=root_check,
        )
        apt_install = _sudo_plan(
            "apt-get", "install", "-y", "git",
            which=lookup, is_root=root_check,
        )
        apk = _sudo_plan("apk", "add", "git", which=lookup, is_root=root_check)
        zypper = _sudo_plan(
            "zypper", "install", "-y", "git",
            which=lookup, is_root=root_check,
        )
        pacman = _sudo_plan(
            "pacman", "-Sy", "--noconfirm", "git",
            which=lookup, is_root=root_check,
        )
        managers = (
            ("dnf", dnf.command, dnf.run_steps,
             _note_with_privilege(
                 "Amazon Linux, Fedora, RHEL, and compatible distributions.",
                 dnf,
             )),
            ("yum", yum.command, yum.run_steps,
             _note_with_privilege(
                 "Older Amazon Linux, RHEL, CentOS, and compatible distributions.",
                 yum,
             )),
            ("apt-get", f"{apt_update.command} && {apt_install.command}",
             apt_update.run_steps + apt_install.run_steps,
             _note_with_privilege(
                 "Debian, Ubuntu, and compatible distributions.",
                 apt_update, apt_install,
             )),
            ("apk", apk.command, apk.run_steps,
             _note_with_privilege("Alpine Linux.", apk)),
            ("zypper", zypper.command, zypper.run_steps,
             _note_with_privilege("openSUSE and SLES.", zypper)),
            ("pacman", pacman.command, pacman.run_steps,
             _note_with_privilege("Arch Linux.", pacman)),
        )
        for binary, command, run_steps, note in managers:
            if lookup(binary):
                return GitInstallAdvice("Linux", command, note, run_steps)
        return GitInstallAdvice(
            "Linux",
            None,
            "Install the package named git with this distribution's package "
            "manager, then choose Try again.",
        )

    if "freebsd" in name:
        pkg = _sudo_plan(
            "pkg", "install", "-y", "git",
            which=lookup, is_root=root_check,
        )
        return GitInstallAdvice(
            "FreeBSD",
            pkg.command,
            _note_with_privilege("FreeBSD.", pkg),
            pkg.run_steps,
        )
    if "openbsd" in name:
        pkg_add = _doas_plan("pkg_add", "git", which=lookup, is_root=root_check)
        return GitInstallAdvice(
            "OpenBSD",
            pkg_add.command,
            _note_with_privilege("OpenBSD.", pkg_add),
            pkg_add.run_steps,
        )

    return GitInstallAdvice(
        "this operating system",
        None,
        "Install the package named git with this system's package manager, then "
        "choose Try again.",
    )


def install_action_label(advice: GitInstallAdvice | None = None) -> str:
    advice = advice or install_advice()
    if advice.requires_user_completion:
        return "Install Apple Tools"
    return "Install Git"


def install_action_hint(advice: GitInstallAdvice | None = None) -> str:
    advice = advice or install_advice()
    if advice.requires_user_completion:
        return "adds git"
    return "run installer"


def install_progress_message(advice: GitInstallAdvice) -> str:
    if advice.requires_user_completion:
        return "Trying macOS softwareupdate; Apple may open an installer."
    return f"Running: {advice.command}"


def install_progress_detail_lines(advice: GitInstallAdvice) -> list[str]:
    if advice.requires_user_completion:
        return [
            "Yoke tries Apple's terminal installer first.",
            "If a Command Line Tools installer opens, finish it and return here.",
        ]
    return ["This can take a minute."]


def install_handoff_detail_lines(
    advice: GitInstallAdvice | None = None,
) -> list[str]:
    advice = advice or install_advice()
    return [
        f"Yoke ran: {advice.command}.",
        "Complete the Command Line Tools installer outside this terminal.",
        "When it finishes, return here and choose Check again.",
    ]


__all__ = [
    "GitInstallAdvice",
    "IsRoot",
    "Which",
    "install_action_hint",
    "install_action_label",
    "install_advice",
    "install_handoff_detail_lines",
    "install_progress_detail_lines",
    "install_progress_message",
]
