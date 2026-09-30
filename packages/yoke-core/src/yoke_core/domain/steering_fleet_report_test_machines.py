"""Test-host OS facts in a project fleet report, separate from launch capacity."""

from __future__ import annotations
import json
from typing import Any
from yoke_core.domain.schema_common import _table_exists


def read_test_machines(conn: Any, project_id: int) -> tuple[tuple[str, str], ...]:
    if not _table_exists(conn, "project_capabilities"):
        return ()
    rows = conn.execute(
        "SELECT type, settings FROM project_capabilities WHERE project_id = %s "
        "AND type LIKE %s ORDER BY type",
        (project_id, "test-machine:%"),
    ).fetchall()
    result = []
    for row in rows:
        settings = json.loads(str(row[1] or "{}"))
        result.append(
            (
                str(row[0]).split(":", 1)[1],
                str(settings.get("os") or "requires next-release serving build"),
            )
        )
    return tuple(result)


def test_machine_lines(rows: tuple[tuple[str, str], ...]) -> list[str]:
    if not rows:
        return []
    return ["Test Machines: " + "; ".join(f"{name} (OS: {os})" for name, os in rows)]
