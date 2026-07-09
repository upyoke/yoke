"""Yoke-owned machine secret storage helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as contract


class MachineSecretError(RuntimeError):
    """Machine secret input or storage failed."""


def store_machine_secret(name: str, suffix: str, secret: str) -> Path:
    value = secret.strip()
    if not value:
        raise MachineSecretError(f"{suffix} is empty")
    path = secret_path(name, suffix)
    _write_secret(path, value)
    return path


def store_github_token(secret: str) -> Path:
    return store_machine_secret("github", "token", secret)


def read_secret_file(path: str | Path, label: str) -> str:
    selected = Path(path).expanduser()
    if not selected.is_file():
        raise MachineSecretError(f"{label} file is missing: {selected}")
    try:
        value = selected.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MachineSecretError(f"{label} file is unreadable: {selected}") from exc
    if not value:
        raise MachineSecretError(f"{label} file is empty: {selected}")
    return value


def read_stdin_secret(label: str) -> str:
    value = sys.stdin.read().strip()
    if not value:
        raise MachineSecretError(f"no {label} on stdin")
    return value


def replace_secret_file(path: str | Path, label: str, secret: str) -> Path:
    value = secret.strip()
    if not value:
        raise MachineSecretError(f"{label} is empty")
    selected = Path(path).expanduser()
    selected.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_secret(selected, value)
    return selected


def secret_path(name: str, suffix: str) -> Path:
    return _secret_path(name, suffix, create_parent=True)


def secret_path_no_create(name: str, suffix: str) -> Path:
    return _secret_path(name, suffix, create_parent=False)


def _secret_path(name: str, suffix: str, *, create_parent: bool) -> Path:
    safe = "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in name.strip()
    ).strip("._-")
    if not safe:
        raise MachineSecretError("secret name must include a filesystem-safe label")
    directory = (
        secrets_dir()
        if create_parent
        else machine_config.yoke_home() / contract.SECRETS_DIR_NAME
    )
    return directory / f"{safe}.{suffix}"


def secrets_dir() -> Path:
    directory = machine_config.yoke_home() / contract.SECRETS_DIR_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _write_secret(path: Path, secret: str) -> None:
    _refuse_unisolated_test_write(path)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(secret + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    os.replace(tmp_path, path)


def _refuse_unisolated_test_write(path: Path) -> None:
    """Refuse to write a secret into the real machine home under test.

    A real incident: an unisolated test wrote a stub token over the operator's
    live ``~/.yoke/secrets/prod.token``, 401-ing every prod call. Under
    pytest the writer must target an isolated home (set ``YOKE_MACHINE_HOME``
    to a temp dir, as ``runtime/api/conftest.py`` does); writing into the real
    home is refused so a test can never clobber real credentials.
    """
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return
    real_home = (Path.home() / ".yoke").resolve()
    try:
        path.resolve().relative_to(real_home)
    except (ValueError, OSError):
        return
    raise MachineSecretError(
        f"refusing to write a secret into the real machine home under test "
        f"({path}); set YOKE_MACHINE_HOME to a temp dir to isolate the test"
    )


__all__ = [
    "MachineSecretError",
    "replace_secret_file",
    "read_secret_file",
    "read_stdin_secret",
    "secret_path",
    "secret_path_no_create",
    "secrets_dir",
    "store_github_token",
    "store_machine_secret",
]
