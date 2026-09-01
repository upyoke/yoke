"""Shepherd domain CLI front door.

Public imports from ``yoke_core.domain.shepherd`` are preserved here while the
implementation lives in focused sibling modules.

CLI usage: ``python3 -m yoke_core.domain.shepherd <subcmd> [args...]``.
"""
from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.shepherd_init import cmd_init
from yoke_core.domain.shepherd_verdict_log import (
    VALID_DISPOSITIONS,
    cmd_caveat_disposition,
    cmd_caveat_dispositions,
    cmd_shepherd_log,
    cmd_verdict,
)

__all__ = [
    "VALID_DISPOSITIONS",
    "cmd_caveat_disposition",
    "cmd_caveat_dispositions",
    "cmd_init",
    "cmd_shepherd_log",
    "cmd_verdict",
    "main",
]

_USAGE = """\
Usage: shepherd <subcmd> [args...]

Subcommands:
  init
  verdict <item> <transition> <worker> <verdict> [caveats] [session_id]
  shepherd-log <item_id>
  caveat-disposition <item> <transition> <attempt> <caveat_num> <caveat_text> <disposition> [resolution_details] [verdict_id]
  caveat-dispositions <item>
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
        elif subcmd == "verdict":
            if len(rest) < 4:
                _cli_usage_error(
                    "Usage: shepherd verdict <item> <transition> <worker> <verdict> "
                    "[caveats]"
                )
            if len(rest) > 5:
                # Older callers passed a 6th positional that referenced a
                # retired session-id column. Accept and ignore so stale callers
                # don't crash the verdict insert; warn so the operator notices.
                print(
                    "shepherd verdict: ignoring extra positional argument(s); "
                    "this subcommand accepts only [item, transition, worker, "
                    "verdict, caveats].",
                    file=sys.stderr,
                )
            caveats = rest[4] if len(rest) > 4 else None
            print(cmd_verdict(conn, rest[0], rest[1], rest[2], rest[3], caveats))
        elif subcmd == "shepherd-log":
            if not rest:
                _cli_usage_error("Usage: shepherd shepherd-log <item_id>")
            print(cmd_shepherd_log(conn, rest[0]))
        elif subcmd == "caveat-disposition":
            if len(rest) < 6:
                _cli_usage_error(
                    "Usage: shepherd caveat-disposition <item> <transition> <attempt> "
                    "<caveat_num> <caveat_text> <disposition> [resolution_details] [verdict_id]"
                )
            resolution = rest[6] if len(rest) > 6 else None
            verdict_id = int(rest[7]) if len(rest) > 7 else None
            cmd_caveat_disposition(
                conn,
                rest[0],
                rest[1],
                int(rest[2]),
                int(rest[3]),
                rest[4],
                rest[5],
                resolution,
                verdict_id,
            )
        elif subcmd == "caveat-dispositions":
            if not rest:
                _cli_usage_error("Usage: shepherd caveat-dispositions <item>")
            result = cmd_caveat_dispositions(conn, rest[0])
            if result:
                print(result)
        else:
            _cli_usage_error(_USAGE)
    except LookupError as exc:
        _cli_error(f"Error: {exc}", 1)
    except ValueError as exc:
        code = 2 if "invalid" in str(exc).lower() or "must be" in str(exc).lower() else 1
        _cli_error(f"Error: {exc}", code)
    except RuntimeError as exc:
        _cli_error(f"Error: {exc}", 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
