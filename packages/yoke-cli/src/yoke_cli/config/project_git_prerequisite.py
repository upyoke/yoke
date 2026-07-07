"""Git prerequisite detection and user-facing install guidance."""

from __future__ import annotations

from dataclasses import replace
import shutil
import subprocess
import sys
from typing import Callable, Sequence

from yoke_cli.config import project_git_install_advice as install_advice_impl
from yoke_cli.config import project_git_macos_tools
from yoke_cli.config.project_git_install_advice import (
    GitInstallAdvice,
    IsRoot,
    Which,
)


class MissingGitError(RuntimeError):
    """Raised when a project-onboarding path needs git but it is unavailable."""


class GitInstallError(RuntimeError):
    """Raised when Yoke cannot install git automatically."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _which(which: Which | None) -> Which:
    return which or shutil.which


def install_advice(
    *,
    platform_name: str | None = None,
    which: Which | None = None,
    is_root: IsRoot | None = None,
) -> GitInstallAdvice:
    return install_advice_impl.install_advice(
        platform_name=platform_name,
        which=_which(which),
        is_root=is_root,
    )


def install_action_label(advice: GitInstallAdvice | None = None) -> str:
    return install_advice_impl.install_action_label(advice or install_advice())


def install_action_hint(advice: GitInstallAdvice | None = None) -> str:
    return install_advice_impl.install_action_hint(advice or install_advice())


def install_handoff_detail_lines(
    advice: GitInstallAdvice | None = None,
) -> list[str]:
    return install_advice_impl.install_handoff_detail_lines(
        advice or install_advice(),
    )


def install_progress_message(advice: GitInstallAdvice) -> str:
    return install_advice_impl.install_progress_message(advice)


def install_progress_detail_lines(advice: GitInstallAdvice) -> list[str]:
    return install_advice_impl.install_progress_detail_lines(advice)


def finalize_git_install(
    *,
    platform_name: str | None = None,
    which: Which | None = None,
    is_root: IsRoot | None = None,
    runner: Runner = subprocess.run,
    timeout: int = 120,
) -> None:
    if (platform_name or sys.platform).lower() != "darwin":
        return
    project_git_macos_tools.finalize_developer_tools(
        which=_which(which),
        is_root=is_root,
        runner=runner,
        timeout=timeout,
    )


def git_available(
    *,
    platform_name: str | None = None,
    which: Which | None = None,
    runner: Runner = subprocess.run,
    timeout: int = 10,
) -> bool:
    git_path = _which(which)("git")
    if git_path is None:
        return False
    if (platform_name or sys.platform).lower() == "darwin" and git_path == "/usr/bin/git":
        return project_git_macos_tools.developer_git_ready(
            runner=runner,
            timeout=timeout,
        )
    try:
        result = runner(
            [git_path, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def required_summary() -> str:
    return "Git is needed to create, clone, import, or inspect a project checkout."


def missing_git_detail_lines(
    *,
    platform_name: str | None = None,
    which: Which | None = None,
    is_root: IsRoot | None = None,
) -> list[str]:
    advice = install_advice(
        platform_name=platform_name,
        which=which,
        is_root=is_root,
    )
    lines: list[str] = []
    if advice.command and advice.run_steps and advice.requires_user_completion:
        lines.append(
            "Choose Install Apple Tools. Yoke tries the terminal installer "
            "first; if Apple opens a Command Line Tools installer, finish it "
            "and choose Try again."
        )
    elif advice.command and advice.run_steps:
        lines.append(f"Choose Install Git, or run manually: {advice.command}")
    elif advice.command:
        lines.append(f"Run this manually, then choose Try again: {advice.command}")
    lines.append(advice.note)
    return lines


def missing_git_message(
    *,
    platform_name: str | None = None,
    which: Which | None = None,
    is_root: IsRoot | None = None,
) -> str:
    details = " ".join(missing_git_detail_lines(
        platform_name=platform_name,
        which=which,
        is_root=is_root,
    ))
    return f"git is required for project setup but was not found on PATH. {details}"


def require_git_available(
    *,
    platform_name: str | None = None,
    which: Which | None = None,
    is_root: IsRoot | None = None,
) -> None:
    if git_available(platform_name=platform_name, which=which):
        return
    raise MissingGitError(missing_git_message(
        platform_name=platform_name,
        which=which,
        is_root=is_root,
    ))


def install_git(
    *,
    platform_name: str | None = None,
    which: Which | None = None,
    is_root: IsRoot | None = None,
    runner: Runner = subprocess.run,
    probe_runner: Runner = subprocess.run,
    timeout: int = 900,
) -> GitInstallAdvice:
    """Install git with the detected platform command, then verify it exists."""

    advice = install_advice(
        platform_name=platform_name,
        which=which,
        is_root=is_root,
    )
    if not advice.run_steps:
        raise GitInstallError(
            "Yoke does not know how to install git automatically on "
            f"{advice.platform_label}. {advice.note}"
        )
    if advice.requires_user_completion:
        if project_git_macos_tools.try_terminal_install(
            which=_which(which),
            is_root=is_root,
            runner=runner,
            timeout=timeout,
        ) and git_available(
            platform_name=platform_name,
            which=which,
            runner=probe_runner,
        ):
            return replace(advice, requires_user_completion=False)
        for step in advice.run_steps:
            _run_install_step(step, runner=runner, timeout=timeout)
        return advice
    last_result: subprocess.CompletedProcess[str] | None = None
    for step in advice.run_steps:
        last_result = _run_install_step(step, runner=runner, timeout=timeout)
    if git_available(
        platform_name=platform_name,
        which=which,
        runner=probe_runner,
    ):
        return advice
    detail = _command_failure_detail(last_result) if last_result else ""
    raise GitInstallError(
        "The git install command finished, but git is still not on PATH. "
        "Open a new shell if the installer changed PATH, or run this manually: "
        f"{advice.command}."
        + (f" Last output: {detail}" if detail else "")
    )


def _run_install_step(
    step: Sequence[str],
    *,
    runner: Runner,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            list(step),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitInstallError(
            f"Could not run {' '.join(step)} because {step[0]} was not found."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitInstallError(
            f"Timed out while running {' '.join(step)}."
        ) from exc
    if result.returncode != 0:
        detail = _command_failure_detail(result)
        raise GitInstallError(
            f"{' '.join(step)} exited with {result.returncode}."
            + (f" {detail}" if detail else "")
        )
    return result


def _command_failure_detail(
    result: subprocess.CompletedProcess[str] | None,
) -> str:
    if result is None:
        return ""
    return (result.stderr or result.stdout or "").strip()


__all__ = [
    "GitInstallAdvice",
    "GitInstallError",
    "MissingGitError",
    "finalize_git_install",
    "git_available",
    "install_git",
    "install_advice",
    "install_action_hint",
    "install_action_label",
    "install_handoff_detail_lines",
    "install_progress_detail_lines",
    "install_progress_message",
    "missing_git_detail_lines",
    "missing_git_message",
    "require_git_available",
    "required_summary",
]
