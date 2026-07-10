"""Database state reader for project GitHub App authorization."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_github_auth_models import (
    GITHUB_CAPABILITY_TYPE,
    ProjectGithubState,
)
from yoke_core.domain.project_identity import resolve_project


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rollback_quietly(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    return dict(row)


def empty_state(project: str) -> ProjectGithubState:
    return ProjectGithubState(
        project_slug=str(project),
        project_id=None,
        has_capability=False,
        binding=None,
        installation=None,
    )


def read_github_state(
    project: str,
    db_path: Optional[str],
    conn: Optional[Any] = None,
) -> ProjectGithubState:
    own_conn = conn is None
    if own_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        missing_table_errors = db_backend.operational_error_types(conn)
        try:
            ident = resolve_project(conn, project, required=True)
        except LookupError:
            return empty_state(project)
        except missing_table_errors:
            _rollback_quietly(conn)
            return empty_state(project)
        assert ident is not None

        has_capability = False
        try:
            row = conn.execute(
                "SELECT 1 FROM project_capabilities "
                f"WHERE project_id={_p(conn)} AND type={_p(conn)} LIMIT 1",
                (ident.id, GITHUB_CAPABILITY_TYPE),
            ).fetchone()
            has_capability = row is not None
        except missing_table_errors:
            _rollback_quietly(conn)

        binding = None
        installation = None
        try:
            row = conn.execute(
                "SELECT * FROM project_github_repo_bindings "
                f"WHERE project_id={_p(conn)}",
                (ident.id,),
            ).fetchone()
            binding = _row_dict(row)
            if binding is not None:
                row = conn.execute(
                    "SELECT * FROM github_app_installations "
                    f"WHERE installation_id={_p(conn)}",
                    (binding["installation_id"],),
                ).fetchone()
                installation = _row_dict(row)
        except missing_table_errors:
            _rollback_quietly(conn)

        return ProjectGithubState(
            project_slug=ident.slug,
            project_id=ident.id,
            has_capability=has_capability,
            binding=binding,
            installation=installation,
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


__all__ = ["empty_state", "read_github_state"]
