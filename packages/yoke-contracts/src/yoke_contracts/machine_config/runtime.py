"""Machine-local Yoke configuration.

The cloud-runtime local shape keeps machine/runtime selection in
``~/.yoke/config.json``. Project repos carry only project-local generated
views and policy files under ``.yoke/``; repo-root ``data/`` is not an
authority surface.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config import schema as contract


CONFIG_FILE_ENV = "YOKE_MACHINE_CONFIG_FILE"
HOME_ENV = "YOKE_MACHINE_HOME"
DEFAULT_CONFIG_NAME = contract.DEFAULT_CONFIG_NAME
DEFAULT_BOARD_PATH = contract.DEFAULT_BOARD_PATH
DEFAULT_CACHE_DIR_NAME = contract.DEFAULT_CACHE_DIR_NAME
DEFAULT_TEMP_ROOT = contract.DEFAULT_TEMP_ROOT


class MachineConfigError(RuntimeError):
    """Raised when machine config exists but is malformed."""


def yoke_home() -> Path:
    """Return the machine-local Yoke directory."""

    explicit = os.environ.get(HOME_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".yoke"


def config_path(explicit: str | Path | None = None) -> Path:
    """Return the selected machine config file path."""

    # Route overrides through _machine_path so a relative value anchors under
    # the machine home, never the current working directory (which would write
    # config into whatever checkout/worktree the process happens to run from).
    if explicit is not None:
        return _machine_path(explicit)
    env_path = os.environ.get(CONFIG_FILE_ENV, "").strip()
    if env_path:
        return _machine_path(env_path)
    return yoke_home() / DEFAULT_CONFIG_NAME


def cache_dir(path: str | Path | None = None) -> Path:
    """Return the machine-local Yoke cache directory."""

    cfg = load_config(path)
    value = cfg.get("cache_dir")
    raw = value if isinstance(value, str) and value.strip() else contract.DEFAULT_CACHE_ROOT
    return _machine_path(raw)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load ``~/.yoke/config.json`` or return ``{}`` when absent."""

    cfg_path = config_path(path)
    if not cfg_path.is_file():
        return {}
    try:
        with cfg_path.open() as _fh:
            payload = json.load(_fh)
    except ValueError as exc:
        raise MachineConfigError(f"{cfg_path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MachineConfigError(f"{cfg_path} must contain a JSON object")
    return payload


def normalized_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load machine config and fill contract defaults."""

    return contract.normalize_payload(load_config(path))


def active_connection(
    path: str | Path | None = None,
    *,
    explicit_env: str | None = None,
) -> Mapping[str, Any]:
    """Return the selected active connection per the machine contract."""

    return contract.active_connection(load_config(path), explicit_env=explicit_env)


def active_env(
    path: str | Path | None = None,
    *,
    explicit_env: str | None = None,
) -> str:
    """Return selected env using explicit, ``YOKE_ENV``, then config."""

    return contract.selected_env(load_config(path), explicit_env=explicit_env)


def read_settings(path: str | Path | None = None) -> dict[str, str]:
    """Return machine ``settings`` as string values for legacy callers."""

    raw = load_config(path).get("settings", {})
    if not isinstance(raw, Mapping):
        return {}
    values: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            continue
        if value is None:
            continue
        if isinstance(value, bool):
            values[key] = "true" if value else "false"
        else:
            values[key] = str(value)
    return values


def temp_root(path: str | Path | None = None) -> str:
    """Return the configured machine temp root."""

    cfg = load_config(path)
    value = cfg.get("temp_root")
    raw = value if isinstance(value, str) and value.strip() else DEFAULT_TEMP_ROOT
    return str(_machine_path(raw))


def project_entry(repo_root: str | Path, path: str | Path | None = None) -> dict[str, Any]:
    """Return the machine-config entry for a checkout, or ``{}``."""

    entry = contract.project_entry_for_checkout(load_config(path), repo_root)
    project_id = contract.normalize_project_id(entry.get("project_id"))
    if project_id is not None:
        entry["project_id"] = project_id
    return entry


def project_id(repo_root: str | Path, path: str | Path | None = None) -> int | None:
    """Resolve the numeric project id for a checkout."""

    return contract.normalize_project_id(project_entry(repo_root, path).get("project_id"))


def installed_project_ids(path: str | Path | None = None) -> set[int]:
    """Return the distinct project ids installed on this machine.

    Sourced from the ``projects`` map in machine config (checkout path -> entry).
    Used to disambiguate a bare item number when there is no explicit/cwd
    project context.
    """

    cfg = load_config(path)
    projects = cfg.get("projects", {})
    ids: set[int] = set()
    if isinstance(projects, Mapping):
        for entry in projects.values():
            if isinstance(entry, Mapping):
                pid = contract.normalize_project_id(entry.get("project_id"))
                if pid is not None:
                    ids.add(pid)
    return ids


def board_scope(
    repo_root: str | Path,
    explicit: str | None = None,
    path: str | Path | None = None,
) -> str:
    """Resolve the board scope for a checkout."""

    if explicit:
        return explicit
    board = project_entry(repo_root, path).get("board", {})
    if isinstance(board, Mapping):
        value = board.get("scope")
        if isinstance(value, str) and value.strip():
            return value.strip()
    pid = project_id(repo_root, path)
    return str(pid) if pid is not None else "all"


def board_render_path(
    repo_root: str | Path,
    explicit: str | Path | None = None,
    path: str | Path | None = None,
) -> Path:
    """Resolve the generated board path for a checkout."""

    root = Path(repo_root).expanduser()
    raw: str | Path | None = explicit
    if raw is None:
        board = project_entry(root, path).get("board", {})
        if isinstance(board, Mapping):
            value = board.get("render_path")
            if isinstance(value, str) and value.strip():
                raw = value.strip()
    selected = Path(raw or DEFAULT_BOARD_PATH).expanduser()
    if selected.is_absolute():
        return selected
    return root / selected


def board_art_path(
    repo_root: str | Path,
    path: str | Path | None = None,
) -> Path:
    """Return the project-local board art path for a checkout."""

    root = Path(repo_root).expanduser()
    return root / ".yoke" / "board-art"


def _machine_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return yoke_home() / path


__all__ = [
    "CONFIG_FILE_ENV",
    "DEFAULT_BOARD_PATH",
    "DEFAULT_CACHE_DIR_NAME",
    "DEFAULT_TEMP_ROOT",
    "HOME_ENV",
    "MachineConfigError",
    "active_connection",
    "active_env",
    "board_art_path",
    "board_render_path",
    "cache_dir",
    "board_scope",
    "config_path",
    "load_config",
    "normalized_config",
    "project_entry",
    "project_id",
    "read_settings",
    "yoke_home",
    "temp_root",
]
