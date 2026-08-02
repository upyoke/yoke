"""GitHub App installation and project repository binding state."""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_contracts.github_binding_metadata import (
    GitHubBindingMetadataError,
    validate_binding_metadata,
)
from yoke_contracts.github_app_tokens import GITHUB_CAPABILITY_TYPE
from yoke_contracts.project_contract.github_sync_mode import GITHUB_SYNC_DISABLED

from yoke_core.domain import (
    db_backend,
    json_helper,
    project_github_capability_settings,
)
from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
    verify_project_github_binding,
)
from yoke_core.domain.project_github_binding_payload import (
    normalize_github_repo,
    permission_status,
    permissions_text,
)
from yoke_core.domain.project_github_binding_persistence import (
    InstallationOriginConflict,
    ProjectGithubBindingError,
    RepositoryBindingConflict,
    persist_project_binding,
    persist_verified_installation,
)
from yoke_core.domain.project_github_binding_status import (
    cmd_project_github_binding_status,
)
from yoke_core.domain.project_github_binding_state import (
    BINDING_ACTIVE,
    BINDING_PENDING,
    BINDING_STATUS_VALUES,
    BINDING_UNAVAILABLE,
    INSTALLATION_ACTIVE,
    INSTALLATION_DELETED,
    INSTALLATION_PENDING,
    INSTALLATION_STATUS_VALUES,
    INSTALLATION_SUSPENDED,
    binding_persistence_state,
    refresh_attached_project_bindings,
)
from yoke_core.domain.project_identity import resolve_project


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cmd_bind_project_repo(
    project: str,
    *,
    installation_id: str,
    repository_id: str,
    github_repo: str,
    expected_api_url: str,
    github_user_access_token: str,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
    verifier: Callable[..., VerifiedProjectGitHubBinding] | None = None,
) -> dict[str, Any]:
    """Verify user-authorized GitHub metadata, then persist the binding."""
    selected_verifier = verifier or verify_project_github_binding
    verified = selected_verifier(
        installation_id=installation_id,
        repository_id=repository_id,
        expected_github_repo=github_repo,
        expected_api_url=expected_api_url,
        github_user_access_token=github_user_access_token,
    )
    return _store_verified_project_repo_binding(
        project,
        verified=verified,
        db_path=db_path,
        conn=conn,
    )


def _store_verified_project_repo_binding(
    project: str,
    *,
    verified: VerifiedProjectGitHubBinding,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> dict[str, Any]:
    """Persist metadata produced by ``verify_project_github_binding`` only."""
    try:
        metadata = validate_binding_metadata(
            installation_id=verified.installation_id,
            account_id=verified.account_id,
            account_login=verified.account_login,
            account_type=verified.account_type,
            repository_selection=verified.repository_selection,
            permissions=verified.permissions,
            repository_id=verified.repository_id,
            github_repo=verified.github_repo,
            default_branch=verified.default_branch,
            repository_is_private=verified.repository_is_private,
            installation_status=verified.installation_status,
        )
    except GitHubBindingMetadataError as exc:
        raise ProjectGithubBindingError(str(exc)) from exc
    installation_key = metadata.installation_id
    repo = metadata.github_repo
    owns_conn = conn is None
    if owns_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        now = iso8601_now()
        p = _p(conn)
        selected_permissions = permissions_text(metadata.permissions)
        installation_status = metadata.installation_status
        if installation_status not in INSTALLATION_STATUS_VALUES:
            raise ProjectGithubBindingError(
                f"invalid verified installation status: {installation_status}"
            )
        permissions_info = permission_status(metadata.permissions)
        persistence = binding_persistence_state(
            installation_status,
            str(permissions_info.get("status") or "unknown"),
        )
        repository_key = metadata.repository_id
        try:
            api_url = validate_github_api_endpoint(verified.api_url).base_url
        except GitHubApiOriginError as exc:
            raise ProjectGithubBindingError(
                "verified GitHub API URL is invalid"
            ) from exc
        capability_settings = (
            project_github_capability_settings.build_github_capability_settings(
                conn,
                ident.id,
                github_repo=repo,
                installation_id=installation_key,
                repository_id=repository_key,
                api_url=api_url,
                permissions=metadata.permissions,
            )
        )
        try:
            persist_verified_installation(
                conn,
                placeholder=p,
                installation_id=installation_key,
                api_url=api_url,
                account_id=metadata.account_id,
                account_login=metadata.account_login,
                account_type=metadata.account_type,
                repository_selection=metadata.repository_selection,
                permissions=selected_permissions,
                status=installation_status,
                verified_at=now,
                last_error=persistence.installation_error,
            )
        except InstallationOriginConflict as exc:
            raise ProjectGithubBindingError(
                "GitHub App installation is already registered for a different "
                "GitHub API origin; use the matching control plane or reconnect "
                "the installation"
            ) from exc
        refresh_attached_project_bindings(
            conn,
            installation_id=installation_key,
            permissions=selected_permissions,
            persistence=persistence,
            verified_at=now,
        )
        try:
            persist_project_binding(
                conn,
                placeholder=p,
                project_id=ident.id,
                installation_id=installation_key,
                repository_id=repository_key,
                api_url=api_url,
                github_repo=repo,
                default_branch=metadata.default_branch,
                repository_is_private=metadata.repository_is_private,
                status=persistence.binding_status,
                permissions=selected_permissions,
                verified_at=now,
                last_error=persistence.binding_error,
            )
        except RepositoryBindingConflict as exc:
            raise ProjectGithubBindingError(
                "GitHub App repository is already bound to another project; "
                "unbind it there before retrying"
            ) from exc
        conn.execute(
            f"UPDATE projects SET github_repo={p}, "
            f"default_branch=COALESCE({p}, default_branch) "
            f"WHERE id={p}",
            (
                repo,
                metadata.default_branch,
                ident.id,
            ),
        )
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
    """Remove one project's GitHub binding and retired credential residue."""
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
        for table in ("project_capabilities", "capability_secrets"):
            delete_sql = (
                f"DELETE FROM {table} WHERE project_id={p} AND LOWER(TRIM(type))={p}"
            )
            conn.execute(delete_sql, (ident.id, GITHUB_CAPABILITY_TYPE))
        conn.execute(
            f"UPDATE projects SET github_repo=NULL, github_sync_mode={p} WHERE id={p}",
            (GITHUB_SYNC_DISABLED, ident.id),
        )
        if owns_conn:
            conn.commit()
        return cmd_project_github_binding_status(project, conn=conn)
    finally:
        if owns_conn and conn is not None:
            conn.close()


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
    "cmd_bind_project_repo",
    "cmd_project_github_binding_status",
    "cmd_unbind_project_repo",
    "normalize_github_repo",
]
