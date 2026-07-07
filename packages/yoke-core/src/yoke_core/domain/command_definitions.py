"""Read helpers for the ``command_definitions`` Project Structure family.

Concretizes the ``command_definitions`` replacement-family slot declared in
``yoke_core.domain.project_structure``.  Consumers that previously read the
four coarse ``projects.test_command_*`` columns (``quick``, ``full``, ``e2e``,
``smoke``) now read here.

Envelope (per path registry envelope contract slice-start declaration):

* **attachment:** ``project`` — commands are project-level, not path-scoped.
* **multiplicity:** ``keyed_set`` keyed by ``scope``.
* **identity:** ``(project_id, 'command_definitions', 'project', scope)``.
* **payload:** ``{"command": <str>}``. Empty or missing ⇒ "no command defined".

The closed ``scope`` vocabulary is ``{quick, full, e2e, smoke}``.

This module is a thin read wrapper.  Writes always go through the Project
Structure patch contract
(``python3 -m yoke_core.domain.project_structure patch``) so the audit log
and version lineage stay authoritative.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_one, query_rows
from yoke_core.domain.project_identity import resolve_project


#: Closed scope vocabulary for the ``command_definitions`` family. Matches the
#: set of legacy ``projects.test_command_*`` columns this family replaces.
SCOPES: Tuple[str, ...] = ("quick", "full", "e2e", "smoke")

#: Family name. Re-exported so consumers can reference a single constant
#: instead of the literal string.
FAMILY: str = "command_definitions"


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _payload_command(raw: Optional[str]) -> str:
    """Extract the ``command`` string from a payload JSON blob.

    Treats malformed payloads or missing ``command`` keys as empty so readers
    always see a clean string.  Parses the fetched ``payload`` in Python rather
    than extracting it in SQL.
    """
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    value = parsed.get("command", "")
    if not isinstance(value, str):
        return ""
    return value


def get_command(
    project_id: str,
    scope: str,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Return the command string for ``(project_id, scope)``.

    Returns ``None`` when the scope has no entry, the entry's ``command`` is
    empty, or the Project Structure tables have not been created yet (fresh
    DBs used by narrowly scoped tests).  The ``scope`` argument must be a
    member of :data:`SCOPES`; passing anything else raises :class:`ValueError`
    so callers don't silently skip.
    """
    if scope not in SCOPES:
        raise ValueError(
            f"Unknown command_definitions scope '{scope}'. "
            f"Known scopes: {', '.join(SCOPES)}."
        )
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project_id, required=False)
        if ident is None:
            return None
        p = _placeholder(conn)
        try:
            row = query_one(
                conn,
                "SELECT payload FROM project_structure "
                f"WHERE project_id={p} AND family={p} AND attachment_value='project' "
                f"AND entry_key={p}",
                (ident.id, FAMILY, scope),
            )
        except db_backend.operational_error_types():
            # ``project_structure`` not yet created on this DB. The error type
            # differs by backend (sqlite3.OperationalError vs psycopg
            # UndefinedTable), so match on the backend-resolved tuple.
            return None
        if row is None:
            return None
        cmd = _payload_command(row["payload"])
        return cmd or None
    finally:
        conn.close()


def list_commands(
    project_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, str]:
    """Return a mapping of ``scope -> command`` for ``project_id``.

    Only entries with a non-empty ``command`` are returned.  The mapping
    preserves canonical scope order (``quick``, ``full``, ``e2e``, ``smoke``).

    Returns an empty dict when the Project Structure tables do not exist yet
    (fresh DBs used by narrowly scoped tests).
    """
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project_id, required=False)
        if ident is None:
            return {}
        p = _placeholder(conn)
        try:
            rows = query_rows(
                conn,
                "SELECT entry_key, payload FROM project_structure "
                f"WHERE project_id={p} AND family={p} AND attachment_value='project' "
                "ORDER BY entry_key",
                (ident.id, FAMILY),
            )
        except db_backend.operational_error_types():
            # ``project_structure`` not yet created on this DB. Backend-resolved
            # error tuple so the swallow fires on both engines.
            return {}
    finally:
        conn.close()

    by_scope: Dict[str, str] = {}
    for row in rows:
        scope = row["entry_key"]
        if scope not in SCOPES:
            continue
        cmd = _payload_command(row["payload"])
        if cmd:
            by_scope[scope] = cmd

    return {s: by_scope[s] for s in SCOPES if s in by_scope}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_USAGE = """\
Usage: python3 -m yoke_core.domain.command_definitions <subcmd> [args...]

Subcommands:
  get <project-id> <scope>    Print the command for (project, scope).
                              Exits 0 with empty output when absent.
                              Exits 2 on unknown scope.
  list <project-id>           Print "scope=command" lines for every
                              defined scope (one per line, canonical order).
  scopes                      Print the closed scope vocabulary, one per line."""


def _cmd_get(args: argparse.Namespace) -> int:
    try:
        value = get_command(args.project_id, args.scope)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if value is not None:
        sys.stdout.write(value)
        if not value.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    commands = list_commands(args.project_id)
    for scope, command in commands.items():
        print(f"{scope}={command}")
    return 0


def _cmd_scopes(_: argparse.Namespace) -> int:
    for scope in SCOPES:
        print(scope)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.command_definitions",
        description=(
            "Read helpers for the command_definitions Project Structure "
            "family (path-continuity command registry)."
        ),
    )
    sub = parser.add_subparsers(dest="subcmd")

    p_get = sub.add_parser("get", help="Print command for (project, scope)")
    p_get.add_argument("project_id")
    p_get.add_argument("scope")

    p_list = sub.add_parser("list", help="List defined commands for a project")
    p_list.add_argument("project_id")

    sub.add_parser("scopes", help="Print the closed scope vocabulary")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args_in = argv if argv is not None else sys.argv[1:]
    if not args_in:
        print(_USAGE, file=sys.stderr)
        return 2
    parser = _build_parser()
    args = parser.parse_args(args_in)
    if args.subcmd is None:
        print(_USAGE, file=sys.stderr)
        return 2
    dispatch = {
        "get": _cmd_get,
        "list": _cmd_list,
        "scopes": _cmd_scopes,
    }
    handler = dispatch.get(args.subcmd)
    if handler is None:  # pragma: no cover - argparse guards this
        print(_USAGE, file=sys.stderr)
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
