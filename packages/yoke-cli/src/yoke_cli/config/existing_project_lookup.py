"""Existing-project lookup helpers for onboarding flows."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts import github_origin
from yoke_cli.config.existing_project_http import (
    ExistingProjectLookupError,
    call_function as _call_function,
)
from yoke_cli.config.local_universe_setup import LOCAL_ENV

MATCH_SOURCE_LOCAL_CHECKOUT = "local-checkout"
MATCH_SOURCE_GITHUB_REPO = "github-repo"


class ExistingProjectAccessError(ExistingProjectLookupError):
    """A project exists for the repo, but this Yoke token cannot access it."""


class ExistingProjectReferenceError(ExistingProjectLookupError):
    """A local checkout names a project id that cannot be used."""


@dataclass(frozen=True)
class ExistingProject:
    """A Yoke project row resolved from repo metadata."""

    id: int
    slug: str
    name: str
    github_repo: str
    default_branch: str
    public_item_prefix: str
    github_sync_mode: str = "backlog_only"


@dataclass(frozen=True)
class LocalProjectReference:
    """A project id discovered from local checkout state."""

    project_id: int
    source: str


def find_local_project_reference(
    checkout: str | Path,
    *,
    config_path: str | Path | None,
) -> LocalProjectReference | None:
    """Return the local project id from manifest or machine config, if present."""
    from yoke_cli.config import machine_config
    from yoke_cli.project_install import files as install_files
    from yoke_cli.project_install.files import ProjectInstallError

    root = Path(checkout).expanduser()
    try:
        manifest = install_files.load_manifest(root)
    except ProjectInstallError as exc:
        raise ExistingProjectReferenceError(str(exc)) from exc
    if manifest is not None:
        project_id = _positive_project_id(manifest.get("project_id"))
        if project_id is None:
            raise ExistingProjectReferenceError(
                f"{install_files.MANIFEST_REL} does not contain a valid project_id"
            )
        return LocalProjectReference(
            project_id=project_id,
            source=install_files.MANIFEST_REL,
        )
    try:
        project_id = machine_config.project_id(root, config_path)
    except machine_config.MachineConfigError as exc:
        raise ExistingProjectReferenceError(str(exc)) from exc
    if project_id is not None:
        return LocalProjectReference(
            project_id=project_id,
            source="machine config",
        )
    return None


def find_by_project_id(
    *,
    api_url: str,
    token: str,
    project_id: int,
) -> ExistingProject:
    """Return a visible project by canonical numeric id."""
    numeric = _positive_project_id(project_id)
    if numeric is None:
        raise ExistingProjectReferenceError("local project_id must be positive")
    response = _call_function(
        api_url=api_url,
        token=token,
        function="projects.get",
        payload={"project": str(numeric)},
    )
    if not response.get("success"):
        error = response.get("error")
        code = ""
        message = ""
        if isinstance(error, Mapping):
            code = str(error.get("code") or "")
            message = str(error.get("message") or "")
        if code == "permission_denied":
            raise ExistingProjectAccessError(
                message or f"this Yoke token cannot access project {numeric}"
            )
        if code == "not_found":
            raise ExistingProjectReferenceError(
                message or f"project {numeric} was not found"
            )
        raise ExistingProjectLookupError(
            message or f"projects.get could not read project {numeric}"
        )
    result = response.get("result")
    row = result.get("row") if isinstance(result, Mapping) else None
    if not isinstance(row, Mapping):
        raise ExistingProjectLookupError("projects.get returned an invalid row")
    return _project_from_row(row)


def find_local_by_project_id(
    *,
    config_path: str | Path | None,
    project_id: int,
) -> ExistingProject:
    """Return a project from this machine's local Yoke universe."""
    numeric = _positive_project_id(project_id)
    if numeric is None:
        raise ExistingProjectReferenceError("local project_id must be positive")
    response = _call_local_function(
        config_path=config_path,
        function="projects.get",
        payload={"project": str(numeric)},
    )
    if not response.get("success"):
        error = response.get("error")
        code = ""
        message = ""
        if isinstance(error, Mapping):
            code = str(error.get("code") or "")
            message = str(error.get("message") or "")
        if code == "permission_denied":
            raise ExistingProjectAccessError(
                message or f"this local Yoke universe cannot access project {numeric}"
            )
        if code == "not_found":
            raise ExistingProjectReferenceError(
                message or f"project {numeric} was not found"
            )
        raise ExistingProjectLookupError(
            message or f"projects.get could not read project {numeric}"
        )
    result = response.get("result")
    row = result.get("row") if isinstance(result, Mapping) else None
    if not isinstance(row, Mapping):
        raise ExistingProjectLookupError("projects.get returned an invalid row")
    return _project_from_row(row)


