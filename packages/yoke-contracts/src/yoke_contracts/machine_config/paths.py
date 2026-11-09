"""Shared machine-home selection and config mutation ownership."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

from yoke_contracts.machine_config.schema import DEFAULT_CONFIG_NAME


DEFAULT_HOME_NAME = ".yoke"

CONFIG_FILE_ENV = "YOKE_MACHINE_CONFIG_FILE"
HOME_ENV = "YOKE_MACHINE_HOME"
_READ_CONFIG: ContextVar[Path | None] = ContextVar("machine_config_read", default=None)


class MachineConfigOwnershipError(RuntimeError):
    """A config mutation targets another machine home."""


def default_yoke_home() -> Path:
    return Path.home() / DEFAULT_HOME_NAME


def yoke_home() -> Path:
    explicit = os.environ.get(HOME_ENV, "").strip()
    return Path(explicit).expanduser() if explicit else Path.home() / ".yoke"


def config_path(explicit: str | Path | None = None) -> Path:
    """Resolve explicit path, isolated home, config-file env, then default."""
    selected = explicit if explicit is not None else _READ_CONFIG.get()
    if selected is not None:
        selected = Path(selected).expanduser()
        return selected if selected.is_absolute() else yoke_home() / selected
    return _ambient_config_path()


@contextmanager
def select_read_config(explicit: str | Path | None) -> Iterator[None]:
    """Select one command's explicit config without changing write ownership."""
    selected = config_path(explicit) if explicit is not None else _READ_CONFIG.get()
    token = _READ_CONFIG.set(selected)
    try:
        yield
    finally:
        _READ_CONFIG.reset(token)


def _ambient_config_path() -> Path:
    home = yoke_home()
    if os.environ.get(HOME_ENV, "").strip():
        return home / DEFAULT_CONFIG_NAME
    override = os.environ.get(CONFIG_FILE_ENV, "").strip()
    if override:
        selected = Path(override).expanduser()
        return selected if selected.is_absolute() else home / selected
    return home / DEFAULT_CONFIG_NAME


def assert_write_owned(selected: str | Path) -> None:
    """Confine config writes to the selected config or explicit machine home.

    Resolve physical paths so a symlink or '..' cannot escape the boundary.
    Without a home override the config-file environment selects the owned
    config; an explicit command path alone cannot authorize a foreign write.
    """
    try:
        home = yoke_home().resolve()
        target = Path(selected).expanduser().resolve()
        owned = _ambient_config_path().resolve()
    except (OSError, RuntimeError) as exc:
        raise MachineConfigOwnershipError(
            f"machine_config_ownership_unresolved: cannot resolve {selected}; "
            "repair the config path and machine-home symlinks, then retry."
        ) from exc
    explicit_home = bool(os.environ.get(HOME_ENV, "").strip())
    permitted = target.is_relative_to(home) if explicit_home else target == owned
    if not permitted:
        boundary = f"machine home {home}" if explicit_home else f"config {owned}"
        raise MachineConfigOwnershipError(
            f"machine_config_not_owned: {target} is not owned by the selected "
            f"{boundary}; remove --config and retry with the selected config. "
            f"For isolation, set {HOME_ENV} to the worker's own directory."
        )
