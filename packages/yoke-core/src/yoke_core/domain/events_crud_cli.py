"""CLI dispatcher for ``python3 -m yoke_core.domain.events_crud``.

Exit codes: 0 success, 1 not-found, 2 usage. All ``cmd_*`` lookups go through
the ``events_crud`` module attribute so test-time monkeypatches flow through.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from yoke_core.domain import events_crud as _ec
from yoke_core.domain.events_registry_cli import cli_registry


# Flag → kwarg mapping for the ``insert`` subcommand. Preserved verbatim as
# external CLI consumers depend on each name (see Cross-Script Contracts).
_INSERT_FLAG_MAP = {
    f"--{k.replace('_', '-')}": k
    for k in (
        "event_id",
        "source_type",
        "session_id",
        "severity",
        "event_kind",
        "event_type",
        "event_name",
        "event_outcome",
        "org_id",
        "actor_id",
        "environment",
        "service",
        "project",
        "item_id",
        "task_num",
        "agent",
        "tool_name",
        "duration_ms",
        "exit_code",
        "trace_id",
        "anomaly_flags",
        "envelope",
        "tool_use_id",
        "turn_id",
        "hook_event_name",
    )
}

_TOP_USAGE = (
    "Usage: events_crud <subcommand> [args...]\n"
    "\n"
    "Subcommands:\n"
    "  init, insert, list, query, count, anomalies, prune, tail,\n"
    "  severity-config, severity-check, registry"
)


def _cli_insert(argv: list[str]) -> int:
    """Parse CLI flags for insert and call cmd_insert."""
    kwargs: dict[str, Any] = {}
    db_path = os.environ.get("YOKE_DB")
    i = 0
    while i < len(argv):
        flag = argv[i]
        if flag == "--skip-severity":
            kwargs["skip_severity"] = True
        elif flag in _INSERT_FLAG_MAP:
            i += 1
            val = argv[i]
            key = _INSERT_FLAG_MAP[flag]
            if key in ("actor_id", "task_num", "duration_ms", "exit_code"):
                val = int(val)
            kwargs[key] = val
        else:
            print(f"Error: unknown flag '{flag}'", file=sys.stderr)
            return 2
        i += 1

    for req in (
        "event_id",
        "source_type",
        "session_id",
        "event_kind",
        "event_type",
        "event_name",
    ):
        if req not in kwargs:
            print(f"Error: --{req.replace('_', '-')} is required", file=sys.stderr)
            return 2

    try:
        _ec.cmd_insert(db_path, **kwargs)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(_TOP_USAGE, file=sys.stderr)
        return 2

    subcmd = argv[0]
    rest = argv[1:]
    db_path = os.environ.get("YOKE_DB")

    if subcmd == "init":
        _ec.cmd_init(db_path)
        return 0

    if subcmd == "insert":
        return _cli_insert(rest)

    if subcmd == "list":
        from yoke_core.domain.events_queries import cli_list

        return cli_list(db_path, rest)

    if subcmd == "query":
        if not rest:
            print("Usage: events_crud query <sql>", file=sys.stderr)
            return 2
        try:
            result = _ec.cmd_query(db_path, rest[0])
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        if result:
            print(result)
        return 0

    if subcmd == "count":
        from yoke_core.domain.events_queries import cli_count

        return cli_count(db_path, rest)
    if subcmd == "anomalies":
        from yoke_core.domain.events_queries import cli_anomalies

        return cli_anomalies(db_path, rest)
    if subcmd == "prune":
        try:
            print(_ec.cmd_prune(db_path, **_ec.prune_cli_kwargs(rest)))
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return 0

    if subcmd == "tail":
        limit = 20
        if rest:
            raw = rest[1] if rest[0] == "--limit" and len(rest) >= 2 else rest[0]
            if rest[0] == "--limit" and len(rest) < 2:
                print("Usage: events_crud tail [N|--limit N]", file=sys.stderr)
                return 2
            try:
                limit = int(raw)
            except ValueError:
                print(
                    "Error: tail limit must be a non-negative integer", file=sys.stderr
                )
                return 2
        result = _ec.cmd_tail(db_path, limit)
        if result:
            print(result)
        return 0

    if subcmd == "severity-config":
        action = rest[0] if rest else None
        if action == "set":
            args = rest[1:]
            ev = args[0] if len(args) > 0 else "*"
            src = args[1] if len(args) > 1 else "*"
            sev = args[2] if len(args) > 2 else "INFO"
            try:
                print(_ec.cmd_severity_config_set(db_path, ev, src, sev))
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 2
            return 0
        if action == "list":
            result = _ec.cmd_severity_config_list(db_path)
            if result:
                print(result)
            return 0
        print("Usage: events_crud severity-config <set|list>", file=sys.stderr)
        return 2

    if subcmd == "severity-check":
        if len(rest) < 3:
            print(
                "Usage: events_crud severity-check <event_name> <source_type> <severity>",
                file=sys.stderr,
            )
            return 2
        print(_ec.cmd_severity_check(db_path, rest[0], rest[1], rest[2]))
        return 0

    if subcmd == "registry":
        return cli_registry(rest)

    print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
