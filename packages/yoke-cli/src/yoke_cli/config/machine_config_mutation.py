"""Serialized, validated machine-config mutation primitives."""

from __future__ import annotations

from functools import wraps
import json
from pathlib import Path
from typing import Any, Callable, TypeVar

from yoke_cli.config import machine_config
from yoke_cli.config import machine_config_file
from yoke_contracts.machine_config import schema as contract


class MachineConfigWriteError(RuntimeError):
    """The requested machine-config mutation cannot be applied."""


_Result = TypeVar("_Result")


def serialized_mutation(
    operation: Callable[..., _Result],
) -> Callable[..., _Result]:
    """Serialize one complete config read-modify-replace transaction."""
    @wraps(operation)
    def locked(*args: Any, **kwargs: Any) -> _Result:
        cfg_path = machine_config.config_path(kwargs.get("path"))
        try:
            with machine_config_file.exclusive_lock(cfg_path):
                return operation(*args, **kwargs)
        except (
            machine_config.MachineConfigError,
            machine_config_file.MachineConfigFileError,
        ) as exc:
            raise MachineConfigWriteError(str(exc)) from exc

    return locked


def load_payload(path: str | Path | None) -> tuple[dict[str, Any], Path]:
    """Load the selected config, seeding the schema version when empty."""
    cfg_path = machine_config.config_path(path)
    payload = machine_config.load_config(path)
    if not payload:
        payload = {"schema_version": contract.SCHEMA_VERSION}
    return payload, cfg_path


def write_payload(payload: dict[str, Any], cfg_path: Path) -> None:
    """Validate and atomically replace one machine-config payload."""
    errors = [
        issue for issue in contract.validate_payload(payload)
        if issue.severity == "error"
    ]
    if errors:
        detail = "\n".join(
            f"  - {issue.code}: {issue.message}"
            + (f" ({issue.path})" if issue.path else "")
            for issue in errors
        )
        raise MachineConfigWriteError(
            f"refusing to write invalid machine config:\n{detail}"
        )
    machine_config_file.atomic_write_text(
        cfg_path, json.dumps(payload, indent=2) + "\n",
    )


__all__ = [
    "MachineConfigWriteError",
    "load_payload",
    "serialized_mutation",
    "write_payload",
]
