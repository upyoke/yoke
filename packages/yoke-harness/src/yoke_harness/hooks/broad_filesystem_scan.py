"""Client-local whole-disk scan refusal.

Mirrors ``yoke_core.domain.lint_broad_filesystem_scan`` through the shared
contracts classifier, so the client and engine decide identically.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.hook_runner.broad_filesystem_scan import (
    broad_scan_reason,
    find_broad_scan,
)
from yoke_contracts.hook_runner.shell_parse import ShellParse
from yoke_harness.hooks.local_policy_common import DENY, NOOP, PolicyResult


def lint_broad_filesystem_scan(payload: dict, shell: ShellParse) -> PolicyResult:
    """Deny a command that would walk ``/``, ``/Users`` or another disk root."""
    tool = payload.get("tool_name") or payload.get("toolName")
    if tool and tool != "Bash":
        return PolicyResult(NOOP)
    cwd = payload.get("cwd")
    scan = find_broad_scan(
        shell, cwd=cwd if isinstance(cwd, str) else None, home=str(Path.home())
    )
    if scan is None:
        return PolicyResult(NOOP)
    return PolicyResult(DENY, broad_scan_reason(scan))


__all__ = ["lint_broad_filesystem_scan"]
