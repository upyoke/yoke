"""Machine-local state for ``yoke core`` launcher commands."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import machine_config

STATE_DIR_NAME = "local-core"
STATE_FILE_NAME = "state.json"
ENV_FILE_NAME = "local-core.env"
SCHEMA_VERSION = 1


def yoke_home(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser()
    return machine_config.yoke_home()


@contextmanager
def machine_home_override(explicit: str | Path | None):
    if explicit is None:
        yield
        return
    old = os.environ.get(machine_config.HOME_ENV)
    os.environ[machine_config.HOME_ENV] = str(Path(explicit).expanduser())
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(machine_config.HOME_ENV, None)
        else:
            os.environ[machine_config.HOME_ENV] = old


def state_dir(machine_home: str | Path | None = None) -> Path:
    return yoke_home(machine_home) / STATE_DIR_NAME


def state_path(machine_home: str | Path | None = None) -> Path:
    return state_dir(machine_home) / STATE_FILE_NAME


def env_path(machine_home: str | Path | None = None) -> Path:
    return state_dir(machine_home) / ENV_FILE_NAME


def load_state(machine_home: str | Path | None = None) -> dict[str, Any]:
    path = state_path(machine_home)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "schema_version": SCHEMA_VERSION,
            "state_unreadable": True,
            "state_path": str(path),
        }
    return payload if isinstance(payload, dict) else {}


def save_state(
    payload: Mapping[str, Any],
    *,
    machine_home: str | Path | None = None,
) -> Path:
    directory = state_dir(machine_home)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    selected = state_path(machine_home)
    body = dict(payload)
    body["schema_version"] = SCHEMA_VERSION
    body["updated_at"] = now_iso()
    tmp_path = selected.with_name(selected.name + ".tmp")
    tmp_path.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.chmod(0o600)
    os.replace(tmp_path, selected)
    return selected


def write_env_file(
    values: Mapping[str, str],
    *,
    machine_home: str | Path | None = None,
) -> Path:
    directory = state_dir(machine_home)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    selected = env_path(machine_home)
    lines = [f"{key}={value}" for key, value in sorted(values.items())]
    tmp_path = selected.with_name(selected.name + ".tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    os.replace(tmp_path, selected)
    return selected


def read_env_file(machine_home: str | Path | None = None) -> dict[str, str]:
    selected = env_path(machine_home)
    if not selected.is_file():
        return {}
    values: dict[str, str] = {}
    for line in selected.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "ENV_FILE_NAME",
    "SCHEMA_VERSION",
    "STATE_DIR_NAME",
    "STATE_FILE_NAME",
    "env_path",
    "load_state",
    "machine_home_override",
    "read_env_file",
    "save_state",
    "state_dir",
    "state_path",
    "yoke_home",
    "write_env_file",
]
