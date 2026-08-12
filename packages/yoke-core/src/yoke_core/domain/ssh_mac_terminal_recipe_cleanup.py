"""Staged-file cleanup composition for terminal recipes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from yoke_core.domain.host_control_runner import HostActionResult
from yoke_core.domain.ssh_mac_terminal_capture import RunRemote
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    cleanup_staged_files,
)


def with_staged_cleanup(
    run: RunRemote,
    result: HostActionResult,
    staged: list[dict[str, str]],
) -> HostActionResult:
    """Attach cleanup evidence and fail closed when staged files remain."""
    if not staged:
        return result
    try:
        cleanup_ok = cleanup_staged_files(run, staged)
    except Exception:
        cleanup_ok = False
    evidence: dict[str, Any] = {
        **result.evidence,
        "staged_file_cleanup": cleanup_ok,
    }
    if cleanup_ok:
        return HostActionResult(
            result.ok,
            evidence,
            result.error_code,
        )
    if result.error_code is not None:
        evidence["primary_error_code"] = result.error_code
    return HostActionResult(
        False,
        evidence,
        "terminal_stage_file_cleanup_failed",
    )


def remove_staged_files(
    run: RunRemote,
    staged: Sequence[dict[str, str]],
) -> None:
    """Best-effort exceptional-path cleanup."""
    cleanup_staged_files(run, list(staged))


__all__ = ["remove_staged_files", "with_staged_cleanup"]
