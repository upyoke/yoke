"""Machine-local Yoke configuration for the installable CLI."""

from __future__ import annotations

from dataclasses import dataclass
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
DEFAULT_CACHE_ROOT = contract.DEFAULT_CACHE_ROOT


class MachineConfigError(RuntimeError):
    """Raised when machine config exists but is malformed."""


@dataclass(frozen=True)
class ConfiguredProject:
    """Read-only view of one checkout registered in machine config."""

    checkout: Path
    project_id: int
    entry: dict[str, Any]


def yoke_home() -> Path:
    explicit = os.environ.get(HOME_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".yoke"


def config_path(explicit: str | Path | None = None) -> Path:
    # Route overrides through _machine_path so a relative value anchors under
    # the machine home, never the current working directory (which would write
    # config into whatever checkout/worktree the process happens to run from).
    if explicit is not None:
        return _machine_path(explicit)
    env_path = os.environ.get(CONFIG_FILE_ENV, "").strip()
    if env_path:
        return _machine_path(env_path)
    return yoke_home() / DEFAULT_CONFIG_NAME


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    selected = config_path(path)
    if not selected.is_file():
        return {}
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise MachineConfigError(f"{selected} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MachineConfigError(f"{selected} must contain a JSON object")
    return payload


def active_connection(
    path: str | Path | None = None,
    *,
    explicit_env: str | None = None,
) -> Mapping[str, Any]:
    return contract.active_connection(load_config(path), explicit_env=explicit_env)


def product_connection(
    path: str | Path | None = None,
    *,
    explicit_env: str | None = None,
) -> Mapping[str, Any]:
    return contract.product_client_connection(
        load_config(path), explicit_env=explicit_env,
    )


def github_config(path: str | Path | None = None) -> dict[str, Any]:
    return contract.github_config(load_config(path))


def active_env(
    path: str | Path | None = None,
    *,
    explicit_env: str | None = None,
) -> str:
    return contract.selected_env(load_config(path), explicit_env=explicit_env)


def cache_dir(path: str | Path | None = None) -> Path:
    cfg = load_config(path)
    value = cfg.get("cache_dir")
    raw = value if isinstance(value, str) and value.strip() else DEFAULT_CACHE_ROOT
    return _machine_path(raw)


def temp_root(path: str | Path | None = None) -> str:
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


def configured_projects(
    path: str | Path | None = None,
    *,
    existing_only: bool = False,
) -> list[ConfiguredProject]:
    """Return project checkout mappings recorded in machine config."""

    payload = load_config(path)
    projects = payload.get("projects", {})
    if not isinstance(projects, Mapping):
        return []
    out: list[ConfiguredProject] = []
    for raw_checkout, raw_entry in projects.items():
        if not isinstance(raw_checkout, str) or not raw_checkout.strip():
            continue
        if not isinstance(raw_entry, Mapping):
            continue
        project_id = contract.normalize_project_id(raw_entry.get("project_id"))
        if project_id is None:
            continue
        checkout = Path(raw_checkout).expanduser()
        if existing_only and not checkout.exists():
            continue
        out.append(ConfiguredProject(
            checkout=checkout,
            project_id=project_id,
            entry=dict(raw_entry),
        ))
    return out


def project_id(repo_root: str | Path, path: str | Path | None = None) -> int | None:
    """Resolve the numeric project id for a checkout."""

    return contract.normalize_project_id(project_entry(repo_root, path).get("project_id"))


def board_scope(
    repo_root: str | Path,
    explicit: str | None = None,
    path: str | Path | None = None,
) -> str:
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


def board_art_path(repo_root: str | Path, path: str | Path | None = None) -> Path:
    root = Path(repo_root).expanduser()
    return root / ".yoke" / "board-art"


def _machine_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return yoke_home() / path


__all__ = [
    "CONFIG_FILE_ENV",
    "ConfiguredProject",
    "DEFAULT_BOARD_PATH",
    "DEFAULT_CACHE_DIR_NAME",
    "DEFAULT_CACHE_ROOT",
    "DEFAULT_CONFIG_NAME",
    "DEFAULT_TEMP_ROOT",
    "HOME_ENV",
    "MachineConfigError",
    "active_connection",
    "active_env",
    "board_art_path",
    "board_render_path",
    "board_scope",
    "cache_dir",
    "config_path",
    "configured_projects",
    "github_config",
    "load_config",
    "project_entry",
    "project_id",
    "product_connection",
    "yoke_home",
    "temp_root",
]