def find_by_github_repo(
    *,
    api_url: str,
    token: str,
    github_repo: str,
    web_url: str | None = None,
) -> ExistingProject | None:
    """Return the visible project whose recorded GitHub repo matches."""
    wanted = normalize_github_repo(github_repo, web_url=web_url)
    if not wanted:
        return None
    response = _call_function(
        api_url=api_url,
        token=token,
        function="projects.resolve_by_github_repo",
        payload={"github_repo": wanted},
    )
    if not response.get("success"):
        error = response.get("error")
        code = ""
        message = ""
        if isinstance(error, Mapping):
            code = str(error.get("code") or "")
            message = str(error.get("message") or "")
        if code == "not_found":
            return None
        if code == "permission_denied":
            raise ExistingProjectAccessError(
                message or f"this Yoke token cannot access {wanted}"
            )
        raise ExistingProjectLookupError(
            message or "projects.resolve_by_github_repo could not resolve the repo"
        )
    result = response.get("result")
    row = result.get("row") if isinstance(result, Mapping) else None
    if row is None:
        return None
    if not isinstance(row, Mapping):
        raise ExistingProjectLookupError("project resolver returned an invalid row")
    return _project_from_row(row)


def normalize_github_repo(
    value: Any,
    *,
    web_url: str | None = None,
) -> str:
    """Normalize a repo on the configured GitHub origin to ``owner/repo``."""
    try:
        normalized = github_origin.normalize_github_repository(
            str(value or ""),
            web_url=web_url or github_origin.DEFAULT_GITHUB_WEB_URL,
        )
    except github_origin.GitHubApiOriginError:
        return ""
    return normalized.casefold()


def _call_local_function(
    *,
    config_path: str | Path | None,
    function: str,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    from yoke_cli.config import machine_config
    from yoke_cli.project_install.files import ProjectInstallError
    from yoke_cli.project_install.transport import _local_postgres_env
    from yoke_cli.transport.dispatcher import call_dispatcher
    from yoke_contracts.api.function_call import ActorContext, TargetRef
    from yoke_contracts.machine_config.schema import (
        MachineConfigContractError,
        POSTGRES_TRANSPORTS,
        connection_is_prod,
    )

    try:
        connection = machine_config.active_connection(
            config_path,
            explicit_env=LOCAL_ENV,
        )
    except (machine_config.MachineConfigError, MachineConfigContractError) as exc:
        raise ExistingProjectLookupError(
            "this machine does not have a usable local universe connection yet; "
            "finish local machine setup first, then retry project setup"
        ) from exc
    transport = str(connection.get("transport") or "")
    if transport not in POSTGRES_TRANSPORTS:
        raise ExistingProjectLookupError(
            f"env {LOCAL_ENV!r} is {transport or 'unconfigured'}, not local-postgres"
        )
    if connection_is_prod(connection):
        raise ExistingProjectLookupError(
            f"env {LOCAL_ENV!r} is marked prod; local onboarding will not read "
            "projects through a prod local-postgres authority"
        )
    try:
        # Dynamic import keeps yoke-cli's static engine-import boundary intact
        # (see test_installer_package_boundaries); local project-reuse lookup
        # reads the engine DSN env contract only on the local-postgres branch.
        db_backend = importlib.import_module("yoke_core.domain.db_backend")
    except ModuleNotFoundError as exc:
        raise ExistingProjectLookupError(
            "the yoke-core engine package is not importable, so local project "
            "metadata cannot be verified; reinstall Yoke or choose a hosted/server "
            "destination"
        ) from exc
    try:
        with _local_postgres_env(
            connection,
            config_path,
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        ):
            response = call_dispatcher(
                function_id=function,
                target=TargetRef(kind="global"),
                payload=dict(payload),
                actor=ActorContext(actor_id=None, session_id=""),
                local_only=True,
            )
    except ProjectInstallError as exc:
        raise ExistingProjectLookupError(str(exc)) from exc
    return response.model_dump(mode="json")


def _project_from_row(row: Mapping[str, Any]) -> ExistingProject:
    try:
        project_id = int(row.get("id") or 0)
    except (TypeError, ValueError) as exc:
        raise ExistingProjectLookupError("matched project row has no numeric id") from exc
    if project_id <= 0:
        raise ExistingProjectLookupError("matched project row has no numeric id")
    slug = _text(row.get("slug"))
    name = _text(row.get("name")) or slug
    github_repo = _text(row.get("github_repo"))
    if not slug:
        raise ExistingProjectLookupError("matched project row is missing slug")
    return ExistingProject(
        id=project_id,
        slug=slug,
        name=name,
        github_repo=github_repo,
        default_branch=_text(row.get("default_branch")) or "main",
        public_item_prefix=_text(row.get("public_item_prefix")) or "YOK",
        github_sync_mode=_text(row.get("github_sync_mode")) or "backlog_only",
    )


def _positive_project_id(value: Any) -> int | None:
    try:
        project_id = int(value)
    except (TypeError, ValueError):
        return None
    return project_id if project_id > 0 else None


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "ExistingProject",
    "ExistingProjectAccessError",
    "ExistingProjectLookupError",
    "ExistingProjectReferenceError",
    "MATCH_SOURCE_GITHUB_REPO",
    "MATCH_SOURCE_LOCAL_CHECKOUT",
    "LocalProjectReference",
    "find_local_by_project_id",
    "find_by_project_id",
    "find_by_github_repo",
    "find_local_project_reference",
    "normalize_github_repo",
]
