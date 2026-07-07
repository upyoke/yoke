"""CLI entry point for ``python3 -m yoke_core.domain.epic``.

This module owns the parser-level surface: ``_USAGE``,
``_TASK_UPDATE_BODY_USAGE``, ``_cli_error``, ``_cli_usage_error``, the
subcommand registration sets (``_EPIC_CMDS``, ``_VALIDATE_EPIC_CMDS``), and
the ``main`` entry point with its argv parsing, epic-id resolution, validation,
exception-to-exit-code mapping, and connection lifecycle.

Subcommand handlers live in two responsibility-named siblings:

- :mod:`yoke_core.domain.epic_cli_handlers_task` — task CRUD, file-add,
  history, dispatch-chain handlers.
- :mod:`yoke_core.domain.epic_cli_handlers_review` — review, progress notes,
  simulation, proceed-triage-handoff, cascade, orphan-check, migrate-task-files.

Domain functions are accessed via the parent ``epic`` module object so that
test patches on ``yoke_core.domain.epic.*`` continue to intercept calls
from the handler modules.
"""

from __future__ import annotations

import sys
from typing import List, Optional

# Import the parent module object — NOT individual names — so that test
# patches on ``yoke_core.domain.epic.X`` are seen inside main().
from yoke_core.domain import epic as _epic


_USAGE = """\
Usage: python3 -m yoke_core.domain.epic <subcmd> [args...]

Subcommands:
  task-upsert <epic-id> <task_num> <title> <worktree> <context_estimate> <dependencies>
  task-get <epic-id> <task_num>
  task-list <epic-id>
  task-update-status <epic-id> <task_num> <status>
  task-update-body <epic-id> <task_num> [--body-file <path>]  (reads body from stdin when the flag is omitted)
  task-get-body <epic-id> <task_num>
  task-update-field <epic-id> <task_num> <field> <value>
  file-add <epic-id> <task_num> <file_path> <action>
  file-list <epic-id> <task_num>
  history-insert <epic-id> <task_num> <from_status> <to_status> [note | --body-file <path>]
  dispatch-chain-upsert <epic-id> <worktree>  (reads JSON from stdin)
  dispatch-chain-get <epic-id> <worktree>
  dispatch-chain-update <epic-id> <worktree> <field> <value>
  dispatch-chain-list <epic-id>
  dispatch-chain-advance <epic-id> <worktree>
  dispatch-chain-refresh-activation <epic-id> <worktree> <task-num>
  review-seed <epic-id> <task_num>
  review-insert <epic-id> <task_num> <verdict> [--body-file <path>]  (reads body from stdin when omitted)
  review-get <epic-id> <task_num>
  progress-note-insert <epic-id> <task_num> <note_num> [--body-file <path>]
  progress-note-list <epic-id> <task_num> [--limit N]
  progress-note-list-unsynced <epic-id>
  progress-note-mark-synced <epic-id> <task_num> <note_num>
  submission-receipt-get <epic-id> <task_num> [--after-note-count N]
  simulation-upsert <epic-id> <phase>  (reads body from stdin)
  simulation-get <epic-id> <phase>
  proceed-triage-handoff <epic-id> [--recommendation R] [--gap-summary S]
                              [--filed-tickets T1,T2] [--session-id SID]
  cascade-task-status <epic-id> <from-parent-status> <to-parent-status>
  orphan-check
  migrate-task-files                  Add UNIQUE constraint to epic_task_files (idempotent)
"""

_TASK_UPDATE_BODY_USAGE = (
    "Usage: task-update-body <epic-id> <task_num> [--body-file <path>] "
    "(reads body from stdin when the flag is omitted)"
)


def _cli_error(msg: str, code: int = 1) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


def _cli_usage_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for ``python3 -m yoke_core.domain.epic``."""
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        _cli_usage_error(_USAGE)

    subcmd = args[0]
    rest = args[1:]

    # ``<subcmd> --help`` prints the canonical usage and exits 0
    # before the per-subcommand epic-id validator fires.
    if subcmd in ("-h", "--help"):
        print(_USAGE)
        sys.exit(0)
    if rest and rest[0] in ("-h", "--help"):
        print(_USAGE)
        sys.exit(0)

    # Parse epic_id for commands that take one
    _EPIC_CMDS = {
        "task-upsert", "task-get", "task-list", "task-update-status",
        "task-update-body", "task-get-body", "task-update-field",
        "file-add", "file-list", "history-insert",
        "dispatch-chain-upsert", "dispatch-chain-get", "dispatch-chain-update",
        "dispatch-chain-list", "dispatch-chain-advance",
        "dispatch-chain-refresh-activation",
        "review-seed", "review-insert", "review-get",
        "progress-note-insert", "progress-note-list", "progress-note-list-unsynced",
        "progress-note-mark-synced", "submission-receipt-get",
        "simulation-upsert", "simulation-get",
        "cascade-task-status", "proceed-triage-handoff",
    }

    epic_id = None
    if subcmd in _EPIC_CMDS and rest:
        try:
            epic_id = _epic._parse_epic_id(rest[0])
        except ValueError as e:
            _cli_error(str(e))
        rest = rest[1:]

    conn = _epic.connect()

    # Validate epic exists for read/update commands
    _VALIDATE_EPIC_CMDS = {
        "task-get", "task-list", "task-update-status", "task-update-body",
        "task-get-body", "task-update-field", "file-add", "file-list",
        "history-insert", "review-seed", "review-insert", "review-get",
        "progress-note-insert", "progress-note-list", "progress-note-list-unsynced",
        "progress-note-mark-synced", "submission-receipt-get",
        "simulation-get", "cascade-task-status",
    }
    if subcmd in _VALIDATE_EPIC_CMDS and epic_id is not None:
        try:
            _epic._validate_epic_exists(conn, epic_id)
        except LookupError as e:
            _cli_error(str(e))

    # Imported lazily so that the lightweight no-arg usage path stays cheap
    # and so that handler modules can ``from yoke_core.domain.epic_cli
    # import _cli_error`` without forming an import cycle at module load.
    from yoke_core.domain.epic_cli_handlers_task import handle as _handle_task
    from yoke_core.domain.epic_cli_handlers_review import handle as _handle_review

    try:
        handled = _handle_task(_epic, conn, subcmd, rest, epic_id)
        if not handled:
            handled = _handle_review(_epic, conn, subcmd, rest, epic_id)
        if not handled:
            _cli_usage_error(_USAGE)

    except LookupError as e:
        _cli_error(str(e), 1)
    except ValueError as e:
        _cli_error(str(e), 2 if "invalid field" in str(e) else 1)
    except PermissionError as e:
        _cli_error(str(e), 3)
    except IndexError as e:
        _cli_error(str(e), 1)
    except RuntimeError as e:
        _cli_error(str(e), 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
