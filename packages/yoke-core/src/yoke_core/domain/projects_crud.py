"""Project-row CRUD: create, get, list, update, has-capability.

Owner: ``yoke_core.domain.projects`` (orchestration layer).  Public
symbols are re-exported from the parent so existing callers via
``yoke_core.domain.projects`` continue to work unchanged.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.project_identity import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    resolve_project,
    resolve_project_id,
)


def _parent_constants():
    """Resolve parent-module constants at call time.

    A top-level ``from yoke_core.domain.projects import PROJECT_FIELDS``
    would deadlock under ``python -m yoke_core.domain.projects``: that
    invocation loads the parent twice (once as ``__main__``, once as the
    fully-qualified name), and the second load re-enters the parent's
    re-export of this module before this module's symbols exist.  Pulling
    the constants in lazily breaks the cycle.
    """
    from yoke_core.domain import projects as _parent
    return (
        _parent.PROJECT_FIELDS,
        _parent._PROJECT_SELECT,
        _parent._PROJECT_LIST_SELECT,
    )


def _pipe_row(row) -> str:
    """Format a ``sqlite3.Row`` as a pipe-delimited string."""
    return "|".join(str(v) if v is not None else "" for v in row)


def _pipe_rows(rows) -> str:
    """Format a list of ``sqlite3.Row`` as pipe-delimited lines."""
    return "\n".join(_pipe_row(r) for r in rows)



# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def cmd_create(
    project_id: str,
    name: str,
    db_path: Optional[str] = None,
) -> str:
    """Insert a new project.  Returns confirmation message."""
    conn = connect(db_path)
    try:
        if resolve_project(conn, project_id, required=False) is not None:
            raise ValueError(f"project {project_id!r} already exists")
        next_id = int(query_scalar(conn, "SELECT COALESCE(MAX(id), 0) + 1 FROM projects") or 1)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                next_id, project_id, name, DEFAULT_PUBLIC_ITEM_PREFIX,
                iso8601_now(),
            ),
        )
        from yoke_core.domain.project_policy_capabilities import (
            ensure_default_policy_capabilities,
        )

        ensure_default_policy_capabilities(conn, next_id)
        conn.commit()
        return f"Created project: {project_id}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

def cmd_get(
    project_id: str,
    field: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Get a project row or single field.

    Returns:
        Pipe-delimited row (all fields) or single field value.
        ``None`` if not found.
    """
    project_fields, project_select, _ = _parent_constants()
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project_id, required=False)
        if ident is None:
            return None
        numeric_project_id = ident.id
        if field:
            if field not in project_fields:
                # hint messages now point at the Python CLI entrypoint.
                _caps_hint = (
                    f"Hint: for capabilities, use: python3 -m yoke_core.domain.projects "
                    f"capability-list {project_id}"
                )
                _settings_hint = (
                    f"Hint: for capability settings, use: python3 -m yoke_core.domain.projects "
                    f"capability-get-settings {project_id} <type>"
                )
                _secrets_hint = (
                    f"Hint: for secrets, use: python3 -m yoke_core.domain.projects "
                    f"capability-get-secret {project_id} <type> <key>"
                )
                hints = {
                    "capabilities": _caps_hint,
                    "capability": _caps_hint,
                    "caps": _caps_hint,
                    "settings": _settings_hint,
                    "secrets": _secrets_hint,
                    "secret": _secrets_hint,
                    "config": _settings_hint,
                }
                msg = (
                    f"Error: projects get: unknown field '{field}' on projects table.\n"
                )
                msg += f"  Valid fields: {' '.join(project_fields)}"
                hint = hints.get(field)
                if hint:
                    msg += f"\n  {hint}"
                raise ValueError(msg)

            exists = query_scalar(
                conn, "SELECT COUNT(*) FROM projects WHERE id=%s", (numeric_project_id,)
            )
            if not exists:
                return None

            val = query_scalar(
                conn, f"SELECT {field} FROM projects WHERE id=%s", (numeric_project_id,)
            )
            return str(val) if val is not None else ""
        else:
            row = query_one(
                conn,
                f"SELECT {project_select} FROM projects WHERE id=%s",
                (numeric_project_id,),
            )
            if row is None:
                return None
            return _pipe_row(row)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def cmd_list(db_path: Optional[str] = None) -> str:
    """List all projects (pipe-delimited rows)."""
    _, _, project_list_select = _parent_constants()
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            f"SELECT {project_list_select} FROM projects ORDER BY id ASC",
        )
        return _pipe_rows(rows)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def cmd_update(
    project_id: str,
    field: str,
    value: str,
    db_path: Optional[str] = None,
) -> str:
    """Update a single field.  Returns confirmation or raises on error."""
    project_fields, _, _ = _parent_constants()
    if field not in project_fields:
        raise ValueError(
            f"Error: projects update: unknown field '{field}' on projects table.\n"
            f"  Valid fields: {' '.join(project_fields)}"
        )
    if field == "id":
        raise ValueError("Error: cannot update primary key 'id'")
    if field == "github_sync_mode":
        from yoke_core.domain.projects_github_sync_mode import (
            validate_github_sync_mode,
        )

        value = validate_github_sync_mode(value)

    conn = connect(db_path)
    try:
        numeric_project_id = resolve_project_id(conn, project_id)
        exists = query_scalar(
            conn, "SELECT COUNT(*) FROM projects WHERE id=%s", (numeric_project_id,)
        )
        if not exists:
            raise LookupError(f"Error: project '{project_id}' not found")

        if field == "github_repo":
            from yoke_core.domain.projects_upsert import (
                _binding_guarded_github_repo,
            )

            value = _binding_guarded_github_repo(conn, numeric_project_id, value)

        conn.execute(
            f"UPDATE projects SET {field}=%s WHERE id=%s",
            (value, numeric_project_id),
        )
        if field == "default_branch":
            from yoke_core.domain.project_policy_capabilities import (
                set_project_policy_value,
            )

            set_project_policy_value(
                conn, numeric_project_id, "base_branch", value,
            )
        conn.commit()
        return f"Updated project '{project_id}': {field}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# has-capability
# ---------------------------------------------------------------------------

def cmd_has_capability(
    project: str,
    cap_type: str,
    db_path: Optional[str] = None,
) -> bool:
    """Return True if the project has the given capability, False otherwise."""
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project, required=False)
        if ident is None:
            return False
        project_id = ident.id
        count = query_scalar(
            conn,
            "SELECT COUNT(*) FROM project_capabilities WHERE project_id=%s AND type=%s",
            (project_id, cap_type),
        )
        return (count or 0) > 0
    finally:
        conn.close()
