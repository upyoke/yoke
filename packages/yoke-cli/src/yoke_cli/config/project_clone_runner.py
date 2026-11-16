"""Identity-checked Git clone runner for onboarding targets.

The clone runs with the target directory as its working directory. The
directory must be empty and a real directory (not a symlink, junction or
other reparse point) before Git starts, and must still be the same
directory afterwards; any change is refused and nothing is deleted by
pathname. The same checks hold on POSIX and Windows, which has no
descriptor-relative working directory to hand a child process.
"""

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
    """Exact directory identity created by this clone flow across authentication attempts."""

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
    """Clone into a checked empty directory; never pathname-delete on failure."""

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
    identity = _empty_target_identity(target, error_type=error_type)
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
            result = runner(command, env=env, cwd=target)
    except NetworkGitBoundaryError as exc:
        _require_same_target(target, identity, error_type=error_type)
        raise error_type(scrub_git_diagnostic(exc, token=token)) from exc
    _require_same_target(target, identity, error_type=error_type)
    owned = created or bool(
        target_claim is not None and target_claim.identity == identity
    )
    if result.returncode == 0 and owned:
        onboard_checkout_ownership.mark_created(target)
    return result


def _empty_target_identity(
    target: Path, *, error_type: type[RuntimeError],
) -> tuple[int, int]:
    try:
        info = target.lstat()
        if _is_plain_directory(info):
            with os.scandir(target) as entries:
                empty = next(entries, None) is None
        if not _is_plain_directory(info) or not empty:
            raise error_type(
                "clone target is no longer an empty directory; it was left untouched"
            )
    except error_type:
        raise
    except OSError as exc:
        raise error_type(
            "clone target could not be inspected safely; it was left untouched"
        ) from exc
    return info.st_dev, info.st_ino


def _is_plain_directory(info: os.stat_result) -> bool:
    """A real directory: not a symlink, junction or other reparse point."""
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISDIR(info.st_mode) and not (
        getattr(info, "st_file_attributes", 0) & reparse
    )


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
    if (current.st_dev, current.st_ino) != tuple(expected) or not _is_plain_directory(
        current
    ):
        raise error_type(
            "clone target path changed during Git; partial data was left untouched"
        )


__all__ = ["CloneTargetClaim", "run_clone"]
