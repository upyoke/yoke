"""Machine-local ``<env>-db-admin`` profile setup."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_cli.config import machine_config
from yoke_cli.config import machine_config_file
from yoke_cli.config import github_machine_operation
from yoke_cli.config import secrets as machine_secrets
from yoke_contracts.machine_config import schema as contract

DEFAULT_PROJECT = "yoke"
DEFAULT_LOCAL_HOST = "127.0.0.1"
DEFAULT_ADMIN_ENV_SUFFIX = "-db-admin"
DEFAULT_LOCAL_PORTS = {
    "prod": 6547,
    "stage": 6548,
}
AUTHORITY_KIND = "aws_aurora_postgres"
ENDPOINT_OUTPUT = "databaseClusterEndpoint"


class DbAdminSetupError(RuntimeError):
    """The db-admin profile setup plan cannot be applied."""


def admin_env_name(env_name: str) -> str:
    env = _safe_label(env_name, what="environment")
    return f"{env}{DEFAULT_ADMIN_ENV_SUFFIX}"


def secret_name(project: str, env_name: str) -> str:
    return (
        f"{_safe_label(project, what='project')}-"
        f"{_safe_label(env_name, what='environment')}-db-admin"
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
    apply: bool,
    set_active_env: bool,
    allow_render_only: bool,
    emit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Plan or apply one machine-local db-admin profile."""
    project = _safe_label(project or DEFAULT_PROJECT, what="project")
    env_name = _safe_label(env_name, what="environment")
    selected_admin_env = admin_env or admin_env_name(env_name)
    selected_port = int(local_port or default_local_port(env_name))
    selected_secret_label = secret_label or secret_name(project, env_name)
    env = _resolve_environment(project, env_name)
    if env.activation_state == "render_only" and not allow_render_only:
        raise DbAdminSetupError(
            f"{project}/{env_name} is declared render_only; set "
            "environments.settings.pulumi.activation_state=active before "
            f"creating {selected_admin_env}"
        )

    superseded_secret_path = machine_secrets.secret_path_no_create(
        selected_secret_label, "dsn"
    )
    postgres = _postgres_metadata(env, selected_port)
    authority = _authority_metadata(env)
    plan = {
        "admin_env": selected_admin_env,
        "superseded_secret_path": _path_ref(superseded_secret_path),
        "postgres": postgres,
        "authority": authority,
        "steps": [
            {
                "action": "resolve-deploy-environment",
                "target": f"{project}/{env_name}",
            },
            {
                "action": "resolve-cloud-postgres-dsn",
                "target": env.stack_name,
            },
            {
                "action": "configure-managed-secret-authority",
                "target": selected_admin_env,
            },
            {
                "action": "remove-superseded-dsn-snapshot",
                "target": _path_ref(superseded_secret_path),
            },
        ],
    }
    report = {
        "operation": "dev.db_admin.setup",
        "applied": False,
        "project": project,
        "environment": _environment_summary(env),
        "plan": plan,
        "message": "write plan only; rerun with --yes to apply",
    }
    if not apply:
        return report

    dsn, outputs = _resolve_environment_dsn(env, emit=emit)
    endpoint = str(outputs.get(ENDPOINT_OUTPUT) or "")
    if endpoint:
        postgres["tunnel"]["remote_host"] = endpoint
    postgres["tunnel"]["remote_port"] = _dsn_port(dsn)
    credential_source = _managed_credential_source(env, outputs)
    configured = _write_connection(
        env_name=selected_admin_env,
        credential_source=credential_source,
        config_path=config_path,
        postgres=postgres,
        authority=authority,
        set_active_env=set_active_env,
    )
    superseded_removed = machine_config_file.remove_file(superseded_secret_path)
    report.update(
        {
            "applied": True,
            "admin_connection": configured,
            "superseded_dsn_snapshot_removed": superseded_removed,
            "message": f"{selected_admin_env} configured",
        }
    )
    return report


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_human(report: Mapping[str, Any]) -> str:
    env = report["environment"]
    lines = [
        "Yoke db-admin setup",
        f"  target: {report['project']}/{env['name']}",
        f"  admin env: {report['plan']['admin_env']}",
        f"  applied: {str(report['applied']).lower()}",
        "",
        "Write plan:",
    ]
    for step in report["plan"]["steps"]:
        lines.append(f"  - {step['action']}: {step['target']}")
    if not report["applied"]:
        lines.extend(["", "Rerun with --yes to apply this plan."])
    lines.append("")
    return "\n".join(lines)


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


