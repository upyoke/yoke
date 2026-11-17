"""Client/authority contracts for session-cwd filesystem evidence."""

from __future__ import annotations

from pathlib import PureWindowsPath, PurePosixPath
from yoke_contracts.hook_runner.bash_paths import lexical_client_path, is_absolute, windows_path
from typing import Any, Mapping


CLIENT_SCRATCH_ROOT_KEY = "_yoke_client_scratch_root"
CLIENT_SCRATCH_ROOT_SCHEMA = 1
CLIENT_MACHINE_HOME_KEY = "_yoke_client_machine_home"
CLIENT_MACHINE_HOME_SCHEMA = 1


def _valid_root(root: object) -> str:
    value = root.strip() if isinstance(root, str) else ""
    path = PureWindowsPath(value) if windows_path(value) else PurePosixPath(value)
    if not value or not is_absolute(value) or str(path) == path.anchor:
        return ""
    return value


def client_scratch_root_fact(root: str) -> dict[str, object]:
    """Build the relayed fact naming the client machine's scratch root."""

    value = _valid_root(root)
    if not value:
        return {}
    return {
        CLIENT_SCRATCH_ROOT_KEY: {
            "schema": CLIENT_SCRATCH_ROOT_SCHEMA,
            "root": value,
        }
    }


def client_scratch_root(payload: Mapping[str, Any]) -> str:
    """Return a schema-validated client scratch root from a hook payload."""

    raw = payload.get(CLIENT_SCRATCH_ROOT_KEY)
    if not isinstance(raw, Mapping):
        return ""
    if raw.get("schema") != CLIENT_SCRATCH_ROOT_SCHEMA:
        return ""
    return _valid_root(raw.get("root"))


def _valid_machine_home(root: object) -> str:
    value = _valid_root(root)
    if not value:
        return ""
    resolved = lexical_client_path(value)
    expected, actual = value, resolved
    if windows_path(value):
        expected, actual = value.replace("\\", "/").casefold(), resolved.replace("\\", "/").casefold()
    if expected != actual:
        return ""
    return value


def client_machine_home_fact(root: str) -> dict[str, object]:
    """Build the relayed fact naming the client's canonical home."""
    value = _valid_machine_home(root)
    if not value:
        return {}
    return {
        CLIENT_MACHINE_HOME_KEY: {
            "schema": CLIENT_MACHINE_HOME_SCHEMA,
            "root": value,
        }
    }


def client_machine_home(payload: Mapping[str, Any]) -> str:
    """Return the schema-validated client home from a hook payload."""
    raw = payload.get(CLIENT_MACHINE_HOME_KEY)
    if not isinstance(raw, Mapping):
        return ""
    if raw.get("schema") != CLIENT_MACHINE_HOME_SCHEMA:
        return ""
    return _valid_machine_home(raw.get("root"))


__all__ = [
    "CLIENT_MACHINE_HOME_KEY",
    "CLIENT_MACHINE_HOME_SCHEMA",
    "CLIENT_SCRATCH_ROOT_KEY",
    "CLIENT_SCRATCH_ROOT_SCHEMA",
    "client_machine_home",
    "client_machine_home_fact",
    "client_scratch_root",
    "client_scratch_root_fact",
]
