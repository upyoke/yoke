"""Serialized machine-config metadata merge for source-dev setup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_machine_operation
from yoke_cli.config import machine_config
from yoke_cli.config import machine_config_file
from yoke_contracts.machine_config import schema as contract


def merge_connection_metadata(
    env_name: str,
    config_path: str | Path | None,
    *,
    postgres: Mapping[str, Any] | None,
    authority: Mapping[str, Any] | None,
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    """Merge nonsecret connection metadata under both machine locks."""

    cfg_path = machine_config.config_path(config_path)
    try:
        with github_machine_operation.operation_lock(cfg_path):
            with machine_config_file.exclusive_lock(cfg_path):
                payload = machine_config.load_config(cfg_path)
                entry = payload.setdefault("connections", {}).setdefault(
                    env_name, {},
                )
                entry[contract.PROD_FLAG_KEY] = False
                if postgres:
                    entry["postgres"] = dict(postgres)
                if authority:
                    entry["authority"] = dict(authority)
                _write_payload(payload, cfg_path, error_type=error_type)
                return {
                    "env": env_name,
                    "connection": dict(entry),
                    "config": str(cfg_path),
                }
    except (
        github_machine_operation.GitHubMachineOperationError,
        machine_config.MachineConfigError,
        machine_config_file.MachineConfigFileError,
    ) as exc:
        raise error_type(
            "machine configuration changed or was unavailable during dev setup"
        ) from exc


def _write_payload(
    payload: Mapping[str, Any],
    cfg_path: Path,
    *,
    error_type: type[RuntimeError],
) -> None:
    errors = [
        issue for issue in contract.validate_payload(payload)
        if issue.severity == "error"
    ]
    if errors:
        detail = "\n".join(
            f"  - {issue.code}: {issue.message}" for issue in errors
        )
        raise error_type(f"refusing to write invalid machine config:\n{detail}")
    machine_config_file.atomic_write_text(
        cfg_path, json.dumps(payload, indent=2) + "\n",
    )


__all__ = ["merge_connection_metadata"]
