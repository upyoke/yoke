"""Backlog GitHub sync stable import and patch surface.

Responsibility-named sibling modules own the sync behavior. This module
keeps the operator-facing import path compact by re-exporting public
functions and test patch targets directly from their canonical owners.

Sibling layout (each imported directly — no two-hop indirection):

- ``backlog_github_transport``      — PAT availability probe + dry-run helper
- ``backlog_github_label_sync``     — label reconcile, ``update_repo_labels``,
                                       ``sync_labels``
- ``backlog_github_item_create``    — ``sync_item`` create/dedup, ``_regenerate_md``
- ``backlog_github_state_sync``     — ``close_issue``, ``reopen_issue``,
                                       shared ``_sync_flag_label`` engine
- ``backlog_github_flag_label_sync`` — ``sync_frozen_label``,
                                       ``sync_blocked_label``
- ``backlog_github_body_title_sync`` — ``sync_body``, ``sync_title``
- ``backlog_github_done_sync``       — ``sync_done_item``
- ``backlog_github_comments``       — ``post_comment``
- ``backlog_github_repo_migration`` — ``migrate_issue_to_repo``
- ``backlog_github_sync_cli``       — CLI dispatcher (``main``)

For new code, import directly from the canonical owner sibling.
"""

from __future__ import annotations

# Module reference kept on the shim so tests can patch
# ``backlog_github_sync.epic_task_sync.sync_epic_tasks``.
from yoke_core.domain import epic_task_sync  # noqa: F401 — patch surface

# Transport: PAT availability probe + epic-children dispatch
from yoke_core.domain.backlog_github_transport import (  # noqa: F401
    _dry_run,
    _pat_available,
    _sync_epic_children,
)

# Shared read-side helpers (canonical owner: backlog_github_fetch)
from yoke_core.domain.backlog_github_fetch import (  # noqa: F401
    DEFAULT_COLOR_SOURCE,
    DEFAULT_COLOR_STATUS,
    DEFAULT_COLOR_TYPE_EPIC,
    DEFAULT_COLOR_TYPE_ISSUE,
    DEFAULT_COLOR_WORKTREE,
    BLOCKED_LABEL_COLOR,
    FROZEN_LABEL_COLOR,
    LABEL_CATEGORIES,
    REPO_LABEL_DEFINITIONS,
    _close_if_owned,
    _github_sync_skip,
    _item_context,
    _item_fields,
    _label_colors,
    _open_conn,
    _repo_args,
    _status_display_label,
)

# Shared epic-task-sync helper (canonical owner: epic_task_sync_github)
from yoke_core.domain.epic_task_sync_github import (  # noqa: F401
    _validate_issue_in_repo,
)

# Label reconcile + repo-wide label sync
from yoke_core.domain.backlog_github_label_sync import (  # noqa: F401
    _ensure_label,
    _get_issue_labels,
    _get_issue_state,
    _reconcile_category,
    _repo_labels,
    sync_labels,
    update_repo_labels,
)

# Item creation + DB linkage
from yoke_core.domain.backlog_github_item_create import (  # noqa: F401
    _regenerate_md,
    sync_item,
)

# Issue state transitions
from yoke_core.domain.backlog_github_state_sync import (  # noqa: F401
    close_issue,
    reopen_issue,
)

# Boolean-flag labels
from yoke_core.domain.backlog_github_flag_label_sync import (  # noqa: F401
    sync_blocked_label,
    sync_frozen_label,
)

# Body / title sync
from yoke_core.domain.backlog_github_body_title_sync import (  # noqa: F401
    sync_body,
    sync_title,
)

# Done-transition closeout sync
from yoke_core.domain.backlog_github_done_sync import sync_done_item  # noqa: F401

# Status-change comment
from yoke_core.domain.backlog_github_comments import post_comment  # noqa: F401

# Cross-repo migration
from yoke_core.domain.backlog_github_repo_migration import (  # noqa: F401
    migrate_issue_to_repo,
)

# CLI dispatcher
from yoke_core.domain.backlog_github_sync_cli import USAGE, main  # noqa: F401


__all__ = [
    # Transport
    "_dry_run",
    "_github_sync_skip",
    "_pat_available",
    "_sync_epic_children",
    # Shared read helpers
    "_open_conn",
    "_close_if_owned",
    "_item_context",
    "_item_fields",
    "_label_colors",
    "_repo_args",
    "_status_display_label",
    "_validate_issue_in_repo",
    "BLOCKED_LABEL_COLOR",
    "FROZEN_LABEL_COLOR",
    "LABEL_CATEGORIES",
    "REPO_LABEL_DEFINITIONS",
    "DEFAULT_COLOR_SOURCE",
    "DEFAULT_COLOR_STATUS",
    "DEFAULT_COLOR_TYPE_EPIC",
    "DEFAULT_COLOR_TYPE_ISSUE",
    "DEFAULT_COLOR_WORKTREE",
    # Label reconcile
    "_get_issue_labels",
    "_get_issue_state",
    "_repo_labels",
    "_ensure_label",
    "_reconcile_category",
    "update_repo_labels",
    "sync_labels",
    # Item create
    "_regenerate_md",
    "sync_item",
    # State transitions
    "close_issue",
    "reopen_issue",
    "sync_frozen_label",
    "sync_blocked_label",
    # Body / title
    "sync_body",
    "sync_title",
    # Done-transition closeout
    "sync_done_item",
    # Comment
    "post_comment",
    # Migration
    "migrate_issue_to_repo",
    # CLI
    "USAGE",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
