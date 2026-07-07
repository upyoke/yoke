"""CLI dispatcher for ``python3 -m yoke_core.domain.events_crud``.

Exit codes: 0 success, 1 not-found, 2 usage. All ``cmd_*`` lookups go through
the ``events_crud`` module attribute so test-time monkeypatches flow through.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from yoke_core.domain import events_crud as _ec


# Flag → kwarg mapping for the ``insert`` subcommand. Preserved verbatim as
# external CLI consumers depend on each name (see Cross-Script Contracts).
_INSERT_FLAG_MAP = {f"--{k.replace('_', '-')}": k for k in (
    "event_id", "source_type", "session_id", "severity", "event_kind",
    "event_type", "event_name", "event_outcome", "user_id", "org_id",
    "actor_id", "environment", "service", "project", "item_id", "task_num",
    "agent", "tool_name", "duration_ms", "exit_code", "trace_id",
    "parent_id", "anomaly_flags", "envelope", "tool_use_id", "turn_id",
    "hook_event_name",
)}

# Registry add: --type maps to event_type; everything else is its kwarg name.
_REG_ADD_FLAGS = {f"--{k.replace('_', '-')}": k for k in (
    "kind", "service", "description", "context_schema", "severity", "added_in",
)}
_REG_ADD_FLAGS["--type"] = "event_type"

_REG_UPDATE_FLAGS = {f"--{k.replace('_', '-')}": k for k in (
    "description", "context_schema", "event_kind", "event_type", "severity", "status",
)}

_REG_USAGE = (
    "Usage: events_crud registry <subcommand> [args...]\n"
    "\n"
    "Subcommands:\n"
    "  add <name> --kind K --type T --service S --description D [opts]\n"
    "  get <name>\n"
    "  list [--status S] [--kind K] [--service S]\n"
    "  update <name> [--event-kind K] [--event-type T] [--description D] [--severity L] [--status S]\n"
    "  deprecate <name>\n"
    "  delete <name>\n"
    "  count [--status S]\n"
    "  discover\n"
    "  audit\n"
    "  diff [--verbose]"
)

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

    for req in ("event_id", "source_type", "session_id", "event_kind", "event_type", "event_name"):
        if req not in kwargs:
            print(f"Error: --{req.replace('_', '-')} is required", file=sys.stderr)
            return 2

    try:
        _ec.cmd_insert(db_path, **kwargs)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


def _cli_registry(argv: list[str]) -> int:
    """Parse CLI args for registry subcommands."""
    db_path = os.environ.get("YOKE_DB")
    if not argv:
        print("Usage: events_crud registry <subcommand> [args...]", file=sys.stderr)
        return 2

    sub = argv[0]
    rest = argv[1:]

    if sub == "add":
        kwargs: dict[str, Any] = {"name": ""}
        i = 0
        while i < len(rest):
            flag = rest[i]
            if flag.startswith("-"):
                if flag in _REG_ADD_FLAGS:
                    i += 1
                    kwargs[_REG_ADD_FLAGS[flag]] = rest[i]
                else:
                    print(f"Error: unknown flag '{flag}'", file=sys.stderr)
                    return 2
            elif not kwargs["name"]:
                kwargs["name"] = flag
            else:
                print(f"Error: unexpected argument '{flag}'", file=sys.stderr)
                return 2
            i += 1
        for req in ("name", "kind", "event_type", "service", "description"):
            if not kwargs.get(req):
                msg = "Error: event_name is required" if req == "name" else f"Error: --{req.replace('_', '-')} is required"
                print(msg, file=sys.stderr)
                return 2
        _ec.cmd_registry_add(db_path, **kwargs)
        return 0

    if sub == "get":
        if not rest:
            print("Error: event_name is required", file=sys.stderr)
            return 2
        try:
            print(_ec.cmd_registry_get(db_path, rest[0]))
        except LookupError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    if sub == "list":
        kwargs = {"status": "active", "kind": None, "service": None}
        i = 0
        while i < len(rest):
            if rest[i] == "--status":
                i += 1; kwargs["status"] = rest[i]
            elif rest[i] == "--kind":
                i += 1; kwargs["kind"] = rest[i]
            elif rest[i] == "--service":
                i += 1; kwargs["service"] = rest[i]
            i += 1
        result = _ec.cmd_registry_list(db_path, **kwargs)
        if result:
            print(result)
        return 0

    if sub == "update":
        if not rest:
            print("Error: event_name is required", file=sys.stderr)
            return 2
        name = rest[0]
        kwargs = {}
        i = 1
        while i < len(rest):
            if rest[i] in _REG_UPDATE_FLAGS:
                key = _REG_UPDATE_FLAGS[rest[i]]
                i += 1
                kwargs[key] = rest[i]
            i += 1
        if not kwargs:
            print("Error: no fields to update", file=sys.stderr)
            return 2
        try:
            _ec.cmd_registry_update(db_path, name, **kwargs)
        except LookupError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    if sub in ("deprecate", "delete"):
        if not rest:
            print("Error: event_name is required", file=sys.stderr)
            return 2
        fn = _ec.cmd_registry_deprecate if sub == "deprecate" else _ec.cmd_registry_delete
        try:
            fn(db_path, rest[0])
        except LookupError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    if sub == "count":
        status = None
        i = 0
        while i < len(rest):
            if rest[i] == "--status":
                i += 1; status = rest[i]
            i += 1
        print(_ec.cmd_registry_count(db_path, status))
        return 0

    if sub == "discover":
        result = _ec.cmd_registry_discover()
        if result:
            print(result)
        return 0

    if sub == "audit":
        try:
            print(_ec.cmd_registry_audit(db_path))
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    if sub == "diff":
        try:
            print(_ec.cmd_registry_diff(db_path, verbose="--verbose" in rest))
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    print(_REG_USAGE, file=sys.stderr)
    return 2


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
        print(_ec.cmd_prune(db_path, "--dry-run" in rest))
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
                print("Error: tail limit must be a non-negative integer", file=sys.stderr)
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
            print("Usage: events_crud severity-check <event_name> <source_type> <severity>", file=sys.stderr)
            return 2
        print(_ec.cmd_severity_check(db_path, rest[0], rest[1], rest[2]))
        return 0

    if subcmd == "registry":
        return _cli_registry(rest)

    print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
