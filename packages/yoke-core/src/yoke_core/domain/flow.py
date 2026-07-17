"""Deployment flows domain logic (invoked via ``python3 -m yoke_core.domain.flow``).

Manages the ``deployment_flows`` table and the ``item_progress_view``.
This module is the CLI front door — it owns argv parsing and dispatch
plus the small set of CLI helpers used inside :func:`main`.  The
substantive logic lives in responsibility-named siblings:

- :mod:`yoke_core.domain.flow_validation` — stage-shape validation
  and the executor/kind vocabularies.
- :mod:`yoke_core.domain.flow_init` — table DDL, seed flows, and the
  ``item_progress_view`` projection.
- :mod:`yoke_core.domain.flow_cross_reference` — project-level
  cross-reference of ``migration_apply`` stages against declared
  ``migration_model`` capabilities.
- :mod:`yoke_core.domain.flow_crud` — ``cmd_create``/``cmd_get``/
  ``cmd_list``/``cmd_stages`` plus the field allow-list and row
  formatter shared by them.

CLI usage::

    python3 -m yoke_core.domain.flow <subcmd> [args...]

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""
from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect

# Re-exports — every importer of ``yoke_core.domain.flow`` continues
# to resolve these names from this front door.  Each public name imports
# DIRECTLY from its canonical owner sibling (no two-hop indirection).
from yoke_core.domain.flow_crud import (
    cmd_create,
    cmd_delete,
    cmd_get,
    cmd_list,
    cmd_set_status,
    cmd_stages,
    cmd_update_stages,
)
from yoke_core.domain.flow_init import cmd_init
from yoke_core.domain.flow_validation import (
    VALID_EXECUTORS,
    VALID_MIGRATION_APPLY_LIFECYCLE_PHASES,
    VALID_STAGE_KINDS,
    validate_stages,
)

__all__ = [
    "VALID_EXECUTORS",
    "VALID_MIGRATION_APPLY_LIFECYCLE_PHASES",
    "VALID_STAGE_KINDS",
    "cmd_create",
    "cmd_delete",
    "cmd_get",
    "cmd_init",
    "cmd_list",
    "cmd_set_status",
    "cmd_stages",
    "cmd_update_stages",
    "main",
    "validate_stages",
]

_USAGE = """\
Usage: flow <subcmd> [args...]

Subcommands:
  init                                              Create table + seed data
  create <id> <project> <name> <desc> <stages_json> [on_failure]
  get <id> [field]                                  Get flow
  list [--project <project>] [--include-disabled]   List flows
  stages <id>                                       Output raw JSON stages
  update-stages <id> <stages_json> [--description D]  Replace stages (validated)
  set-status <id> <active|disabled>                 Enable/disable without deleting
  delete <id> [--repoint-items-to <flow-id>]        Delete flow (repoint refs)
"""


def _cli_error(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _cli_usage_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def main(argv: Optional[List[str]] = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        _cli_usage_error(_USAGE)

    subcmd = args[0]
    rest = args[1:]

    conn = connect()

    try:
        if subcmd == "init":
            print(cmd_init(conn))

        elif subcmd == "create":
            if len(rest) < 5:
                _cli_usage_error(
                    "Usage: flow create <id> <project> <name> <desc> <stages_json> [on_failure]"
                )
            on_failure = rest[5] if len(rest) > 5 else "halt"
            print(cmd_create(conn, rest[0], rest[1], rest[2], rest[3], rest[4], on_failure))

        elif subcmd == "get":
            if not rest:
                _cli_usage_error("Usage: flow get <id> [field]")
            field = rest[1] if len(rest) > 1 else None
            print(cmd_get(conn, rest[0], field))

        elif subcmd == "list":
            project = None
            include_disabled = False
            i = 0
            while i < len(rest):
                if rest[i] == "--project" and i + 1 < len(rest):
                    project = rest[i + 1]; i += 2
                elif rest[i] == "--include-disabled":
                    include_disabled = True; i += 1
                else:
                    i += 1
            result = cmd_list(conn, project, include_disabled=include_disabled)
            if result:
                print(result)

        elif subcmd == "stages":
            if not rest:
                _cli_usage_error("Usage: flow stages <id>")
            print(cmd_stages(conn, rest[0]))

        elif subcmd == "update-stages":
            if len(rest) < 2:
                _cli_usage_error(
                    "Usage: flow update-stages <id> <stages_json> "
                    "[--description D]"
                )
            description = None
            i = 2
            while i < len(rest):
                if rest[i] == "--description" and i + 1 < len(rest):
                    description = rest[i + 1]; i += 2
                else:
                    i += 1
            print(cmd_update_stages(conn, rest[0], rest[1], description))

        elif subcmd == "set-status":
            if len(rest) != 2:
                _cli_usage_error("Usage: flow set-status <id> <active|disabled>")
            print(cmd_set_status(conn, rest[0], rest[1]))

        elif subcmd == "delete":
            if not rest:
                _cli_usage_error(
                    "Usage: flow delete <id> [--repoint-items-to <flow-id>]"
                )
            repoint_to = None
            i = 1
            while i < len(rest):
                if rest[i] == "--repoint-items-to" and i + 1 < len(rest):
                    repoint_to = rest[i + 1]; i += 2
                else:
                    i += 1
            print(cmd_delete(conn, rest[0], repoint_to))

        else:
            _cli_usage_error(_USAGE)

    except LookupError as e:
        _cli_error(f"Error: {e}", 1)
    except ValueError as e:
        _cli_error(f"Error: {e}", 2 if "invalid" in str(e).lower() else 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
