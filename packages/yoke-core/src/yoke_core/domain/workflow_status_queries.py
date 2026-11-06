"""Pinned-workflow predicates for item scans."""

from __future__ import annotations
from yoke_core.domain import db_backend
from yoke_core.domain.frontier_workflow_versions import load_frontier_workflow_versions


def exclude_terminal_items(conn, *, alias: str = "i"):
    """Return an AND clause and parameters for nonterminal items."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    return load_frontier_workflow_versions(conn).skip_clause(
        marker,
        alias=alias,
        statuses=lambda runtime: runtime.all_terminal_stage_ids,
    )
