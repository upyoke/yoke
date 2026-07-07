"""Ouroboros CLI and public compatibility surface.

Manages the ``ouroboros_entries`` and ``wrapup_reports`` tables through
responsibility-named sibling modules while preserving the historical
``python3 -m yoke_core.domain.ouroboros`` entrypoint.

CLI usage::

    python3 -m yoke_core.domain.ouroboros <subcmd> [args...]

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""
from __future__ import annotations

import select as select_mod
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.ouroboros_entries import (
    cmd_insert_entry,
    cmd_list_entries,
    cmd_mark_archived,
    cmd_mark_reviewed,
)
from yoke_core.domain.ouroboros_wrapups import (
    _resolve_wrapups_dir,
    cmd_generate_wrapup,
    cmd_insert_wrapup,
    cmd_list_wrapups,
)

__all__ = [
    "cmd_generate_wrapup",
    "cmd_insert_entry",
    "cmd_insert_wrapup",
    "cmd_list_entries",
    "cmd_list_wrapups",
    "cmd_mark_archived",
    "cmd_mark_reviewed",
    "main",
]

_USAGE = """\
Usage: ouroboros <subcmd> [args...]

Subcommands:
  insert-entry <timestamp> <agent> <context> <category> <body>
  insert-entry --body-stdin <timestamp> <agent> <context> <category>
  insert-entry --agent <a> --category <c> [--context <x>] [--timestamp <t>] [--project <p>] --observation <o>
  insert-wrapup <session_timestamp>     (body from stdin)
  list-entries [--unreviewed] [--project <p>]
  list-wrapups
  mark-reviewed <id>
  generate-wrapup <session_timestamp>
  mark-archived [--all-reviewed | <id>]
"""


def _cli_error(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _cli_usage_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _read_stdin_safe() -> str:
    if sys.stdin.isatty():
        return ""
    if hasattr(select_mod, "select"):
        readable, _, _ = select_mod.select([sys.stdin], [], [], 0.5)
        if not readable:
            return ""
    return sys.stdin.read()


def _insert_entry_named(conn, rest: list[str]) -> None:
    agent = context = category = observation = timestamp = project = None
    body_stdin = "--body-stdin" in rest
    i = 0
    while i < len(rest):
        if rest[i] == "--body-stdin":
            i += 1
        elif rest[i] == "--agent" and i + 1 < len(rest):
            agent = rest[i + 1]
            i += 2
        elif rest[i] == "--context" and i + 1 < len(rest):
            context = rest[i + 1]
            i += 2
        elif rest[i] == "--category" and i + 1 < len(rest):
            category = rest[i + 1]
            i += 2
        elif rest[i] == "--observation" and i + 1 < len(rest):
            observation = rest[i + 1]
            i += 2
        elif rest[i] == "--timestamp" and i + 1 < len(rest):
            timestamp = rest[i + 1]
            i += 2
        elif rest[i] == "--project" and i + 1 < len(rest):
            project = rest[i + 1]
            i += 2
        else:
            _cli_error(f"Error: unrecognized flag '{rest[i]}'", 2)

    if not agent:
        _cli_error("Error: --agent is required", 2)
    if not category:
        _cli_error("Error: --category is required", 2)
    if not timestamp:
        timestamp = iso8601_now()

    if body_stdin:
        if observation:
            _cli_error(
                "Error: --body-stdin and --observation are mutually exclusive", 2
            )
        body = _read_stdin_safe() or sys.stdin.read()
    else:
        if not observation:
            _cli_error("Error: either --observation or --body-stdin is required", 2)
        body = observation

    print(cmd_insert_entry(conn, timestamp, agent, context, category, body, project))


def _insert_entry_positional(conn, rest: list[str]) -> None:
    body_stdin = "--body-stdin" in rest
    positionals = [arg for arg in rest if arg != "--body-stdin"]
    if body_stdin:
        if len(positionals) < 4:
            _cli_usage_error(
                "Usage: ouroboros insert-entry --body-stdin "
                "<timestamp> <agent> <context> <category>"
            )
        body = _read_stdin_safe() or sys.stdin.read()
        print(
            cmd_insert_entry(
                conn,
                positionals[0],
                positionals[1],
                positionals[2] or None,
                positionals[3],
                body,
            )
        )
        return

    if len(positionals) < 5:
        _cli_usage_error(_USAGE)
    print(
        cmd_insert_entry(
            conn,
            positionals[0],
            positionals[1],
            positionals[2] or None,
            positionals[3],
            positionals[4],
        )
    )


def _handle_insert_entry(conn, rest: list[str]) -> None:
    named_mode = any(
        arg
        in ("--agent", "--context", "--category", "--observation", "--timestamp", "--project")
        for arg in rest
    )
    if named_mode:
        _insert_entry_named(conn, rest)
    else:
        _insert_entry_positional(conn, rest)


def main(argv: Optional[List[str]] = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        _cli_usage_error(_USAGE)

    subcmd = args[0]
    rest = args[1:]
    conn = connect()

    try:
        if subcmd == "insert-entry":
            _handle_insert_entry(conn, rest)

        elif subcmd == "insert-wrapup":
            if not rest:
                _cli_usage_error("Usage: ouroboros insert-wrapup <session_timestamp>")
            body = _read_stdin_safe() or sys.stdin.read()
            if not body:
                _cli_error("Error: empty body from stdin", 1)
            print(cmd_insert_wrapup(conn, rest[0], body))

        elif subcmd == "list-entries":
            unreviewed = "--unreviewed" in rest
            project = None
            i = 0
            while i < len(rest):
                if rest[i] == "--project" and i + 1 < len(rest):
                    project = rest[i + 1]
                    i += 2
                else:
                    i += 1
            result = cmd_list_entries(conn, unreviewed, project)
            if result:
                print(result)

        elif subcmd == "list-wrapups":
            result = cmd_list_wrapups(conn)
            if result:
                print(result)

        elif subcmd == "mark-reviewed":
            if not rest:
                _cli_usage_error("Usage: ouroboros mark-reviewed <id>")
            print(cmd_mark_reviewed(conn, int(rest[0])))

        elif subcmd == "generate-wrapup":
            if not rest:
                _cli_usage_error("Usage: ouroboros generate-wrapup <session_timestamp>")
            print(cmd_generate_wrapup(conn, rest[0]))

        elif subcmd == "mark-archived":
            if rest and rest[0] == "--all-reviewed":
                print(cmd_mark_archived(conn, all_reviewed=True))
            elif rest:
                print(cmd_mark_archived(conn, entry_id=int(rest[0])))
            else:
                _cli_usage_error("Usage: ouroboros mark-archived [--all-reviewed | <id>]")

        else:
            _cli_usage_error(_USAGE)

    except LookupError as e:
        _cli_error(f"Error: {e}", 1)
    except ValueError as e:
        _cli_error(f"Error: {e}", 2)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
