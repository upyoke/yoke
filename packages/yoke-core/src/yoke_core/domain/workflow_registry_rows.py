"""Shared workflow-registry row readers."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.workflow_registry_sql import marker, row_dict


def workflow_row(conn: Any, workflow_id: str) -> Optional[dict]:
    bind = marker(conn)
    cursor = conn.execute(
        f"SELECT * FROM workflows WHERE id = {bind}",
        (workflow_id,),
    )
    return row_dict(cursor, cursor.fetchone())


def version_row(
    conn: Any,
    workflow_id: str,
    version: int,
) -> Optional[dict]:
    bind = marker(conn)
    cursor = conn.execute(
        "SELECT * FROM workflow_versions "
        f"WHERE workflow_id = {bind} AND version = {bind}",
        (workflow_id, version),
    )
    return row_dict(cursor, cursor.fetchone())


def version_by_id(conn: Any, version_id: int) -> Optional[dict]:
    bind = marker(conn)
    cursor = conn.execute(
        f"SELECT * FROM workflow_versions WHERE id = {bind}",
        (version_id,),
    )
    return row_dict(cursor, cursor.fetchone())


__all__ = ["version_by_id", "version_row", "workflow_row"]
