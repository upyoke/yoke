"""Backlog write and mutation operations stable import surface.

Responsibility-named sibling modules own the write behavior. This module
re-exports the public mutation operations (`execute_close`,
`execute_create`, `execute_update`, `execute_batch_update`,
`execute_structured_write`) plus the private helper surface that
`backlog.py` and patch-based tests consume.

Sibling layout (each imported directly — no two-hop indirection):

- ``backlog_close_op``                — ``execute_close`` (cancellation path)
- ``backlog_create_op``               — ``execute_create``
- ``backlog_update_op``               — ``execute_update``, ``execute_batch_update``
- ``backlog_structured_write_op``     — ``execute_structured_write``
- ``backlog_updates_cli``             — argparse-style CLI dispatcher (already split)

Private helpers are also importable via ``backlog_updates_helpers``,
which re-exports from the same canonical owners.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Re-export private helpers consumed through ``backlog_updates``.
# Imported directly from the canonical owner siblings — never through the
# helpers shim, which would be a two-hop indirection.
# ---------------------------------------------------------------------------
from yoke_core.domain.backlog_item_db_writes import (  # noqa: F401
    _insert_item,
    _update_item_field,
    _update_item_multi,
)
from yoke_core.domain.backlog_session_attribution import (  # noqa: F401
    _current_session_id,
    _maybe_set_session_current_item,
)
from yoke_core.domain.backlog_status_claim_verification import (  # noqa: F401
    _verify_status_claim,
)
from yoke_core.domain.backlog_epic_task_cascade import (  # noqa: F401
    _cascade_epic_tasks,
)
from yoke_core.domain.backlog_authoritative_status_gate import (  # noqa: F401
    _run_authoritative_status_gate,
)
from yoke_core.domain.backlog_unsupported_field_writes import (  # noqa: F401
    _apply_shell_fallback,
)
from yoke_core.domain.backlog_project_issue_migration import (  # noqa: F401
    _maybe_migrate_project_issue,
)

# ---------------------------------------------------------------------------
# Re-export helpers used by tests that patched ``backlog_updates._is_dry_run``.
# ---------------------------------------------------------------------------
from yoke_core.domain.backlog_queries import _is_dry_run  # noqa: F401

# ---------------------------------------------------------------------------
# Public mutation operations — re-exported from responsibility-named siblings.
# ---------------------------------------------------------------------------
from yoke_core.domain.backlog_close_op import execute_close  # noqa: F401
from yoke_core.domain.backlog_create_op import execute_create  # noqa: F401
from yoke_core.domain.backlog_update_op import (  # noqa: F401
    execute_batch_update,
    execute_update,
)
from yoke_core.domain.backlog_structured_write_op import (  # noqa: F401
    execute_structured_write,
)


def main(argv=None) -> int:
    """CLI entry point — delegates to backlog_updates_cli."""
    from yoke_core.domain.backlog_updates_cli import main as _cli_main
    return _cli_main(argv)


__all__ = [
    # Public ops
    "execute_close",
    "execute_create",
    "execute_update",
    "execute_batch_update",
    "execute_structured_write",
    # Private helpers
    "_insert_item",
    "_update_item_field",
    "_update_item_multi",
    "_current_session_id",
    "_maybe_set_session_current_item",
    "_verify_status_claim",
    "_cascade_epic_tasks",
    "_run_authoritative_status_gate",
    "_apply_shell_fallback",
    "_maybe_migrate_project_issue",
    "_is_dry_run",
    # CLI entry
    "main",
]


if __name__ == "__main__":
    import sys
    sys.exit(main())
