"""Backlog mutation orchestration for the Yoke software delivery system.

This module is the public API surface for all backlog operations: item
creation, updates, structured field writes, queries, rendering, and
GitHub synchronization.  The implementation is split across three child
modules for maintainability:

- ``backlog_queries``   -- read/query functions and shared helpers
- ``backlog_updates``   -- write/mutation functions and CLI entry points
- ``backlog_rendering`` -- board rebuild, GitHub sync, and event emission

All public symbols are re-exported here so that existing callers using
``from yoke_core.domain.backlog import X`` continue to work unchanged.

CLI usage::

    python3 -m yoke_core.domain.backlog create \\
        --title TITLE --type TYPE [--priority P] [--project P] \\
        [--deployment-flow F] [--status S] [--source S] [--dry-run]

    python3 -m yoke_core.domain.backlog update <item-id> \\
        --field FIELD --value VALUE \\
        [--done-nonce-verified] [--force] [--qa-bypass] [--dry-run]

    python3 -m yoke_core.domain.backlog structured-write <item-id> \\
        --field FIELD (--file PATH | --stdin) [--force] [--source S]
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# Re-exports from backlog_queries (shared helpers + read operations)
# ---------------------------------------------------------------------------
from yoke_core.domain.backlog_queries import (  # noqa: F401
    CONTENT_TRACKING_FIELDS,
    INTEGER_FIELDS,
    LABEL_SYNC_FIELDS,
    VALID_STRUCTURED_FIELDS,
    _assert_write_db_ready,
    _get_next_id,
    _is_dry_run,
    _normalize_item_ref,
    _now_iso,
    _query_item_field,
    _resolve_deploy_envs,
    _resolve_write_db_path,
    _yoke_root,
    _zero_pad,
    dedup_search,
    get_next_display_id,
)

# ---------------------------------------------------------------------------
# Re-exports from backlog_rendering (sync, events, board, display)
# ---------------------------------------------------------------------------
from yoke_core.domain.backlog_rendering import (  # noqa: F401
    _close_issue,
    _emit_event,
    _maybe_rebuild_board,
    _post_comment,
    _rebuild_board,
    _record_sync_failure,
    _render_body,
    _resolve_project_github_repo,
    _sync_body,
    _sync_frozen_label,
    _sync_item,
    _sync_labels,
    _sync_title,
)

# ---------------------------------------------------------------------------
# Re-exports from backlog_updates (mutations, CLI)
# ---------------------------------------------------------------------------
from yoke_core.domain.backlog_updates import (  # noqa: F401
    _apply_shell_fallback,
    _cascade_epic_tasks,
    _current_session_id,
    _insert_item,
    _maybe_migrate_project_issue,
    _maybe_set_session_current_item,
    _run_authoritative_status_gate,
    _update_item_field,
    _update_item_multi,
    _verify_status_claim,
    execute_batch_update,
    execute_close,
    execute_create,
    execute_structured_write,
    execute_update,
    main,
)


if __name__ == "__main__":
    sys.exit(main())
