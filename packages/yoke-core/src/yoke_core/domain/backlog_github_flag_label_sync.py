"""Boolean-flag GitHub label sync — ``sync_frozen_label`` / ``sync_blocked_label``.

Thin public wrappers over the shared add/remove engine
``backlog_github_state_sync._sync_flag_label`` (which owns the auth,
issue-validation, sync-mode, and REST plumbing — and stays the patch
surface for tests). Split out so the state-sync module keeps line-count
headroom.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_github_fetch import (
    BLOCKED_LABEL_COLOR,
    FROZEN_LABEL_COLOR,
)


def _flag_engine():
    """Live shared flag-label engine (call-time patch target)."""
    from yoke_core.domain import backlog_github_state_sync as mod
    return mod._sync_flag_label


def sync_frozen_label(
    item_id: str,
    frozen_value: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    return _flag_engine()(
        item_id, frozen_value,
        label="frozen", color=FROZEN_LABEL_COLOR,
        description="Item is frozen", log_name="frozen",
        conn=conn, stdout=stdout or sys.stdout, stderr=stderr or sys.stderr,
    )


def sync_blocked_label(
    item_id: str,
    blocked_value: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Add or remove the GitHub `blocked` label based on items.blocked.

    flag-driven label. The obsolete ``status:blocked`` label is no
    longer written by any code path; whenever the flag clears, this also
    scrubs ``status:blocked`` from the issue so a row repaired by the
    migration converges on a single blocked indicator.
    """
    return _flag_engine()(
        item_id, blocked_value,
        label="blocked", color=BLOCKED_LABEL_COLOR,
        description="Item blocked (flag)", log_name="blocked",
        conn=conn, stdout=stdout or sys.stdout, stderr=stderr or sys.stderr,
        extra_remove_on_clear=("status:blocked",),
    )


__all__ = ["sync_frozen_label", "sync_blocked_label"]
