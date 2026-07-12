"""Descriptor-anchored Git clone runner for onboarding targets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Any, Callable, Sequence

from yoke_cli.config import onboard_checkout_ownership
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.project_git_diagnostics import scrub_git_diagnostic
from yoke_cli.config.project_git_environment import isolated_network_git_env
from yoke_cli.config.project_git_process import NetworkGitBoundaryError


@dataclass
class CloneTargetClaim:
    """Exact inode created by this clone flow across authentication attempts."""

    identity: tuple[int, int] | None = None


def run_clone(
    *,
    parent: Path,
    name: str,
    clean_url: str,
    config: tuple[str, ...],
    token: str | None,
    runner: Callable[..., Any],
    error_type: type[RuntimeError],
    target_claim: CloneTargetClaim | None = None,
) -> Any:
    """Clone into an opened directory inode; never pathname-delete on failure."""

    project_git_prerequisite.require_git_available()
    target = parent / name
    created = False
    try:
        target.lstat()
    except FileNotFoundError:
        try:
            target.mkdir(mode=0o700)
            created = True
        except OSError as exc:
            raise error_type("clone target could not be created safely") from exc
    descriptor = _open_empty_target(target, error_type=error_type)
    try:
        identity = _identity(descriptor)
        if created and target_claim is not None:
            target_claim.identity = identity
        elif (
            target_claim is not None
            and target_claim.identity is not None
            and target_claim.identity != identity
        ):
            raise error_type(
                "clone target identity changed between attempts; it was left untouched"
            )
        command = ["git", "clone"]
        if token:
            command.append("--no-checkout")
        command.extend(("--", clean_url, "."))
        allowed = "https" if clean_url.startswith("https://") else None
        try:
            with isolated_network_git_env(config, allow_protocols=allowed) as env:
                result = runner(
                    command,
                    env=env,
                    cwd_fd=descriptor,
                    pass_fds=(descriptor,),
                )
        except NetworkGitBoundaryError as exc:
            _require_same_target(target, identity, error_type=error_type)
            raise error_type(scrub_git_diagnostic(exc, token=token)) from exc
        _require_same_target(target, identity, error_type=error_type)
        owned = created or bool(
            target_claim is not None and target_claim.identity == identity
        )
        if result.returncode == 0 and owned:
            onboard_checkout_ownership.mark_created_fd(descriptor)
        return result
    finally:
        os.close(descriptor)


def _open_empty_target(
    target: Path, *, error_type: type[RuntimeError],
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0,
    )
    try:
        descriptor = os.open(target, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or os.listdir(descriptor):
            raise error_type(
                "clone target is no longer an empty directory; it was left untouched"
            )
        return descriptor
    except error_type:
        try:
            os.close(descriptor)
        except (OSError, UnboundLocalError):
            pass
        raise
    except OSError as exc:
        raise error_type(
            "clone target could not be opened safely; it was left untouched"
        ) from exc


def _identity(descriptor: int) -> tuple[int, int]:
    info = os.fstat(descriptor)
    return info.st_dev, info.st_ino


def _require_same_target(
    target: Path,
    expected: Sequence[int],
    *,
    error_type: type[RuntimeError],
) -> None:
    try:
        current = target.lstat()
    except OSError as exc:
        raise error_type(
            "clone target path changed during Git; partial data was left untouched"
        ) from exc
    if (
        (current.st_dev, current.st_ino) != tuple(expected)
        or not stat.S_ISDIR(current.st_mode)
        or target.is_symlink()
    ):
        raise error_type(
            "clone target path changed during Git; partial data was left untouched"
        )


__all__ = ["CloneTargetClaim", "run_clone"]
