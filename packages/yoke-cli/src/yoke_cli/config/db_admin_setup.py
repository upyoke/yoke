"""Machine-local ``<env>-db-admin`` profile setup."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

from yoke_cli.transport import dispatcher as function_dispatcher  # noqa: F401 - public test injection surface
from yoke_cli.transport import https as https_transport  # noqa: F401 - public test injection surface
from yoke_contracts.machine_config import schema as contract
from yoke_cli.config.project_selection import required_project_context
from yoke_contracts.project_defaults import MissingProjectError
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError, _safe_label

from yoke_cli.config.db_admin_control_plane import (
    CONTROL_PLANE_DATABASE_SQL,
    _select_control_plane_env,
    _resolve_control_plane_database,
)

from yoke_cli.config.db_admin_project_database import (
    DeclaredDatabase,
    declared_admin_env_name,
    read_declared_database,
)
from yoke_cli.config.db_admin_profile_write import _write_connection
from yoke_cli.config import db_admin_box_mode as box_mode
from yoke_cli.config.db_admin_setup_report import (
    _path_ref,
    dumps_json,
    environment_summary,
    render_human,
)

DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_ADMIN_ENV_SUFFIX = contract.DB_ADMIN_ENV_SUFFIX
DEFAULT_LOCAL_PORTS = {
    "prod": 6547,
    "stage": 6548,
}
AUTHORITY_KIND = box_mode.BOX_AUTHORITY_KIND


def admin_env_name(env_name: str) -> str:
    env = _safe_label(env_name, what="environment")
    return f"{env}{DEFAULT_ADMIN_ENV_SUFFIX}"


def secret_name(project: str, env_name: str) -> str:
    return (
        f"{_safe_label(project, what='project')}-"
        f"{_safe_label(env_name, what='environment')}"
        f"{contract.DB_ADMIN_ENV_SUFFIX}"
    )


def default_local_port(env_name: str) -> int:
    return DEFAULT_LOCAL_PORTS.get(env_name, 6549)


def build_report(
    *,
    project: str,
    env_name: str,
    config_path: str | Path | None,
    admin_env: str | None,
    local_port: int | None,
    secret_label: str | None,
    control_plane_env: str | None,
    apply: bool,
    set_active_env: bool,
    allow_render_only: bool,
    protected: bool = False,
    database: str | None = None,
    emit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Plan or apply one machine-local db-admin profile.

    Without ``database`` the profile reaches the Yoke control-plane database
    the named HTTPS control plane serves. With ``database`` it reaches the
    project's own declared database model instead.
    """
    try:
        project = _safe_label(required_project_context(project), what="project")
    except MissingProjectError as exc:
        raise DbAdminSetupError(str(exc)) from exc
    env_name = _safe_label(env_name, what="environment")
    selected_port = int(local_port or default_local_port(env_name))
    env = _resolve_environment(project, env_name)
    project = str(env.project)
    selected_control_plane_env = _select_control_plane_env(
        env_name,
        control_plane_env=control_plane_env,
        config_path=config_path,
    )
    declared: DeclaredDatabase | None = None
    if database:
        declared = read_declared_database(
            project,
            database,
            control_plane_env=selected_control_plane_env,
            config_path=config_path,
        )
        default_label = declared_admin_env_name(project, env_name, declared.model)
        selected_admin_env = admin_env or default_label
    else:
        default_label = secret_name(project, env_name)
        selected_admin_env = admin_env or admin_env_name(env_name)
    if env.activation_state == "render_only" and not allow_render_only:
        raise DbAdminSetupError(
            f"{project}/{env_name} is declared render_only; set "
            "environments.settings.pulumi.activation_state=active before "
            f"creating {selected_admin_env}"
        )
    if declared is None:
        database_name = _resolve_control_plane_database(
            selected_control_plane_env,
            config_path=config_path,
        )
    else:
        database_name = declared.database_name

    postgres = _postgres_metadata(env, selected_port)
    dsn_path = box_mode.dsn_file_path(secret_label or default_label)
    authority, steps = box_mode.plan(
        env, postgres=postgres, database_name=database_name, dsn_path=dsn_path
    )
    plan: dict[str, Any] = {
        "admin_env": selected_admin_env,
        "postgres": postgres,
        "authority": authority,
        "steps": steps,
        "dsn_file": _path_ref(dsn_path),
    }
    report: dict[str, Any] = {
        "operation": "dev.db_admin.setup",
        "applied": False,
        "project": project,
        "declared_deploy_database": str(env.database_name),
        "control_plane_env": selected_control_plane_env,
        "environment": environment_summary(env),
        "plan": plan,
        "message": "write plan only; rerun with --yes to apply",
    }
    if declared is None:
        report["control_plane_database"] = database_name
    else:
        report["declared_database"] = declared.as_report()
        steps.insert(
            1,
            {
                "action": "resolve-declared-database-location",
                "target": f"{project}/{declared.model}",
            },
        )
    if not apply:
        return report

    credential_source, report["box_hop"] = box_mode.apply(
        env,
        dsn_path,
        admin_env=selected_admin_env,
        local_port=selected_port,
        database_name=database_name,
    )
    configured = _write_connection(
        env_name=selected_admin_env,
        credential_source=credential_source,
        config_path=config_path,
        postgres=postgres,
        authority=authority,
        protected=protected,
        set_active_env=set_active_env,
    )
    report.update(
        {
            "applied": True,
            "admin_connection": configured,
            "message": f"{selected_admin_env} configured",
        }
    )
    if declared is not None:
        report["release_admin_connection_command"] = (
            f"yoke projects environment-settings merge --project {project} "
            f"--environment {env_name} --set release.admin_connection={selected_admin_env}"
        )
    return report


def _resolve_environment(project: str, env_name: str) -> Any:
    try:
        module = importlib.import_module("yoke_core.domain.deploy_environment_settings")
    except ModuleNotFoundError as exc:
        raise DbAdminSetupError(
            "db-admin setup requires the yoke-core engine's deploy modules, "
            "which are not importable here; reinstall Yoke or run from a "
            "source checkout"
        ) from exc
    try:
        return module.resolve_deploy_environment(project, env_name)
    except Exception as exc:  # noqa: BLE001
        raise DbAdminSetupError(str(exc)) from exc


def _postgres_metadata(env: Any, local_port: int) -> dict[str, Any]:
    return {
        "host": DEFAULT_LOCAL_HOST,
        "port": local_port,
        "tunnel": {
            "kind": "ssh",
            "bastion": env.ssh_target,
            "identity_file": env.ssh_key_path,
            "remote_host": "",
            "remote_port": 5432,
        },
    }


__all__ = [
    "AUTHORITY_KIND",
    "DEFAULT_ADMIN_ENV_SUFFIX",
    "DEFAULT_LOCAL_HOST",
    "DEFAULT_LOCAL_PORTS",
    "DbAdminSetupError",
    "CONTROL_PLANE_DATABASE_SQL",
    "admin_env_name",
    "build_report",
    "default_local_port",
    "dumps_json",
    "render_human",
    "secret_name",
]