def _resolve_environment_dsn(
    env: Any,
    *,
    emit: Callable[[str], None] | None,
) -> tuple[str, Mapping[str, Any]]:
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
        aws_env = deploy_remote.aws_capability_env(env.project, env.aws_region)
        runner = deploy_remote.CommandRunner()
        return deploy_core.resolve_environment_dsn(
            runner,
            env,
            aws_env,
            emit=emit or (lambda _line: None),
        )
    except Exception as exc:  # noqa: BLE001
        raise DbAdminSetupError(
            f"could not resolve {env.project}/{env.env_name} database DSN: {exc}"
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


def _authority_metadata(env: Any) -> dict[str, Any]:
    return {
        "kind": AUTHORITY_KIND,
        "location": {
            "stack": env.stack_name,
            "region": env.aws_region,
            "database_name": env.database_name,
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


def _dsn_port(dsn: str) -> int:
    match = re.search(r"(?:^|\s)port=(\d+)", dsn)
    return int(match.group(1)) if match else 5432


def _write_connection(
    *,
    env_name: str,
    credential_source: Mapping[str, Any],
    config_path: str | Path | None,
    postgres: Mapping[str, Any],
    authority: Mapping[str, Any],
    set_active_env: bool,
) -> dict[str, Any]:
    cfg_path = machine_config.config_path(config_path)
    try:
        with github_machine_operation.operation_lock(cfg_path):
            with machine_config_file.exclusive_lock(cfg_path):
                payload = machine_config.load_config(cfg_path)
                if not payload:
                    payload = {"schema_version": contract.SCHEMA_VERSION}
                connections = payload.setdefault("connections", {})
                if not isinstance(connections, dict):
                    raise DbAdminSetupError(
                        "connections must be an object; repair the file first"
                    )
                entry = {
                    "transport": "local-postgres",
                    contract.PROD_FLAG_KEY: False,
                    "credential_source": dict(credential_source),
                    "postgres": dict(postgres),
                    "authority": dict(authority),
                }
                connections[env_name] = entry
                if set_active_env or not str(payload.get("active_env") or "").strip():
                    payload["active_env"] = env_name
                _write_payload(payload, cfg_path)
                return {
                    "env": env_name,
                    "connection": dict(entry),
                    "active_env": payload.get("active_env"),
                    "config": str(cfg_path),
                }
    except (
        github_machine_operation.GitHubMachineOperationError,
        machine_config.MachineConfigError,
        machine_config_file.MachineConfigFileError,
    ) as exc:
        raise DbAdminSetupError(
            "machine configuration changed or was unavailable during db-admin setup"
        ) from exc


def _managed_credential_source(
    env: Any,
    outputs: Mapping[str, Any],
) -> dict[str, str]:
    try:
        authority = importlib.import_module("yoke_core.domain.yoke_cloud_db_authority")
    except ModuleNotFoundError as exc:
        raise DbAdminSetupError(
            "db-admin setup requires the yoke-core cloud database authority "
            "module, which is not importable here"
        ) from exc
    output_name = authority.DEFAULT_SECRET_ARN_OUTPUT
    secret_arn = str(outputs.get(output_name) or "").strip()
    if not secret_arn:
        raise DbAdminSetupError(
            f"stack {env.stack_name} outputs are missing {output_name}"
        )
    return {
        "kind": contract.CREDENTIAL_KIND_AWS_SECRETS_MANAGER,
        "secret_arn": secret_arn,
        "region": str(env.aws_region),
        "project": str(env.project),
    }


def _write_payload(payload: Mapping[str, Any], cfg_path: Path) -> None:
    errors = [
        issue
        for issue in contract.validate_payload(payload)
        if issue.severity == "error"
    ]
    if errors:
        detail = "\n".join(f"  - {issue.code}: {issue.message}" for issue in errors)
        raise DbAdminSetupError(f"refusing to write invalid machine config:\n{detail}")
    machine_config_file.atomic_write_text(
        cfg_path,
        json.dumps(payload, indent=2) + "\n",
    )


def _path_ref(path: Path) -> str:
    resolved = path.expanduser()
    default_home = Path.home() / ".yoke"
    try:
        rel = resolved.relative_to(default_home)
    except ValueError:
        return str(resolved)
    return "~/.yoke/" + rel.as_posix()


def _safe_label(value: str, *, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DbAdminSetupError(f"{what} must be non-empty")
    if any(char.isspace() for char in text):
        raise DbAdminSetupError(f"{what} must not contain whitespace")
    return text


__all__ = [
    "AUTHORITY_KIND",
    "DEFAULT_ADMIN_ENV_SUFFIX",
    "DEFAULT_LOCAL_HOST",
    "DEFAULT_LOCAL_PORTS",
    "DEFAULT_PROJECT",
    "DbAdminSetupError",
    "admin_env_name",
    "build_report",
    "default_local_port",
    "dumps_json",
    "render_human",
    "secret_name",
]
