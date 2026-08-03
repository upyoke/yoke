"""State reader for project GitHub App authorization.

The rows read here are binding metadata only — which repository a project is
bound to, which installation serves it, and what that installation may do.
No secret material lives in them: the App private key comes from the
control-plane credential mount and a local user token from the bound
provider, both resolved by the caller after this state comes back. That is
what lets the whole state cross the wire when the client has no local
Postgres to read it from.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import control_plane_transport, db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_github_auth_models import (
    GITHUB_CAPABILITY_TYPE,
    ProjectGithubState,
)
from yoke_core.domain.project_identity import resolve_project

READ_FUNCTION_ID = "projects.github_state.read"


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


def state_payload(state: ProjectGithubState) -> dict[str, Any]:
    """Render the state as the wire shape the read function returns."""
    return {
        "project_slug": state.project_slug,
        "project_id": state.project_id,
        "has_capability": state.has_capability,
        "binding": dict(state.binding) if state.binding is not None else None,
        "installation": (
            dict(state.installation) if state.installation is not None else None
        ),
    }


def state_from_payload(payload: Mapping[str, Any]) -> ProjectGithubState:
    """Rebuild the state a relayed read returned."""
    project_id = payload.get("project_id")
    return ProjectGithubState(
        project_slug=str(payload.get("project_slug") or ""),
        project_id=int(project_id) if project_id is not None else None,
        has_capability=bool(payload.get("has_capability")),
        binding=payload.get("binding") or None,
        installation=payload.get("installation") or None,
    )


def read_github_state(
    project: str,
    db_path: Optional[str],
    conn: Optional[Any] = None,
) -> ProjectGithubState:
    """Read one project's GitHub binding state over whichever path is open.

    A caller-supplied connection is used as-is. Otherwise a direct local
    connection is preferred, and the read relays through the dispatcher when
    the connected control plane is one the client cannot open — an https
    control plane has no local Postgres to read.
    """
    if conn is not None:
        return read_github_state_over_connection(conn, project)
    local = control_plane_transport.local_connection_or_none(
        lambda: connect(db_path)
    )
    if local is None:
        return state_from_payload(
            control_plane_transport.relay(
                READ_FUNCTION_ID, {"project": str(project)}
            )
        )
    try:
        return read_github_state_over_connection(local, project)
    finally:
        local.close()


def read_github_state_over_connection(
    conn: Any,
    project: str,
) -> ProjectGithubState:
    """Read the binding state through an already-open connection."""
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


__all__ = [
    "READ_FUNCTION_ID",
    "empty_state",
    "read_github_state",
    "read_github_state_over_connection",
    "state_from_payload",
    "state_payload",
]
