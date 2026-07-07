"""Harness sessions front-door CLI dispatch.

CLI usage::

    python3 -m runtime.harness.harness_sessions <subcmd> [args...]

Exit codes: 0 success, 1 error/not-found, 2 usage error.

Behavior lives in responsibility-named siblings:

- :mod:`runtime.harness.harness_sessions_focus` — focus/precondition
  helpers + identity/format primitives.
- :mod:`runtime.harness.harness_sessions_event_emit` — event emission
  helpers for harness_sessions / work_claims mutations.
- :mod:`runtime.harness.harness_sessions_lifecycle` — ``begin``,
  ``touch``, ``end``, ``get`` command handlers.
- :mod:`runtime.harness.harness_sessions_claims` — ``claim``,
  ``release``, ``release-all``, ``reclaim``, ``list-claims``,
  ``who-claims`` command handlers.
- :mod:`runtime.harness.harness_sessions_inventory` — read-only
  ``list`` and ``stale`` queries.

Public names (cmd_*) are re-exported here so legacy
``from runtime.harness.harness_sessions import cmd_*`` imports continue
to resolve.
"""
from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect

# Re-export public command surface — direct from the canonical owner of
# each name (no two-hop indirection sim-gap rule).
from runtime.harness.harness_sessions_claims import (  # noqa: F401
    cmd_claim,
    cmd_list_claims,
    cmd_reclaim,
    cmd_release,
    cmd_release_all,
    cmd_who_claims,
)
from runtime.harness.harness_sessions_inventory import (  # noqa: F401
    cmd_list,
    cmd_stale,
)
from runtime.harness.harness_sessions_lifecycle import (  # noqa: F401
    cmd_begin,
    cmd_end,
    cmd_get,
    cmd_touch,
)


_USAGE = """\
Usage: harness-sessions <subcmd> [args...]

Subcommands:
  begin <session-id> <executor> <provider> <model> <workspace> [lane] [mode]
  touch <session-id> [--mode M]
  end <session-id> [--force]
  claim <session-id> --target-kind {item|epic_task|process}
        --item-id N | --epic-id N --task-num K |
        --process-key KEY --conflict-group GROUP [--reason R]
  release <claim-id> [reason]
  release-all <session-id> [reason]
  reclaim <session-id>
  list
  list-claims <session-id>
  who-claims <item-id> [--current-episode]
  stale [threshold-minutes]
  get <session-id>

Run `<subcmd> --help` for per-subcommand worked examples.
"""

