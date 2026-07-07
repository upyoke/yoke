"""Release notes domain logic (invoked via ``python3 -m yoke_core.domain.release_notes``).

Manages the ``release_entries`` table: per-item release note entries
with category classification and project/version scoping.

CLI usage::

    python3 -m yoke_core.domain.release_notes <subcmd> [args...]

All output uses pipe-delimited format matching the CLI contract.
Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now, query_one, query_rows, query_scalar
from yoke_core.domain.project_identity import resolve_project_id

VALID_CATEGORIES = frozenset({"features", "improvements", "bug_fixes", "internal"})

_USAGE = """\
Usage: release-notes <subcmd> [args...]

Subcommands:
  insert <item_id> <category> <title> [version] [--project <name>]
  exists <item_id> [version] [--project <name>]
  list [version] [--project <name>]
"""

_UNKNOWN_USAGE = """\
Usage: release-notes <insert|exists|list> [args...]

Subcommands:
  insert <item_id> <category> <title> [version] [--project <name>]  Insert a release entry
  exists <item_id> [version] [--project <name>]                     Exit 0 if entry exists
  list [version] [--project <name>]                                 List entries
"""


def _cli_error(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _cli_usage_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_version() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_item_id(raw: str) -> int:
    """Parse item ID, stripping YOK- prefix and leading zeros."""
    import re
    cleaned = re.sub(r"^[Yy][Oo][Kk]-", "", raw).lstrip("0") or "0"
    return int(cleaned)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_item_project(conn, item_id: int) -> str:
    """Resolve project for an item, falling back to 'yoke'."""
    row = query_scalar(
        conn,
        "SELECT p.slug FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id={_p(conn)}",
        (item_id,),
    )
    return row if row else "yoke"


# --- Domain functions ---

def cmd_insert(conn, item_id: int, category: str, title: str,
               version: Optional[str] = None, project: Optional[str] = None) -> str:
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"invalid category '{category}'. "
            f"Must be: {', '.join(sorted(VALID_CATEGORIES))}"
        )
    if not version:
        version = _current_version()
    if not project:
        project = _resolve_item_project(conn, item_id)
    project_id = resolve_project_id(conn, project)

    conn.execute(
        "INSERT INTO release_entries "
        "(item_id, category, title, version, project_id, created_at) "
        f"VALUES ({_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}) "
        "ON CONFLICT(item_id, version, project_id) DO UPDATE SET "
        "category=EXCLUDED.category, title=EXCLUDED.title, "
        "created_at=EXCLUDED.created_at",
        (item_id, category, title, version, project_id, iso8601_now()),
    )
    conn.commit()
    return f"Release entry: YOK-{item_id} -> {category} ({version}, project={project})"


def cmd_exists(conn, item_id: int, version: Optional[str] = None,
               project: Optional[str] = None) -> bool:
    if not version:
        version = _current_version()

    if project:
        project_id = resolve_project_id(conn, project)
        count = query_scalar(
            conn,
            "SELECT COUNT(*) FROM release_entries "
            f"WHERE item_id={_p(conn)} AND version={_p(conn)} AND project_id={_p(conn)}",
            (item_id, version, project_id),
        )
    else:
        count = query_scalar(
            conn,
            f"SELECT COUNT(*) FROM release_entries WHERE item_id={_p(conn)} AND version={_p(conn)}",
            (item_id, version),
        )
    return (count or 0) > 0


def cmd_list(conn, version: Optional[str] = None,
             project: Optional[str] = None) -> str:
    conditions: List[str] = []
    params: list = []

    if version:
        conditions.append(f"version={_p(conn)}")
        params.append(version)
    if project:
        conditions.append(f"r.project_id={_p(conn)}")
        params.append(resolve_project_id(conn, project))

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = "ORDER BY category, item_id" if version else "ORDER BY version DESC, category, item_id"

    rows = query_rows(
        conn,
        "SELECT r.item_id, r.category, r.title, r.version, p.slug, r.created_at "
        "FROM release_entries r LEFT JOIN projects p ON p.id = r.project_id "
        f"{where} {order}",
        tuple(params),
    )
    lines = []
    for row in rows:
        lines.append("|".join("" if v is None else str(v) for v in tuple(row)))
    return "\n".join(lines)


# --- CLI entry point ---

def main(argv: Optional[List[str]] = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        _cli_usage_error(_USAGE)

    subcmd = args[0]
    rest = args[1:]

    conn = connect()

    try:
        if subcmd == "insert":
            # Parse: positional args + optional --project flag
            item_id_raw = None
            category = None
            title = None
            version = None
            project = None
            positionals: list = []
            i = 0
            while i < len(rest):
                if rest[i] == "--project" and i + 1 < len(rest):
                    project = rest[i + 1]
                    i += 2
                else:
                    positionals.append(rest[i])
                    i += 1

            if len(positionals) < 3:
                _cli_usage_error(
                    "Usage: release insert <item_id> <category> <title> "
                    "[version] [--project <name>]"
                )
            item_id = _parse_item_id(positionals[0])
            category = positionals[1]
            title = positionals[2]
            version = positionals[3] if len(positionals) > 3 else None

            print(cmd_insert(conn, item_id, category, title, version, project))

        elif subcmd == "exists":
            item_id_raw = None
            version = None
            project = None
            positionals = []
            i = 0
            while i < len(rest):
                if rest[i] == "--project" and i + 1 < len(rest):
                    project = rest[i + 1]
                    i += 2
                else:
                    positionals.append(rest[i])
                    i += 1

            if len(positionals) < 1:
                _cli_usage_error(
                    "Usage: release exists <item_id> [version] [--project <name>]"
                )
            item_id = _parse_item_id(positionals[0])
            version = positionals[1] if len(positionals) > 1 else None

            if cmd_exists(conn, item_id, version, project):
                sys.exit(0)
            else:
                sys.exit(1)

        elif subcmd == "list":
            version = None
            project = None
            positionals = []
            i = 0
            while i < len(rest):
                if rest[i] == "--project" and i + 1 < len(rest):
                    project = rest[i + 1]
                    i += 2
                else:
                    positionals.append(rest[i])
                    i += 1

            version = positionals[0] if positionals else None
            result = cmd_list(conn, version, project)
            if result:
                print(result)

        else:
            _cli_error(_UNKNOWN_USAGE, 1)

    except ValueError as e:
        _cli_error(f"Error: {e}", 1)
    except LookupError as e:
        _cli_error(f"Error: {e}", 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
