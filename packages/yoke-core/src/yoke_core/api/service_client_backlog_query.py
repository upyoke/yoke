"""Backlog read/list command handlers for the service_client CLI surface.

Owns ``backlog-dedup-search`` and ``backlog-list-cli`` — the two read paths
that render the public ``backlog-registry list`` and dedup-search output.
"""

from __future__ import annotations

import sys

from yoke_core.api.service_client_shared import (
    _get_db_readonly,
    queries,
)
# _parse_item_filters is the canonical helper used to parse filter flags
# for both backlog-list-cli and the items-side listing commands.  It lives
# in service_client_items_parsing.py — import directly from the canonical
# owner (no two-hop through the items shim).
from yoke_core.api.service_client_items_parsing import _parse_item_filters


def cmd_backlog_dedup_search(args: list[str]) -> int:
    """Search backlog titles and rendered bodies for duplicate-like matches."""
    from yoke_core.domain import backlog

    if len(args) != 1 or not args[0]:
        print("Usage: backlog-dedup-search <keywords>", file=sys.stderr)
        return 2

    for row in backlog.dedup_search(args[0]):
        print(f"YOK-{row['id']}: {row['title']} ({row['status']})")
    return 0


def cmd_backlog_list_cli(args: list[str]) -> int:
    """Render the public backlog-registry list output format in Python."""
    parsed = _parse_item_filters(args)
    if isinstance(parsed, int):
        return parsed
    filt, _ = parsed

    where_clause, params = queries.build_where_clause(filt)
    sql = (
        "SELECT id, title, type, status, priority "
        f"FROM items {where_clause} ORDER BY id"
    )

    print(f"{'ID':<8} {'Title':<50} {'Type':<8} {'Status':<14} {'Priority':<8}")
    print(f"{'------':<8} {'------------------------------------------------':<50} {'------':<8} {'------------':<14} {'------':<8}")

    conn = _get_db_readonly()
    try:
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            display_id = f"YOK-{row['id']}"
            display_title = (row["title"] or "")[:50]
            print(
                f"{display_id:<8} {display_title:<50} "
                f"{row['type']:<8} {row['status']:<14} {row['priority']:<8}"
            )
        return 0
    finally:
        conn.close()


__all__ = [
    "cmd_backlog_dedup_search",
    "cmd_backlog_list_cli",
]
