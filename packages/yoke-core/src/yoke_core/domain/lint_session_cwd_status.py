"""Status-gate helper for the session-cwd lint.

Refuse worktree-bound writes while the item driving the claim is still
in a pre-implementing status. A session can hold a work claim before
``/yoke advance`` finishes its finalize phase; without this gate the
lint would happily accept every Edit/Write into ``.worktrees/<branch>/``
even though the lifecycle never crossed into ``implementing``. The set
of pre-implementing statuses is the canonical
``lifecycle_progression.PRE_IMPLEMENTATION_STATUSES`` — re-import rather
than copy.

Mode is pinned by the machine config key ``lint_session_cwd_status_mode``
(``warn`` records audit only; ``deny`` blocks). Suppression token
``# lint:no-pre-implementing-status-check`` on a Bash command body is
recorded as audit evidence only — it does NOT unblock.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from yoke_core.domain.lifecycle_progression import PRE_IMPLEMENTATION_STATUSES


CONFIG_KEY_MODE = "lint_session_cwd_status_mode"
DEFAULT_MODE = "deny"
VALID_MODES = ("warn", "deny")
SUPPRESSION_TOKEN = "# lint:no-pre-implementing-status-check"
FAILURE_CLASS = "pre_implementing_status"


def is_pre_implementing_status(status: Optional[str]) -> bool:
    """Return True when ``status`` is in the pre-implementing set.

    Empty / None inputs return False — an unresolvable status must
    not trigger the gate (fail-open on lookup failure).
    """
    if not status:
        return False
    return status in PRE_IMPLEMENTATION_STATUSES


def _toplevel() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_mode() -> str:
    """Return the configured mode from machine config.

    Looks up ``CLAUDE_PROJECT_DIR`` / ``CODEX_PROJECT_DIR`` / ``git
    rev-parse`` in order to locate the workspace. Any failure (missing
    workspace, missing file, malformed line) returns :data:`DEFAULT_MODE`
    so the gate remains active in the default-secure deny posture.
    """
    workspace = (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("CODEX_PROJECT_DIR")
        or _toplevel()
    )
    if not workspace:
        return DEFAULT_MODE
    path = os.path.join(workspace, "data", "config")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, sep, value = line.partition("=")
                if sep and key.strip() == CONFIG_KEY_MODE:
                    cand = value.strip()
                    if cand in VALID_MODES:
                        return cand
    except Exception:
        return DEFAULT_MODE
    return DEFAULT_MODE


def command_has_suppression_token(command_text: str) -> bool:
    """Return True when ``command_text`` carries the suppression token."""
    if not isinstance(command_text, str) or not command_text:
        return False
    return SUPPRESSION_TOKEN in command_text


def build_denial_message(item_id: int, status: str) -> str:
    """Render the denial message body."""
    return (
        f"BLOCKED: worktree write while item is in pre-implementing status.\n\n"
        f"YOK-{int(item_id)} is at status='{status}'. Worktree-bound writes "
        f"require the item to be in an implementing-class status "
        f"(implementing, reviewing-implementation, polishing-implementation).\n\n"
        f"The most likely cause: /yoke advance YOK-{int(item_id)} "
        f"implementation acquired the work claim and created the worktree, "
        f"but the finalize step never ran to flip the status to "
        f"implementing. Re-enter via:\n"
        f"    /yoke advance YOK-{int(item_id)} implementation\n"
        f"to resume finalize, or apply the lifecycle.transition function "
        f"call from .agents/skills/yoke/advance/finalize.md step 6 to "
        f"flip status directly."
    )


__all__ = [
    "CONFIG_KEY_MODE",
    "DEFAULT_MODE",
    "FAILURE_CLASS",
    "SUPPRESSION_TOKEN",
    "VALID_MODES",
    "build_denial_message",
    "command_has_suppression_token",
    "is_pre_implementing_status",
    "read_mode",
]
