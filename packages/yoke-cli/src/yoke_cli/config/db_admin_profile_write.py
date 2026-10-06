"""Write one db-admin connection entry into machine config, atomically."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_machine_operation
from yoke_cli.config import machine_config
from yoke_cli.config import machine_config_file
from yoke_contracts.machine_config import schema as contract
from yoke_cli.config.db_admin_setup_errors import DbAdminSetupError


def _write_connection(
    *,
    env_name: str,
    credential_source: Mapping[str, Any],
    config_path: str | Path | None,
    postgres: Mapping[str, Any],
    authority: Mapping[str, Any],
    prod: bool,
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
                    contract.PROD_FLAG_KEY: bool(prod),
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
