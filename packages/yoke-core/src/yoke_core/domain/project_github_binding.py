"""GitHub App installation and project repository binding state."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
from yoke_core.domain.project_github_binding_payload import (
    REQUIRED_AUTOMATION_PERMISSIONS,
    automation_status,
    binding_payload,
    installation_payload,
    normalize_github_repo,
    permission_status,
    permissions_text,
)
from yoke_core.domain.project_identity import resolve_project


BINDING_ACTIVE = "active"
BINDING_PENDING = "pending"
BINDING_UNAVAILABLE = "unavailable"
BINDING_STATUS_VALUES = frozenset({
    BINDING_ACTIVE,
    BINDING_PENDING,
    BINDING_UNAVAILABLE,
})

INSTALLATION_ACTIVE = "active"
INSTALLATION_PENDING = "pending"
INSTALLATION_SUSPENDED = "suspended"
INSTALLATION_DELETED = "deleted"
INSTALLATION_STATUS_VALUES = frozenset({
    INSTALLATION_ACTIVE,
    INSTALLATION_PENDING,
    INSTALLATION_SUSPENDED,
    INSTALLATION_DELETED,
})

class ProjectGithubBindingError(ValueError):
    """Raised when GitHub App binding state cannot be read or written."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cmd_bind_project_repo(
    project: str,
    *,
    installation_id: str,
    account_id: str,
    account_login: str,
    account_type: str,
    github_repo: str,
    repository_id: Optional[str] = None,
    default_branch: Optional[str] = None,
    repository_selection: str = "selected",
    permissions: Optional[Mapping[str, Any]] = None,
    installation_status: str = INSTALLATION_ACTIVE,
    binding_status: str = BINDING_ACTIVE,
    last_verified_at: Optional[str] = None,
    last_error: Optional[str] = None,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Bind a Yoke project to a GitHub App installation repository."""
    installation_key = _clean_required(installation_id, "installation_id")
    account_id_clean = _clean_required(account_id, "account_id")
    account_login_clean = _clean_required(account_login, "account_login")
    account_type_clean = _clean_required(account_type, "account_type")
    repo = normalize_github_repo(github_repo)
    if not repo:
        raise ProjectGithubBindingError(
            "github_repo must be a GitHub owner/repo or clone URL"
        )
    installation_status = _validate_value(
        installation_status,
        "installation_status",
        INSTALLATION_STATUS_VALUES,
    )
    binding_status = _validate_value(
        binding_status,
        "binding_status",
        BINDING_STATUS_VALUES,
    )
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        now = iso8601_now()
        p = _p(conn)
        selected_permissions = permissions_text(permissions)
        conn.execute(
            "INSERT INTO github_app_installations "
            "(installation_id, account_id, account_login, account_type, "
            "repository_selection, permissions, status, last_verified_at, "
            "last_error, created_at, updated_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
            "ON CONFLICT(installation_id) DO UPDATE SET "
            "account_id=EXCLUDED.account_id, "
            "account_login=EXCLUDED.account_login, "
            "account_type=EXCLUDED.account_type, "
            "repository_selection=EXCLUDED.repository_selection, "
            "permissions=EXCLUDED.permissions, "
            "status=EXCLUDED.status, "
            "last_verified_at=EXCLUDED.last_verified_at, "
            "last_error=EXCLUDED.last_error, "
            "updated_at=EXCLUDED.updated_at",
            (
                installation_key,
                account_id_clean,
                account_login_clean,
                account_type_clean,
                _clean_optional(repository_selection) or "selected",
                selected_permissions,
                installation_status,
                _clean_optional(last_verified_at),
                _clean_optional(last_error),
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO project_github_repo_bindings "
            "(project_id, installation_id, repository_id, github_repo, "
            "default_branch, status, permissions, last_verified_at, last_error, "
            "created_at, updated_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
            "ON CONFLICT(project_id) DO UPDATE SET "
            "installation_id=EXCLUDED.installation_id, "
            "repository_id=EXCLUDED.repository_id, "
            "github_repo=EXCLUDED.github_repo, "
            "default_branch=EXCLUDED.default_branch, "
            "status=EXCLUDED.status, "
            "permissions=EXCLUDED.permissions, "
            "last_verified_at=EXCLUDED.last_verified_at, "
            "last_error=EXCLUDED.last_error, "
            "updated_at=EXCLUDED.updated_at",
            (
                ident.id,
                installation_key,
                _clean_optional(repository_id),
                repo,
                _clean_optional(default_branch),
                binding_status,
                selected_permissions,
                _clean_optional(last_verified_at),
                _clean_optional(last_error),
                now,
                now,
            ),
        )
        conn.execute(
            f"UPDATE projects SET github_repo={p}, "
            f"default_branch=COALESCE({p}, default_branch) WHERE id={p}",
            (repo, _clean_optional(default_branch), ident.id),
        )
        capability_settings = _merged_github_capability_settings(conn, ident.id)
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT(project_id, type) DO UPDATE SET "
            "settings=EXCLUDED.settings",
            (
                ident.id,
                "github",
                json_helper.dumps_compact(capability_settings),
                now,
            ),
        )
        if owns_conn:
            conn.commit()
        return cmd_project_github_binding_status(project, conn=conn)
    finally:
        if owns_conn and conn is not None:
            conn.close()


def cmd_unbind_project_repo(
    project: str,
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Remove the project repository binding and mark the project backlog-only."""
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        p = _p(conn)
        conn.execute(
            f"DELETE FROM project_github_repo_bindings WHERE project_id={p}",
            (ident.id,),
        )
        conn.execute(
            f"DELETE FROM project_capabilities WHERE project_id={p} AND type={p}",
            (ident.id, "github"),
        )
        conn.execute(
            "UPDATE projects SET github_repo=NULL, "
            "github_sync_mode='backlog_only' "
            f"WHERE id={p}",
            (ident.id,),
        )
        if owns_conn:
            conn.commit()
        return cmd_project_github_binding_status(project, conn=conn)
    finally:
        if owns_conn and conn is not None:
            conn.close()


