"""Shared schema facade for the canonical Yoke control-plane schema.

Converges the canonical ``items`` table with all columns, shared tables
(ouroboros_entries, wrapup_reports, release_entries, epic_tasks,
epic_task_files, epic_dispatch_chains, epic_progress_notes, qa_requirements,
qa_runs, qa_artifacts, merge_locks, item_sections, harness_sessions,
work_claims), compatibility indexes, and runs idempotent ADD COLUMN
migrations for newer columns.

The active Yoke control plane is Postgres. Core-table CREATE TABLE blocks emit
portable DDL so explicitly provisioned SQLite validation surfaces can exercise
the same schema; those validation surfaces are never control-plane authority.
The DDL has no implicit-id auto-increment clauses or SQLite-only timestamp
default clauses.
Callers supply ``created_at`` / ``updated_at`` explicitly via
:func:`yoke_core.domain.db_helpers.iso8601_now`.  JSON-payload ``TEXT``
columns carry a ``-- → JSONB on Postgres`` annotation for backend-aware schema
rendering; the enumeration lives in
:data:`yoke_core.domain.sql_json.JSONB_COLUMNS`.

CLI usage::

    python3 -m yoke_core.domain.schema <subcmd>

Subcommands:

    init, migration-audit-list, migration-verify

Exit codes: 0 success, 1 error/not-found, 2 usage error.

Field-level sub-modules:
  schema_checks.py     — status validators + canonical status constants
  schema_migrations.py — idempotent data-shape migrations
  schema_orphans.py    — sibling state-dir collision guards
  schema_init.py       — table creation and idempotent init pipeline
"""

from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain.schema_common import (
    _USAGE, _check_sibling_state_collision,
    _cli_error, _cli_usage_error, _connect_raw,
    _resolve_db_path, _resolve_db_root,
    check_sibling_state_collision, guard_state_dir_creation,
)
from yoke_core.domain import schema_init as _schema_init


def cmd_init() -> None:
    """Converge shared tables while preserving front-door patch hooks."""
    _schema_init._check_sibling_state_collision = _check_sibling_state_collision
    _schema_init._cli_error = _cli_error
    _schema_init._connect_raw = _connect_raw
    _schema_init._resolve_db_path = _resolve_db_path
    _schema_init._resolve_db_root = _resolve_db_root
    return _schema_init.cmd_init()

__all__ = [
    "check_sibling_state_collision", "guard_state_dir_creation",
    "_check_sibling_state_collision", "_resolve_db_path",
    "_resolve_db_root", "cmd_init", "main",
]


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for schema module."""
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        _cli_usage_error(_USAGE)

    subcmd = args[0]
    if subcmd in ("-h", "--help"):
        print(_USAGE)
        return

    dispatch = {
        "init": cmd_init,
    }

    # migration audit commands
    if subcmd == "migration-audit-list":
        from yoke_core.domain.migration_harness import cmd_audit_list
        cmd_audit_list(_resolve_db_path())
        return
    if subcmd == "migration-verify":
        from yoke_core.domain.migration_harness import cmd_verify
        cmd_verify(_resolve_db_path())
        return

    handler = dispatch.get(subcmd)
    if handler is None:
        _cli_usage_error(_USAGE)

    handler()


if __name__ == "__main__":
    main()
