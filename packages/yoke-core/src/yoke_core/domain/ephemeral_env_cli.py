"""Command-line adapter for ephemeral environment lifecycle operations."""

from __future__ import annotations

import sys
from typing import Optional

from yoke_core.domain.db_helpers import connect

_USAGE = """\
Usage: ephemeral-env <subcmd> [args...]

Subcommands:
  create <project> <branch> [--item X] [--workflow-run-id Y] [--github-ref Z]
  update <id> <field> <value>
  get <project> <branch>
  get-by-id <id> [field]
  list [--project X] [--status Y]
  cleanup [--max-age-hours N]
"""


def _error(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _usage_error(message: str) -> None:
    _error(message, 2)


def main(argv: Optional[list[str]] = None) -> None:
    """Dispatch the retained source-development CLI."""
    from yoke_core.domain.ephemeral_env import (
        cmd_cleanup,
        cmd_create,
        cmd_get,
        cmd_get_by_id,
        cmd_list,
        cmd_update,
    )

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        _usage_error(_USAGE)
    subcmd, rest = args[0], args[1:]
    conn = connect()
    try:
        if subcmd == "create":
            if len(rest) < 2:
                _usage_error(
                    "Usage: ephemeral-env create <project> <branch> "
                    "[--item X] [--workflow-run-id Y] [--github-ref Z]"
                )
            project, branch = rest[0], rest[1]
            options = {
                "--item": "",
                "--workflow-run-id": "",
                "--github-ref": "",
            }
            index = 2
            while index < len(rest):
                flag = rest[index]
                if flag not in options or index + 1 >= len(rest):
                    _error(f"Error: unknown flag '{flag}'", 2)
                options[flag] = rest[index + 1]
                index += 2
            print(
                cmd_create(
                    conn,
                    project,
                    branch,
                    options["--item"],
                    options["--workflow-run-id"],
                    options["--github-ref"],
                )
            )
        elif subcmd == "update":
            if len(rest) < 3:
                _usage_error("Usage: ephemeral-env update <id> <field> <value>")
            print(cmd_update(conn, int(rest[0]), rest[1], rest[2]))
        elif subcmd == "get":
            if len(rest) < 2:
                _usage_error("Usage: ephemeral-env get <project> <branch>")
            print(cmd_get(conn, rest[0], rest[1]))
        elif subcmd == "get-by-id":
            if not rest:
                _usage_error("Usage: ephemeral-env get-by-id <id> [field]")
            print(
                cmd_get_by_id(
                    conn,
                    int(rest[0]),
                    rest[1] if len(rest) > 1 else None,
                )
            )
        elif subcmd == "list":
            options = {"--project": None, "--status": None}
            index = 0
            while index < len(rest):
                flag = rest[index]
                if flag in options and index + 1 < len(rest):
                    options[flag] = rest[index + 1]
                    index += 2
                else:
                    index += 1
            result = cmd_list(
                conn,
                options["--project"],
                options["--status"],
            )
            if result:
                print(result)
        elif subcmd == "cleanup":
            max_age = 24
            index = 0
            while index < len(rest):
                if rest[index] == "--max-age-hours" and index + 1 < len(rest):
                    max_age = int(rest[index + 1])
                    index += 2
                else:
                    index += 1
            print(cmd_cleanup(conn, max_age))
        else:
            _usage_error(_USAGE)
    except LookupError as exc:
        _error(f"Error: {exc}", 1)
    except ValueError as exc:
        _error(f"Error: {exc}", 2)
    finally:
        conn.close()


__all__ = ["main"]
