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
from yoke_core.domain.project_identity import format_item_ref, render_item_ref


def cmd_backlog_dedup_search(args: list[str]) -> int:
    """Search backlog titles and rendered bodies for duplicate-like matches."""
    from yoke_core.domain import backlog

    if len(args) != 1 or not args[0]:
        print("Usage: backlog-dedup-search <keywords>", file=sys.stderr)
        return 2

    conn = _get_db_readonly()
    try:
        for row in backlog.dedup_search(args[0]):
            ref = render_item_ref(conn, int(row["id"]))
            print(f"{ref}: {row['title']} ({row['status']})")
    finally:
        conn.close()
    return 0


def cmd_backlog_list_cli(args: list[str]) -> int:
    """Render the public backlog-registry list output format in Python."""
    parsed = _parse_item_filters(args)
    if isinstance(parsed, int):
        return parsed
    filt, _ = parsed

    where_clause, params = queries.build_where_clause(filt, table_prefix="i.")
    sql = (
        "SELECT i.id, i.title, i.workflow_id, i.status, i.priority, "
        "p.public_item_prefix, i.project_sequence, p.slug AS project_slug "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        f"{where_clause} ORDER BY i.id"
    )

    print(f"{'ID':<8} {'Title':<50} {'Workflow':<12} {'Status':<14} {'Priority':<8}")
    print(f"{'------':<8} {'------------------------------------------------':<50} {'------':<8} {'------------':<14} {'------':<8}")

    conn = _get_db_readonly()
    try:
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            display_id = format_item_ref(
                row["project_slug"],
                row["public_item_prefix"],
                row["project_sequence"],
                item_id=row["id"],
            )
            display_title = (row["title"] or "")[:50]
            print(
                f"{display_id:<8} {display_title:<50} "
                f"{row['workflow_id']:<12} {row['status']:<14} {row['priority']:<8}"
            )
        return 0
    finally:
        conn.close()


__all__ = [
    "cmd_backlog_dedup_search",
    "cmd_backlog_list_cli",
]
