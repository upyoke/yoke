"""Project, harness and machine facets for ended session history."""

from __future__ import annotations

from typing import Any, Sequence
from yoke_core.domain.project_identity import row_value


_MACHINE_NAME = (
    "(SELECT sr.hostname FROM session_relays sr "
    "WHERE sr.machine_id = s.machine_id AND sr.hostname IS NOT NULL "
    "ORDER BY sr.last_seen_at DESC LIMIT 1)"
)


def _facet_rows(conn: Any, clauses: Sequence[str], params: Sequence[Any]) -> dict:
    where = "WHERE " + " AND ".join(clauses)
    projects = conn.execute(
        "SELECT DISTINCT pr.id, pr.slug FROM harness_sessions s "
        "LEFT JOIN projects pr ON pr.id = s.project_id "
        f"{where} AND pr.id IS NOT NULL ORDER BY pr.slug",
        tuple(params),
    ).fetchall()
    harness_rows = conn.execute(
        "SELECT DISTINCT s.executor, s.executor_surface FROM harness_sessions s "
        f"{where}",
        tuple(params),
    ).fetchall()
    machines = conn.execute(
        "SELECT DISTINCT s.machine_id, " + _MACHINE_NAME + " AS machine_name "
        "FROM harness_sessions s " + where + " AND s.machine_id IS NOT NULL "
        "ORDER BY s.machine_id",
        tuple(params),
    ).fetchall()
    harnesses = sorted(
        {
            str(value)
            for raw in harness_rows
            for value in (
                row_value(raw, "executor", 0),
                row_value(raw, "executor_surface", 1),
            )
            if value
        }
    )
    return {
        "projects": [
            {"id": int(row_value(raw, "id", 0)), "slug": str(row_value(raw, "slug", 1))}
            for raw in projects
        ],
        "harnesses": harnesses,
        "machines": [
            {
                "id": str(row_value(raw, "machine_id", 0)),
                "label": str(
                    row_value(raw, "machine_name", 1) or row_value(raw, "machine_id", 0)
                ),
            }
            for raw in machines
        ],
    }
