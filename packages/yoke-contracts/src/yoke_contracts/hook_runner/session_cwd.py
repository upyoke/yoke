"""Client/authority contracts for session-cwd filesystem evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


CLIENT_SCRATCH_ROOT_KEY = "_yoke_client_scratch_root"
CLIENT_SCRATCH_ROOT_SCHEMA = 1
CLIENT_MACHINE_HOME_KEY = "_yoke_client_machine_home"
CLIENT_MACHINE_HOME_SCHEMA = 1


def _valid_root(root: object) -> str:
    value = root.strip() if isinstance(root, str) else ""
    path = Path(value).expanduser()
    if not value or not path.is_absolute() or path == Path(path.anchor):
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
    path = Path(value)
    resolved = path.resolve()
    if value != str(resolved):
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
