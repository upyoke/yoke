"""Registry subcommands for ``python3 -m yoke_core.domain.events_crud``.

Lookups go through the ``events_crud`` module attribute so test-time
monkeypatches flow through.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from yoke_core.domain import events_crud as _ec

_REG_ADD_FLAGS = {
    f"--{k.replace('_', '-')}": k
    for k in (
        "kind",
        "service",
        "description",
        "context_schema",
        "severity",
        "added_in",
    )
}
_REG_ADD_FLAGS["--type"] = "event_type"

_REG_UPDATE_FLAGS = {
    f"--{k.replace('_', '-')}": k
    for k in (
        "description",
        "context_schema",
        "event_kind",
        "event_type",
        "severity",
        "status",
    )
}

_REG_USAGE = (
    "Usage: events_crud registry <subcommand> [args...]\n"
    "\n"
    "Subcommands:\n"
    "  add <name> --kind K --type T --service S --description D [opts]\n"
    "  get <name>\n"
    "  list [--status S] [--kind K] [--service S]\n"
    "  update <name> [--event-kind K] [--event-type T] [--description D]"
    " [--severity L] [--status S]\n"
    "  deprecate <name>\n"
    "  delete <name>\n"
    "  count [--status S]\n"
    "  discover\n"
    "  audit\n"
    "  diff [--verbose]"
)


def cli_registry(argv: list[str]) -> int:
    """Parse CLI args for registry subcommands."""
    db_path = os.environ.get("YOKE_DB")
    if not argv:
        print("Usage: events_crud registry <subcommand> [args...]", file=sys.stderr)
        return 2

    sub = argv[0]
    rest = argv[1:]

    if sub == "add":
        return _registry_add(db_path, rest)
    if sub == "get":
        return _registry_get(db_path, rest)
    if sub == "list":
        return _registry_list(db_path, rest)
    if sub == "update":
        return _registry_update(db_path, rest)
    if sub in ("deprecate", "delete"):
        return _registry_retire(db_path, sub, rest)
    if sub == "count":
        return _registry_count(db_path, rest)
    if sub == "discover":
        result = _ec.cmd_registry_discover()
        if result:
            print(result)
        return 0
    if sub == "audit":
        return _registry_audit(db_path)
    if sub == "diff":
        return _registry_diff(db_path, rest)
    print(_REG_USAGE, file=sys.stderr)
    return 2


def _registry_add(db_path: str | None, rest: list[str]) -> int:
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
            msg = (
                "Error: event_name is required"
                if req == "name"
                else f"Error: --{req.replace('_', '-')} is required"
            )
            print(msg, file=sys.stderr)
            return 2
    _ec.cmd_registry_add(db_path, **kwargs)
    return 0


def _registry_get(db_path: str | None, rest: list[str]) -> int:
    if not rest:
        print("Error: event_name is required", file=sys.stderr)
        return 2
    try:
        print(_ec.cmd_registry_get(db_path, rest[0]))
    except LookupError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def _registry_list(db_path: str | None, rest: list[str]) -> int:
    kwargs = {"status": "active", "kind": None, "service": None}
    i = 0
    while i < len(rest):
        if rest[i] == "--status":
            i += 1
            kwargs["status"] = rest[i]
        elif rest[i] == "--kind":
            i += 1
            kwargs["kind"] = rest[i]
        elif rest[i] == "--service":
            i += 1
            kwargs["service"] = rest[i]
        i += 1
    result = _ec.cmd_registry_list(db_path, **kwargs)
    if result:
        print(result)
    return 0


def _registry_update(db_path: str | None, rest: list[str]) -> int:
    if not rest:
        print("Error: event_name is required", file=sys.stderr)
        return 2
    name = rest[0]
    kwargs: dict[str, Any] = {}
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


def _registry_retire(db_path: str | None, sub: str, rest: list[str]) -> int:
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


def _registry_count(db_path: str | None, rest: list[str]) -> int:
    status = None
    i = 0
    while i < len(rest):
        if rest[i] == "--status":
            i += 1
            status = rest[i]
        i += 1
    print(_ec.cmd_registry_count(db_path, status))
    return 0


def _registry_audit(db_path: str | None) -> int:
    try:
        print(_ec.cmd_registry_audit(db_path))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def _registry_diff(db_path: str | None, rest: list[str]) -> int:
    try:
        print(_ec.cmd_registry_diff(db_path, verbose="--verbose" in rest))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0