# Canonical per-subcommand help. Keyed by subcommand name; each value is a
# structured help block (usage / worked example / flag matrix / notes).
_SUBCOMMAND_HELP = {
    "who-claims": """\
Usage: harness-sessions who-claims <item-id> [--current-episode]

Resolve who holds work claims and path claims on a backlog item. Reads
the live ``work_claims`` and ``path_claims`` rows, returning the session
identity, claim state, and (with ``--current-episode``) the episode
scope used by Claude session-resumption audit.

Worked example:
  python3 -m runtime.harness.harness_sessions who-claims YOK-N
  python3 -m runtime.harness.harness_sessions who-claims YOK-N --current-episode

Flags:
  --current-episode   Append ``episode_scope=current_episode|inherited_from_prior_episode|unknown``
                      per claim row and an ``episode_boundary=<ts|none>`` line. Use
                      this to distinguish claims inherited across a Claude session
                      reactivation from claims acquired in the current episode.

Notes:
  - ``<item-id>`` accepts ``YOK-N`` or a bare integer.
  - Inherited claims remain valid across episode boundaries — audit
    output names the inheritance fact rather than hiding it.

Exit codes: 0 success, 1 not-found, 2 usage error.
""",
}


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

    if args[0] in ("-h", "--help", "help"):
        print(_USAGE, end="")
        sys.exit(0)

    subcmd = args[0]
    rest = args[1:]

    # Per-subcommand structured help — return 0 to stdout before any
    # downstream argument parsing rejects ``--help`` as a positional.
    if rest and rest[0] in ("-h", "--help"):
        help_text = _SUBCOMMAND_HELP.get(subcmd)
        if help_text is not None:
            print(help_text, end="")
            sys.exit(0)

    conn = connect()

    try:
        if subcmd == "begin":
            if len(rest) < 5:
                _cli_usage_error(
                    "Usage: harness-sessions begin <sid> <executor> <provider> "
                    "<model> <workspace> [lane] [mode]"
                )
            lane = rest[5] if len(rest) > 5 else "primary"
            mode = rest[6] if len(rest) > 6 else "wait"
            print(cmd_begin(conn, rest[0], rest[1], rest[2], rest[3], rest[4], lane, mode))

        elif subcmd == "touch":
            if not rest:
                _cli_usage_error("Usage: harness-sessions touch <session-id> [--mode M]")
            mode = None
            if len(rest) > 1:
                if rest[1] == "--mode" and len(rest) > 2:
                    mode = rest[2]
                elif rest[1] != "--mode":
                    mode = rest[1]
            print(cmd_touch(conn, rest[0], mode))

        elif subcmd == "end":
            if not rest:
                _cli_usage_error("Usage: harness-sessions end <session-id> [--force]")
            force = "--force" in rest
            print(cmd_end(conn, rest[0], force))

        elif subcmd == "claim":
            if len(rest) < 1:
                _cli_usage_error(
                    "Usage: harness-sessions claim <session-id> "
                    "--target-kind {item|epic_task|process} "
                    "[--item-id N | --epic-id N --task-num K | "
                    "--process-key KEY --conflict-group GROUP] "
                    "[--reason R]"
                )
            session_id = rest[0]
            kind = None
            item_id = epic_id = task_num = None
            process_key = conflict_group = None
            reason: Optional[str] = None
            i = 1
            while i < len(rest):
                if rest[i] == "--target-kind" and i + 1 < len(rest):
                    kind = rest[i + 1]
                    i += 2
                elif rest[i] == "--item-id" and i + 1 < len(rest):
                    item_id = int(rest[i + 1])
                    i += 2
                elif rest[i] == "--epic-id" and i + 1 < len(rest):
                    epic_id = int(rest[i + 1])
                    i += 2
                elif rest[i] == "--task-num" and i + 1 < len(rest):
                    task_num = int(rest[i + 1])
                    i += 2
                elif rest[i] == "--process-key" and i + 1 < len(rest):
                    process_key = rest[i + 1]
                    i += 2
                elif rest[i] == "--conflict-group" and i + 1 < len(rest):
                    conflict_group = rest[i + 1]
                    i += 2
                elif rest[i] == "--reason" and i + 1 < len(rest):
                    reason = rest[i + 1]
                    i += 2
                else:
                    _cli_usage_error(
                        f"Unrecognized claim arg: {rest[i]!r}; expected "
                        "--target-kind / --item-id / --epic-id / --task-num / "
                        "--process-key / --conflict-group / --reason"
                    )
            if kind is None:
                _cli_usage_error("--target-kind is required for claim")
            print(cmd_claim(
                conn, session_id, kind,
                item_id=item_id, epic_id=epic_id, task_num=task_num,
                process_key=process_key, conflict_group=conflict_group,
                reason=reason,
            ))

        elif subcmd == "release":
            if not rest:
                _cli_usage_error("Usage: harness-sessions release <claim-id> [reason]")
            reason = rest[1] if len(rest) > 1 else "released"
            print(cmd_release(conn, int(rest[0]), reason))

        elif subcmd == "release-all":
            if not rest:
                _cli_usage_error("Usage: harness-sessions release-all <session-id> [reason]")
            reason = rest[1] if len(rest) > 1 else "released"
            print(cmd_release_all(conn, rest[0], reason))

        elif subcmd == "reclaim":
            if not rest:
                _cli_usage_error("Usage: harness-sessions reclaim <session-id>")
            print(cmd_reclaim(conn, rest[0]))

        elif subcmd == "list":
            result = cmd_list(conn)
            if result:
                print(result)

        elif subcmd == "list-claims":
            if not rest:
                _cli_usage_error("Usage: harness-sessions list-claims <session-id>")
            result = cmd_list_claims(conn, rest[0])
            if result:
                print(result)

        elif subcmd == "who-claims":
            if not rest:
                _cli_usage_error(
                    "Usage: harness-sessions who-claims <item-id> "
                    "[--current-episode]"
                )
            current_episode = "--current-episode" in rest[1:]
            extra = [a for a in rest[1:] if a != "--current-episode"]
            if extra:
                _cli_usage_error(
                    f"Unrecognized who-claims arg: {extra[0]!r}; expected "
                    "[--current-episode]"
                )
            result = cmd_who_claims(
                conn, rest[0], current_episode=current_episode,
            )
            if result:
                print(result)

        elif subcmd == "stale":
            threshold = int(rest[0]) if rest else 10
            result = cmd_stale(conn, threshold)
            if result:
                print(result)

        elif subcmd == "get":
            if not rest:
                _cli_usage_error("Usage: harness-sessions get <session-id>")
            print(cmd_get(conn, rest[0]))

        else:
            _cli_usage_error(_USAGE)

    except LookupError as e:
        _cli_error(f"Error: {e}", 1)
    except PermissionError as e:
        _cli_error(f"Error: {e}", 1)
    except ValueError as e:
        _cli_error(f"Error: {e}", 2)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