def cmd_project_github_binding_status(
    project: str,
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Return repository binding and automation availability for a project."""
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        p = _p(conn)
        project_row = query_one(
            conn,
            f"SELECT slug, github_repo, default_branch, github_sync_mode "
            f"FROM projects WHERE id={p}",
            (ident.id,),
        )
        binding = query_one(
            conn,
            f"SELECT * FROM project_github_repo_bindings WHERE project_id={p}",
            (ident.id,),
        )
        installation = None
        if binding is not None:
            installation = query_one(
                conn,
                f"SELECT * FROM github_app_installations "
                f"WHERE installation_id={p}",
                (binding["installation_id"],),
            )
        binding_info = binding_payload(binding)
        installation_info = installation_payload(installation)
        permissions_info = permission_status(
            binding_info.get("permissions", {}) if binding_info else {}
        )
        automation_info = automation_status(
            binding_info,
            installation_info,
            permissions_info,
        )
        return {
            "project": ident.slug,
            "github_repo": (
                str(project_row["github_repo"] or "") if project_row else ""
            ),
            "default_branch": (
                str(project_row["default_branch"] or "") if project_row else ""
            ),
            "github_sync_mode": (
                str(project_row["github_sync_mode"] or "enabled")
                if project_row else "enabled"
            ),
            "bound": binding_info is not None,
            "binding": binding_info,
            "installation": installation_info,
            "permission_status": permissions_info,
            "automation": automation_info,
        }
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _clean_required(value: Any, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ProjectGithubBindingError(f"{label} is required")
    return cleaned


def _clean_optional(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def _validate_value(value: Any, label: str, accepted: frozenset[str]) -> str:
    cleaned = _clean_required(value, label)
    if cleaned not in accepted:
        raise ProjectGithubBindingError(
            f"{label} must be one of {sorted(accepted)}, got {value!r}"
        )
    return cleaned


def _merged_github_capability_settings(conn: Any, project_id: int) -> dict[str, Any]:
    row = query_one(
        conn,
        f"SELECT COALESCE(settings, '{{}}') AS settings "
        f"FROM project_capabilities WHERE project_id={_p(conn)} AND type={_p(conn)}",
        (project_id, "github"),
    )
    settings: dict[str, Any] = {}
    if row is not None:
        try:
            loaded = json_helper.loads_text(str(row["settings"] or "{}"))
        except Exception:
            loaded = {}
        if isinstance(loaded, dict):
            settings.update({str(key): value for key, value in loaded.items()})
    settings.update({
        "auth_model": "github_app",
        "binding_table": "project_github_repo_bindings",
    })
    return settings


__all__ = [
    "BINDING_ACTIVE",
    "BINDING_PENDING",
    "BINDING_STATUS_VALUES",
    "BINDING_UNAVAILABLE",
    "INSTALLATION_ACTIVE",
    "INSTALLATION_DELETED",
    "INSTALLATION_PENDING",
    "INSTALLATION_STATUS_VALUES",
    "INSTALLATION_SUSPENDED",
    "ProjectGithubBindingError",
    "REQUIRED_AUTOMATION_PERMISSIONS",
    "cmd_bind_project_repo",
    "cmd_project_github_binding_status",
    "cmd_unbind_project_repo",
    "normalize_github_repo",
]
