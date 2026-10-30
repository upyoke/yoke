"""Read non-secret project bindings within one authorized organization."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


def list_project_github_bindings(
    conn: Any, *, org_id: int, installation_id: str | None = None,
) -> list[dict[str, Any]]:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    query = (
        "SELECT p.id AS project_id, p.slug AS project, "
        "b.installation_id, b.repository_id, b.github_repo, b.api_url "
        "FROM project_github_repo_bindings b "
        "JOIN projects p ON p.id = b.project_id "
        f"WHERE p.org_id = {p}"
    )
    params: list[Any] = [org_id]
    if installation_id is not None:
        query += f" AND b.installation_id = {p}"
        params.append(installation_id)
    rows = conn.execute(query + " ORDER BY p.id", tuple(params)).fetchall()
    return [dict(row) for row in rows]
