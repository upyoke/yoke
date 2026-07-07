"""Machine-local storage for project capability secrets."""

from __future__ import annotations

import os
from pathlib import Path

from yoke_contracts.machine_config import capability_secrets as contract
from yoke_contracts.machine_config import schema as machine_contract

from yoke_core.domain import machine_config


class MachineCapabilitySecretError(RuntimeError):
    """Machine-local capability secret storage failed."""


def machine_capability_secret_path(
    project_slug: str,
    cap_type: str,
    key: str,
) -> Path:
    """Return the deterministic local path for a capability secret."""
    return (
        machine_config.yoke_home()
        / machine_contract.SECRETS_DIR_NAME
        / contract.capability_secret_relative_path(project_slug, cap_type, key)
    )


def read_machine_capability_secret(
    project_slug: str,
    cap_type: str,
    key: str,
) -> str | None:
    """Read a machine-local capability secret, or ``None`` when absent."""
    path = machine_capability_secret_path(project_slug, cap_type, key)
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MachineCapabilitySecretError(
            f"{cap_type}.{key} file is unreadable: {path}"
        ) from exc
    if not value:
        raise MachineCapabilitySecretError(
            f"{cap_type}.{key} file is empty: {path}"
        )
    return value


def store_machine_capability_secret(
    project_slug: str,
    cap_type: str,
    key: str,
    secret: str,
) -> Path:
    """Write a machine-local capability secret with owner-only permissions."""
    value = str(secret or "").strip()
    if not value:
        raise MachineCapabilitySecretError(f"{cap_type}.{key} is empty")
    path = machine_capability_secret_path(project_slug, cap_type, key)
    _write_secret(path, value)
    return path


def list_machine_capability_secret_keys(project_slug: str, cap_type: str) -> list[str]:
    """List present local secret key files for a machine-local capability."""
    base = (
        machine_config.yoke_home()
        / machine_contract.SECRETS_DIR_NAME
        / contract.capability_secret_directory_relative_path(project_slug, cap_type)
    )
    if not base.is_dir():
        return []
    allowed = contract.machine_local_capability_secret_keys(cap_type)
    return sorted(
        path.name for path in base.iterdir()
        if path.is_file() and path.name in allowed
    )


def _write_secret(path: Path, secret: str) -> None:
    _refuse_unisolated_test_write(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_private_dirs(path.parent)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(secret + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    os.replace(tmp_path, path)
    path.chmod(0o600)


def _chmod_private_dirs(directory: Path) -> None:
    secrets_root = (
        machine_config.yoke_home() / machine_contract.SECRETS_DIR_NAME
    ).resolve()
    current = directory.resolve()
    while True:
        try:
            current.relative_to(secrets_root)
        except ValueError:
            break
        current.chmod(0o700)
        if current == secrets_root:
            break
        current = current.parent


def _refuse_unisolated_test_write(path: Path) -> None:
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return
    real_home = (Path.home() / ".yoke").resolve()
    try:
        path.resolve().relative_to(real_home)
    except (ValueError, OSError):
        return
    raise MachineCapabilitySecretError(
        f"refusing to write a secret into the real machine home under test "
        f"({path}); set YOKE_MACHINE_HOME to a temp dir"
    )


__all__ = [
    "MachineCapabilitySecretError",
    "list_machine_capability_secret_keys",
    "machine_capability_secret_path",
    "read_machine_capability_secret",
    "store_machine_capability_secret",
]
