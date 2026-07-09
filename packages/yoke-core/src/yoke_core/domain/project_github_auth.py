"""Canonical project GitHub App auth + repo resolver.

Yoke-owned GitHub callers resolve repo + bearer-token-ready auth through
``resolve_project_github_auth`` and fail closed with typed
``ProjectGithubAuthError`` subclasses. Repo state comes from the GitHub App
project binding tables; bearer tokens are short-lived installation tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Callable, Mapping, Optional

from yoke_core.domain import db_backend, gh_rest_transport, json_helper
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.github_app_installation_tokens import InstallationTokenCache
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    InstallationToken,
)
from yoke_core.domain.project_github_binding import (
    BINDING_ACTIVE,
    INSTALLATION_ACTIVE,
)
from yoke_core.domain.project_github_binding_payload import (
    REQUIRED_AUTOMATION_PERMISSIONS,
    permission_status,
    permissions_dict,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.projects_capabilities import cmd_capability_get_secret


GITHUB_CAPABILITY_TYPE = "github"
GITHUB_APP_PRIVATE_KEY_SECRET_KEY = "app_private_key"

_INSTALLATION_TOKEN_CACHE = InstallationTokenCache()


def _missing_table_errors(conn) -> tuple:
    return db_backend.operational_error_types(conn)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _rollback_quietly(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


class ProjectGithubAuthError(Exception):
    """Base class for canonical project GitHub auth failures."""

    code: str = "project_github_auth_error"

    def __init__(self, project: str, message: str) -> None:
        super().__init__(message)
        self.project = project


class MissingCapability(ProjectGithubAuthError):
    """No ``project_capabilities`` row for ``(project, type='github')``."""

    code = "missing_capability"


class MissingRepoMetadata(ProjectGithubAuthError):
    """The bound GitHub repository string is missing or invalid."""

    code = "missing_repo_metadata"


class MissingRepoBinding(ProjectGithubAuthError):
    """No GitHub App repository binding exists for the project."""

    code = "missing_repo_binding"


class MissingInstallation(ProjectGithubAuthError):
    """The project binding references an installation row that is absent."""

    code = "missing_installation"


class BindingUnavailable(ProjectGithubAuthError):
    """The project binding exists but is pending or unavailable."""

    code = "binding_unavailable"


class InstallationUnavailable(ProjectGithubAuthError):
    """The GitHub App installation is pending, suspended, or deleted."""

    code = "installation_unavailable"


class MissingPermission(ProjectGithubAuthError):
    """The binding is known to lack permissions required for automation."""

    code = "missing_permission"


class MissingAppCredentials(ProjectGithubAuthError):
    """The control plane lacks GitHub App issuer or private-key material."""

    code = "missing_app_credentials"


class TokenMintFailed(ProjectGithubAuthError):
    """GitHub App installation-token minting failed."""

    code = "token_mint_failed"


class MissingToken(ProjectGithubAuthError):
    """Legacy diagnostic retained for callers that still branch on it."""

    code = "missing_token"


class InvalidSecretSource(ProjectGithubAuthError):
    """Legacy diagnostic retained for callers that still branch on it."""

    code = "invalid_secret_source"


class InvalidToken(ProjectGithubAuthError):
    """Bearer token resolved but GitHub rejected it as unauthorized."""

    code = "invalid_token"


class TransportFailure(ProjectGithubAuthError):
    """GitHub could not be reached by a downstream caller."""

    code = "transport_failure"


@dataclass(frozen=True)
class ProjectGithubAuth:
    """Resolved project GitHub auth bundle.

    Frozen so callers cannot mutate the returned env dict by accident.
    ``env`` is a fresh copy of the caller's ``base_env`` (or
    ``os.environ``) with ``GH_TOKEN`` set; pass directly to
    ``subprocess.run(..., env=...)``.
    """

    project: str
    repo: str
    token: str
    env: Mapping[str, str] = field()
    installation_id: str = ""
    token_expires_at: str = ""
    token_source: str = "github_app_installation"


@dataclass(frozen=True)
class _ProjectGithubState:
    project_slug: str
    project_id: int | None
    has_capability: bool
    capability_settings: Mapping[str, Any]
    project_repo: str
    binding: Mapping[str, Any] | None
    installation: Mapping[str, Any] | None


@dataclass(frozen=True)
class _AppCredentials:
    issuer: str
    private_key_pem: str
    secret_key: str
    api_url: str


TokenMinter = Callable[..., InstallationToken]


def _read_github_state(
    project: str,
    db_path: Optional[str],
    conn: Optional[Any] = None,
) -> _ProjectGithubState:
    own_conn = conn is None
    if own_conn:
        conn = connect(db_path)
    try:
        assert conn is not None
        try:
            ident = resolve_project(conn, project, required=True)
        except LookupError:
            return _empty_state(project)
        except _missing_table_errors(conn):
            _rollback_quietly(conn)
            return _empty_state(project)
        assert ident is not None
        project_id = ident.id
        project_slug = ident.slug

        has_capability = False
        capability_settings: Mapping[str, Any] = {}
        try:
            cap_row = conn.execute(
                "SELECT COALESCE(settings, '{}') AS settings "
                "FROM project_capabilities "
                f"WHERE project_id={_p(conn)} AND type={_p(conn)} LIMIT 1",
                (project_id, GITHUB_CAPABILITY_TYPE),
            ).fetchone()
            has_capability = cap_row is not None
            capability_settings = _settings_dict(
                cap_row["settings"] if cap_row is not None else "{}"
            )
        except _missing_table_errors(conn):
            _rollback_quietly(conn)

        project_repo = ""
        try:
            project_row = conn.execute(
                "SELECT COALESCE(github_repo, '') AS repo FROM projects "
                f"WHERE id={_p(conn)}",
                (project_id,),
            ).fetchone()
            project_repo = (
                str(project_row["repo"] or "") if project_row is not None else ""
            )
        except _missing_table_errors(conn):
            _rollback_quietly(conn)

        binding = None
        installation = None
        try:
            binding_row = conn.execute(
                "SELECT * FROM project_github_repo_bindings "
                f"WHERE project_id={_p(conn)}",
                (project_id,),
            ).fetchone()
            binding = _row_dict(binding_row)
            if binding is not None:
                installation_row = conn.execute(
                    "SELECT * FROM github_app_installations "
                    f"WHERE installation_id={_p(conn)}",
                    (binding["installation_id"],),
                ).fetchone()
                installation = _row_dict(installation_row)
        except _missing_table_errors(conn):
            _rollback_quietly(conn)

        return _ProjectGithubState(
            project_slug=project_slug,
            project_id=project_id,
            has_capability=has_capability,
            capability_settings=capability_settings,
            project_repo=project_repo,
            binding=binding,
            installation=installation,
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


def resolve_project_github_auth(
    project: str,
    *,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
    base_env: Optional[Mapping[str, str]] = None,
    token_cache: InstallationTokenCache | None = None,
    token_minter: TokenMinter | None = None,
) -> ProjectGithubAuth:
    """Resolve canonical GitHub repo + short-lived App token for ``project``.

    Failure modes are App-shaped: missing repo binding, missing installation,
    unavailable binding/installation, missing permission, missing control-plane
    App credentials, token mint failure, and transport failure. Backlog-only
    callers still skip before reaching this resolver.
    """

    state = _read_github_state(project, db_path, conn=conn)

    if not state.has_capability:
        raise MissingCapability(
            state.project_slug,
            f"project '{state.project_slug}' has no GitHub App capability row; "
            "bind a repository with `yoke projects github-binding bind`",
        )

    if state.binding is None:
        raise MissingRepoBinding(
            state.project_slug,
            f"project '{state.project_slug}' is not bound to a GitHub App repository",
        )

    repo_clean = str(
        state.binding.get("github_repo") or state.project_repo or ""
    ).strip()
    if not repo_clean:
        raise MissingRepoMetadata(
            state.project_slug,
            f"project '{state.project_slug}' has no bound GitHub repository",
        )

    if state.installation is None:
        raise MissingInstallation(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App installation is missing",
        )

    binding_status = str(state.binding.get("status") or "")
    if binding_status != BINDING_ACTIVE:
        raise BindingUnavailable(
            state.project_slug,
            f"project '{state.project_slug}' GitHub binding is {binding_status!r}",
        )

    installation_status = str(state.installation.get("status") or "")
    if installation_status != INSTALLATION_ACTIVE:
        raise InstallationUnavailable(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App installation is "
            f"{installation_status!r}",
        )

    binding_permissions = permissions_dict(state.binding.get("permissions"))
    permissions_info = permission_status(binding_permissions)
    if permissions_info.get("status") == "missing":
        missing = ", ".join(permissions_info.get("missing") or [])
        raise MissingPermission(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App binding is missing "
            f"permissions: {missing}",
        )

    credentials = _read_app_credentials(
        state,
        db_path=db_path,
        conn=conn,
    )
    minted = _mint_bound_installation_token(
        state,
        repo=repo_clean,
        credentials=credentials,
        permissions_info=permissions_info,
        token_cache=token_cache,
        token_minter=token_minter,
    )
    token = str(getattr(minted, "token", "") or "").strip()
    if not token:
        raise TokenMintFailed(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App token resolved empty",
        )

    env: dict[str, str] = dict(os.environ) if base_env is None else dict(base_env)
    env["GH_TOKEN"] = token
    expires_at = getattr(minted, "expires_at", None)
    return ProjectGithubAuth(
        project=state.project_slug,
        repo=repo_clean,
        token=token,
        env=env,
        installation_id=str(state.binding.get("installation_id") or ""),
        token_expires_at=expires_at.isoformat() if expires_at else "",
    )


def _read_app_credentials(
    state: _ProjectGithubState,
    *,
    db_path: Optional[str],
    conn: Optional[Any],
) -> _AppCredentials:
    issuer = _setting_text(
        state.capability_settings,
        "app_issuer",
        "client_id",
        "app_id",
    )
    if not issuer:
        raise MissingAppCredentials(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App issuer is not configured",
        )
    secret_key = _setting_text(
        state.capability_settings,
        "private_key_secret_key",
    ) or GITHUB_APP_PRIVATE_KEY_SECRET_KEY
    try:
        private_key = cmd_capability_get_secret(
            state.project_slug,
            GITHUB_CAPABILITY_TYPE,
            secret_key,
            db_path=db_path,
            conn=conn,
        )
    except Exception as exc:
        raise MissingAppCredentials(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App private key cannot be read",
        ) from exc
    private_key = str(private_key or "").strip()
    if not private_key:
        raise MissingAppCredentials(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App private key is not configured",
        )
    return _AppCredentials(
        issuer=issuer,
        private_key_pem=private_key,
        secret_key=secret_key,
        api_url=_setting_text(state.capability_settings, "api_url")
        or gh_rest_transport.GITHUB_API_BASE,
    )


def _mint_bound_installation_token(
    state: _ProjectGithubState,
    *,
    repo: str,
    credentials: _AppCredentials,
    permissions_info: Mapping[str, Any],
    token_cache: InstallationTokenCache | None,
    token_minter: TokenMinter | None,
) -> InstallationToken:
    repository_id = _repository_id(
        state.binding.get("repository_id") if state.binding else None
    )
    kwargs: dict[str, Any] = {
        "issuer": credentials.issuer,
        "private_key_pem": credentials.private_key_pem,
        "installation_id": str(state.binding.get("installation_id") or ""),
        "api_url": credentials.api_url,
    }
    if repository_id is not None:
        kwargs["repository_ids"] = [repository_id]
    else:
        kwargs["repositories"] = [repo]
    if permissions_info.get("status") == "satisfied":
        kwargs["permissions"] = dict(REQUIRED_AUTOMATION_PERMISSIONS)
    try:
        if token_minter is not None:
            return token_minter(**kwargs)
        cache = token_cache or _INSTALLATION_TOKEN_CACHE
        return cache.get_or_mint(**kwargs)
    except GitHubAppTokenError as exc:
        raise TokenMintFailed(
            state.project_slug,
            f"project '{state.project_slug}' GitHub App token mint failed: {exc}",
        ) from exc


def _repository_id(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _setting_text(settings: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = settings.get(key)
        if str(value or "").strip():
            return str(value).strip()
    nested = settings.get("github_app")
    if isinstance(nested, Mapping):
        for key in keys:
            value = nested.get(key)
            if str(value or "").strip():
                return str(value).strip()
    return ""


def _settings_dict(raw: Any) -> dict[str, Any]:
    try:
        loaded = json_helper.loads_text(str(raw or "{}"))
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): value for key, value in loaded.items()}


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    return dict(row)


def _empty_state(project: str) -> _ProjectGithubState:
    return _ProjectGithubState(
        project_slug=str(project),
        project_id=None,
        has_capability=False,
        capability_settings={},
        project_repo="",
        binding=None,
        installation=None,
    )


_HINT_BY_CODE: Mapping[str, str] = {
    "missing_capability": (
        "bind a GitHub App repo with `yoke projects github-binding bind "
        "--project {project} ...`, or switch the project to backlog-only"
    ),
    "missing_repo_metadata": (
        "re-bind the GitHub App repo with `yoke projects github-binding bind "
        "--project {project} --github-repo OWNER/REPO ...`"
    ),
    "missing_repo_binding": (
        "bind a GitHub App repo with `yoke projects github-binding bind "
        "--project {project} ...`, or keep the project backlog-only"
    ),
    "missing_installation": (
        "reconnect GitHub or add repository access, then re-bind project "
        "{project}"
    ),
    "binding_unavailable": (
        "repair GitHub repo access for project {project}, or re-bind to an "
        "available repository"
    ),
    "installation_unavailable": (
        "restore or reinstall the GitHub App installation for project {project}"
    ),
    "missing_permission": (
        "approve the missing GitHub App permissions for project {project}, then "
        "refresh the binding"
    ),
    "missing_app_credentials": (
        "configure GitHub App issuer settings and the github.app_private_key "
        "control-plane secret for project {project}"
    ),
    "token_mint_failed": (
        "retry after GitHub App credentials and installation access are healthy "
        "for project {project}"
    ),
    "missing_token": (
        "legacy github.token is no longer used; `yoke projects capability "
        "secret set` no longer repairs project {project}; bind a GitHub App repo"
    ),
    "invalid_secret_source": (
        "legacy github.token is no longer used; `yoke projects capability "
        "secret set` no longer repairs project {project}; bind a GitHub App repo"
    ),
    "invalid_token": (
        "reconnect GitHub App access for project {project}; installation tokens "
        "are minted on demand"
    ),
    "transport_failure": (
        "retry once network is restored; the resolver is idempotent"
    ),
}


def repair_command_hint(
    error: ProjectGithubAuthError,
    project: str,
) -> str:
    """Concrete operator-facing repair hint for ``error``."""
    template = _HINT_BY_CODE.get(error.code)
    if template is None:
        return (
            f"unknown project_github_auth error code '{error.code}'; "
            "check the GitHub App binding and capability settings"
        )
    return template.format(project=project)


__all__ = [
    "BindingUnavailable",
    "GITHUB_APP_PRIVATE_KEY_SECRET_KEY",
    "GITHUB_CAPABILITY_TYPE",
    "InstallationUnavailable",
    "InvalidSecretSource",
    "InvalidToken",
    "MissingAppCredentials",
    "MissingCapability",
    "MissingInstallation",
    "MissingPermission",
    "MissingRepoBinding",
    "MissingRepoMetadata",
    "MissingToken",
    "ProjectGithubAuth",
    "ProjectGithubAuthError",
    "TokenMintFailed",
    "TransportFailure",
    "repair_command_hint",
    "resolve_project_github_auth",
]
