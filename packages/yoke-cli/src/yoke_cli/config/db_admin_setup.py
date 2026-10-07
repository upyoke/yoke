"""Machine-local ``<env>-db-admin`` profile setup."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_cli.config import machine_config_file
from yoke_cli.config import secrets as machine_secrets
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
from yoke_cli.config.db_admin_setup_report import dumps_json, render_human, _path_ref

DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_ADMIN_ENV_SUFFIX = contract.DB_ADMIN_ENV_SUFFIX
DEFAULT_LOCAL_PORTS = {
    "prod": 6547,
    "stage": 6548,
}
AUTHORITY_KIND = "aws_aurora_postgres"


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
    prod: bool = False,
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
        selected_admin_env = admin_env or declared_admin_env_name(
            project, env_name, declared.model
        )
    else:
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
    authority = _authority_metadata(env, database_name=database_name)
    steps = [
        {"action": "resolve-deploy-environment", "target": f"{project}/{env_name}"},
        {
            "action": "resolve-non-secret-cloud-database-binding",
            "target": env.stack_name,
        },
        {"action": "configure-managed-secret-authority", "target": selected_admin_env},
    ]
    plan: dict[str, Any] = {
        "admin_env": selected_admin_env,
        "postgres": postgres,
        "authority": authority,
        "steps": steps,
    }
    report: dict[str, Any] = {
        "operation": "dev.db_admin.setup",
        "applied": False,
        "project": project,
        "declared_deploy_database": str(env.database_name),
        "control_plane_env": selected_control_plane_env,
        "environment": _environment_summary(env),
        "plan": plan,
        "message": "write plan only; rerun with --yes to apply",
    }
    superseded_secret_path = None
    if declared is None:
        report["control_plane_database"] = database_name
        superseded_secret_path = machine_secrets.secret_path_no_create(
            secret_label or secret_name(project, env_name), "dsn"
        )
        plan["superseded_secret_path"] = _path_ref(superseded_secret_path)
        steps.append(
            {
                "action": "remove-superseded-dsn-snapshot",
                "target": _path_ref(superseded_secret_path),
            }
        )
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

    binding, outputs = _resolve_environment_database_binding(env, emit=emit)
    if declared is None:
        remote_host = str(binding.host)
    else:
        remote_host = _required_output(env, outputs, declared.endpoint_output)
    postgres["tunnel"]["remote_host"] = remote_host
    postgres["tunnel"]["remote_port"] = int(binding.port)
    credential_source = _managed_credential_source(
        env,
        outputs,
        output_name=declared.secret_arn_output if declared else None,
    )
    configured = _write_connection(
        env_name=selected_admin_env,
        credential_source=credential_source,
        config_path=config_path,
        postgres=postgres,
        authority=authority,
        prod=prod,
        set_active_env=set_active_env,
    )
    report.update(
        {
            "applied": True,
            "admin_connection": configured,
            "message": f"{selected_admin_env} configured",
        }
    )
    if superseded_secret_path is not None:
        report["superseded_dsn_snapshot_removed"] = machine_config_file.remove_file(
            superseded_secret_path
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


def _resolve_environment_database_binding(
    env: Any,
    *,
    emit: Callable[[str], None] | None,
) -> tuple[Any, Mapping[str, Any]]:
    try:
        deploy_core = importlib.import_module("yoke_core.domain.deploy_core_container")
        deploy_remote = importlib.import_module("yoke_core.domain.deploy_remote")
    except ModuleNotFoundError as exc:
        raise DbAdminSetupError(
            "db-admin setup requires the yoke-core engine's deploy modules, "
            "which are not importable here; reinstall Yoke or run from a "
            "source checkout"
        ) from exc
    try:
        aws_env = deploy_remote.aws_machine_capability_env(env.project, env.aws_region)
    except Exception as exc:  # noqa: BLE001 - every failure here is the same refusal
        raise DbAdminSetupError(
            f"could not resolve {env.project} aws-admin authority from this "
            f"machine's capability store: {exc}"
        ) from exc
    try:
        runner = deploy_remote.CommandRunner()
        return deploy_core.resolve_environment_database_binding(
            runner,
            env,
            aws_env,
            emit=emit or (lambda _line: None),
        )
    except Exception as exc:  # noqa: BLE001
        raise DbAdminSetupError(
            f"could not resolve {env.project}/{env.env_name} database binding: {exc}"
        ) from exc


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


def _authority_metadata(env: Any, *, database_name: str) -> dict[str, Any]:
    return {
        "kind": AUTHORITY_KIND,
        "location": {
            "stack": env.stack_name,
            "region": env.aws_region,
            "database_name": database_name,
        },
    }


def _environment_summary(env: Any) -> dict[str, str]:
    return {
        "project": str(env.project),
        "name": str(env.env_name),
        "activation_state": str(env.activation_state),
        "stack_name": str(env.stack_name),
        "database_name": str(env.database_name),
        "origin_host": str(env.origin_host),
        "ssh_target": str(env.ssh_target),
        "aws_region": str(env.aws_region),
    }


def _managed_credential_source(
    env: Any,
    outputs: Mapping[str, Any],
    *,
    output_name: str | None = None,
) -> dict[str, str]:
    if output_name is None:
        try:
            authority = importlib.import_module(
                "yoke_core.domain.yoke_cloud_db_authority"
            )
        except ModuleNotFoundError as exc:
            raise DbAdminSetupError(
                "db-admin setup requires the yoke-core cloud database authority "
                "module, which is not importable here"
            ) from exc
        output_name = authority.DEFAULT_SECRET_ARN_OUTPUT
    secret_arn = _required_output(env, outputs, output_name)
    return {
        "kind": contract.CREDENTIAL_KIND_AWS_SECRETS_MANAGER,
        "secret_arn": secret_arn,
        "region": str(env.aws_region),
        "project": str(env.project),
    }


def _required_output(env: Any, outputs: Mapping[str, Any], name: str) -> str:
    value = str(outputs.get(name) or "").strip()
    if not value:
        raise DbAdminSetupError(
            f"stack {env.stack_name} outputs are missing {name}; deploy the "
            f"{env.project}/{env.env_name} stack or correct the declared output name"
        )
    return value


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
