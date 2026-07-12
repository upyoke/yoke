"""Designs domain logic (invoked via ``python3 -m yoke_core.domain.designs``).

Manages the ``designs`` table: one design document per backlog item,
with filesystem sync.

CLI usage::

    python3 -m yoke_core.domain.designs <subcmd> [args...]

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.schema_init_apply import execute_schema_script

_USAGE = """\
Usage: designs <subcmd> [args...]

Subcommands:
  init                                         Ensure designs table exists
  upsert <item_id> <slug> --body-file <path>   Insert or update a design
  get <item_id>                                Get design (pipe-delimited)
  get-body <item_id>                           Get raw design body text
  exists <item_id>                             Check if design exists
  list                                         List all designs
  sync <item_id>                               Write design to file
  sync-all                                     Write all designs to files
"""


def _cli_error(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _cli_usage_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _parse_item_id(raw: str) -> int:
    cleaned = re.sub(r"^[Yy][Oo][Kk]-", "", raw).lstrip("0") or "0"
    if not cleaned.isdigit():
        raise ValueError(f"invalid item_id '{raw}'")
    return int(cleaned)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_designs_dir() -> str:
    """Resolve the designs directory path."""
    from yoke_core.domain.db_helpers import resolve_db_path

    db_path = resolve_db_path()
    yoke_root = os.path.dirname(db_path)
    designs_dir = os.path.join(yoke_root, "designs")
    # guard against sibling-state directory creation.
    from yoke_core.domain.schema import guard_state_dir_creation

    guard_state_dir_creation(designs_dir, "designs._resolve_designs_dir")
    return designs_dir


_INIT_SQL = """\
CREATE TABLE IF NOT EXISTS designs (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    slug TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(item_id)
);
CREATE INDEX IF NOT EXISTS idx_designs_item ON designs(item_id);
CREATE INDEX IF NOT EXISTS idx_designs_slug ON designs(slug);
"""


def cmd_init(conn) -> str:
    execute_schema_script(conn, _INIT_SQL)
    conn.commit()
    return "Designs table initialized"


def cmd_upsert(conn, item_id: int, slug: str, body_file: str) -> str:
    if not os.path.isfile(body_file):
        raise FileNotFoundError(f"body file not found: {body_file}")

    with open(body_file, "r", encoding="utf-8") as f:
        body = f.read()

    now = iso8601_now()
    p = _p(conn)
    existing = query_one(conn, f"SELECT id FROM designs WHERE item_id={p}", (item_id,))
    if existing:
        conn.execute(
            f"UPDATE designs SET slug={p}, body={p}, updated_at={p} WHERE item_id={p}",
            (slug, body, now, item_id),
        )
        conn.commit()
        return f"Updated design: YOK-{item_id} ({slug})"
    else:
        conn.execute(
            "INSERT INTO designs (item_id, slug, body, created_at, updated_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            (item_id, slug, body, now, now),
        )
        conn.commit()
        return f"Inserted design: YOK-{item_id} ({slug})"


def cmd_get(conn, item_id: int) -> str:
    p = _p(conn)
    row = query_one(
        conn,
        "SELECT id, item_id, slug, body, created_at, updated_at "
        f"FROM designs WHERE item_id={p} LIMIT 1",
        (item_id,),
    )
    if row is None:
        raise LookupError(f"no design found for YOK-{item_id}")
    return "|".join("" if v is None else str(v) for v in tuple(row))


def cmd_get_body(conn, item_id: int) -> str:
    p = _p(conn)
    row = query_one(
        conn,
        f"SELECT COALESCE(body, '') FROM designs WHERE item_id={p} LIMIT 1",
        (item_id,),
    )
    if row is None:
        raise LookupError(f"no design found for YOK-{item_id}")
    return row[0]


def cmd_exists(conn, item_id: int) -> bool:
    p = _p(conn)
    count = query_scalar(
        conn, f"SELECT COUNT(*) FROM designs WHERE item_id={p}", (item_id,)
    )
    return (count or 0) > 0


def cmd_list(conn) -> str:
    rows = query_rows(
        conn,
        "SELECT id, item_id, slug, created_at, updated_at "
        "FROM designs ORDER BY item_id ASC",
    )
    lines = []
    for row in rows:
        lines.append("|".join("" if v is None else str(v) for v in tuple(row)))
    return "\n".join(lines)


def cmd_sync(conn, item_id: int, designs_dir: Optional[str] = None) -> str:
    p = _p(conn)
    row = query_one(
        conn, f"SELECT slug, body FROM designs WHERE item_id={p}", (item_id,)
    )
    if row is None:
        raise LookupError(f"no design found for YOK-{item_id}")

    slug, body = row["slug"], row["body"]
    if not designs_dir:
        designs_dir = _resolve_designs_dir()
    os.makedirs(designs_dir, exist_ok=True)
    out_path = os.path.join(designs_dir, f"{slug}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    return f"Synced: YOK-{item_id} -> {out_path}"


def cmd_sync_all(conn, designs_dir: Optional[str] = None) -> str:
    rows = query_rows(conn, "SELECT item_id, slug, body FROM designs ORDER BY item_id")
    if not rows:
        return "No designs to sync."

    if not designs_dir:
        designs_dir = _resolve_designs_dir()
    os.makedirs(designs_dir, exist_ok=True)

    lines = []
    for row in rows:
        item_id, slug, body = row["item_id"], row["slug"], row["body"]
        out_path = os.path.join(designs_dir, f"{slug}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(body)
        lines.append(f"Synced: YOK-{item_id} -> {out_path}")
    lines.append(f"Synced {len(rows)} design(s).")
    return "\n".join(lines)


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

        elif subcmd == "upsert":
            if len(rest) < 4 or rest[2] != "--body-file":
                _cli_usage_error(
                    "Usage: designs upsert <item_id> <slug> --body-file <path>"
                )
            item_id = _parse_item_id(rest[0])
            slug = rest[1]
            body_file = rest[3]
            # Auto-init
            cmd_init(conn)
            print(cmd_upsert(conn, item_id, slug, body_file))

        elif subcmd == "get":
            if not rest:
                _cli_usage_error("Usage: designs get <item_id>")
            item_id = _parse_item_id(rest[0])
            cmd_init(conn)
            print(cmd_get(conn, item_id))

        elif subcmd == "get-body":
            if not rest:
                _cli_usage_error("Usage: designs get-body <item_id>")
            item_id = _parse_item_id(rest[0])
            cmd_init(conn)
            print(cmd_get_body(conn, item_id))

        elif subcmd == "exists":
            if not rest:
                _cli_usage_error("Usage: designs exists <item_id>")
            item_id = _parse_item_id(rest[0])
            cmd_init(conn)
            exists = cmd_exists(conn, item_id)
            print("true" if exists else "false")
            sys.exit(0 if exists else 1)

        elif subcmd == "list":
            cmd_init(conn)
            result = cmd_list(conn)
            if result:
                print(result)

        elif subcmd == "sync":
            if not rest:
                _cli_usage_error("Usage: designs sync <item_id>")
            item_id = _parse_item_id(rest[0])
            cmd_init(conn)
            print(cmd_sync(conn, item_id))

        elif subcmd == "sync-all":
            cmd_init(conn)
            print(cmd_sync_all(conn))

        else:
            _cli_usage_error(_USAGE)

    except FileNotFoundError as e:
        _cli_error(f"Error: {e}", 1)
    except LookupError as e:
        _cli_error(f"Error: {e}", 1)
    except ValueError as e:
        _cli_error(f"Error: {e}", 2)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
