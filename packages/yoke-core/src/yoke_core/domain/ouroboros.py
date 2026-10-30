"""Ouroboros CLI and public compatibility surface.

Manages the Ouroboros entry table through responsibility-named sibling
modules while preserving the historical module entrypoint.

CLI usage::

    python3 -m yoke_core.domain.ouroboros <subcmd> [args...]

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.ouroboros_entries import (
    cmd_list_entries,
    cmd_mark_archived,
    cmd_mark_reviewed,
)

__all__ = [
    "cmd_list_entries",
    "cmd_mark_archived",
    "cmd_mark_reviewed",
    "main",
]

_USAGE = """\
Usage: ouroboros <subcmd> [args...]

Subcommands:
  list-entries [--unreviewed] [--project <p>]
  mark-reviewed <id> [--project <p>]
  mark-archived [--all-reviewed | <id>] [--project <p>] [--include-unattributed]
"""


def _split_scope_flags(rest: List[str]) -> tuple[List[str], Optional[str], bool]:
    """Split project-scope flags out of a subcommand's remaining arguments."""
    positional: List[str] = []
    project: Optional[str] = None
    include_unattributed = False
    i = 0
    while i < len(rest):
        if rest[i] == "--project" and i + 1 < len(rest):
            project = rest[i + 1]
            i += 2
            continue
        if rest[i] == "--include-unattributed":
            include_unattributed = True
        else:
            positional.append(rest[i])
        i += 1
    return positional, project, include_unattributed


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
        if subcmd == "list-entries":
            positional, project, _ = _split_scope_flags(rest)
            result = cmd_list_entries(conn, "--unreviewed" in positional, project)
            if result:
                print(result)

        elif subcmd == "mark-reviewed":
            positional, project, _ = _split_scope_flags(rest)
            if not positional:
                _cli_usage_error("Usage: ouroboros mark-reviewed <id> [--project <p>]")
            print(cmd_mark_reviewed(conn, int(positional[0]), project))

        elif subcmd == "mark-archived":
            positional, project, unattributed = _split_scope_flags(rest)
            if positional and positional[0] == "--all-reviewed":
                print(
                    cmd_mark_archived(
                        conn,
                        all_reviewed=True,
                        project=project,
                        include_unattributed=unattributed,
                    )
                )
            elif positional:
                print(
                    cmd_mark_archived(
                        conn,
                        entry_id=int(positional[0]),
                        project=project,
                    )
                )
            else:
                _cli_usage_error(
                    "Usage: ouroboros mark-archived [--all-reviewed | <id>]"
                )

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
