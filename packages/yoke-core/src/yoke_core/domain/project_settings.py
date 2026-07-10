"""Project setting readers with DB/local authority split.

Shared project behavior is DB-owned through the ``project-policy``
capability.  Machine-local checkout facts are local-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from yoke_contracts.project_contract.project_keys import (
    DB_PROJECT_POLICY_KEYS,
    LOCAL_PROJECT_KEYS,
    RECOGNIZED_PROJECT_KEYS,
)


def get_project_str(
    repo_root: "Path | str | None",
    key: str,
    default: "str | None" = None,
    *,
    config_path: "Path | str | None" = None,
) -> str:
    """Read a project setting using its current authority."""

    resolved_default = _default_for_key(key, default)
    if key in LOCAL_PROJECT_KEYS:
        from yoke_core.domain import runtime_settings

        return (
            runtime_settings.get_str(key, "", config_path=config_path)
            or resolved_default
        )
    if key in DB_PROJECT_POLICY_KEYS:
        value = _policy_value_for_repo(repo_root, key, config_path=config_path)
        return _string_value(value, resolved_default)
    raise KeyError(key)


def get_project_int(
    repo_root: "Path | str | None",
    key: str,
    default: "int | None" = None,
    *,
    config_path: "Path | str | None" = None,
) -> int:
    """Read an integer project setting using its current authority."""

    resolved_default = int(
        _default_for_key(key, str(default) if default is not None else None)
    )
    if key in LOCAL_PROJECT_KEYS:
        from yoke_core.domain import runtime_settings

        return runtime_settings.get_int(
            key, resolved_default, config_path=config_path,
        )
    if key in DB_PROJECT_POLICY_KEYS:
        value = _policy_value_for_repo(repo_root, key, config_path=config_path)
        return _int_value(value, resolved_default)
    raise KeyError(key)


def get_project_str_for_id(
    project_id: int | None,
    key: str,
    default: "str | None" = None,
    *,
    db_path: str | None = None,
) -> str:
    """Read a DB-owned project policy string by project id."""

    resolved_default = _default_for_key(key, default)
    if key not in DB_PROJECT_POLICY_KEYS or project_id is None:
        return resolved_default
    value = _policy_value_for_id(project_id, key, db_path=db_path)
    return _string_value(value, resolved_default)


def get_project_int_for_id(
    project_id: int | None,
    key: str,
    default: "int | None" = None,
    *,
    db_path: str | None = None,
) -> int:
    """Read a DB-owned project policy integer by project id."""

    resolved_default = int(
        _default_for_key(key, str(default) if default is not None else None)
    )
    if key not in DB_PROJECT_POLICY_KEYS or project_id is None:
        return resolved_default
    value = _policy_value_for_id(project_id, key, db_path=db_path)
    return _int_value(value, resolved_default)


def offer_project_config_dir(
    workspace: Optional[str],
    project_scope: Optional[List[int]] = None,
    machine_config_path: Path | str | None = None,
) -> Optional[Path]:
    """Return a machine-local checkout that matches the current context.

    Shared project policy readers should use ``*_for_id`` instead.
    """

    from yoke_core.domain import machine_config

    if workspace:
        root = checkout_root(workspace)
        if root is not None and machine_config.project_id(
            root, machine_config_path,
        ) is not None:
            return root
    if project_scope and len(project_scope) == 1:
        target = int(project_scope[0])
        for checkout, mapped in _mapped_checkouts(machine_config_path):
            if mapped == target and checkout.is_dir():
                return checkout
    return None


def checkout_root(workspace: str) -> Optional[Path]:
    """Walk a workspace path up to its git checkout root."""

    path = Path(workspace).expanduser()
    if not path.exists():
        return None
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return path if path.is_dir() else None


def _policy_value_for_repo(
    repo_root: "Path | str | None",
    key: str,
    *,
    config_path: "Path | str | None" = None,
) -> Any:
    if not repo_root:
        return None
    try:
        from yoke_core.domain import machine_config

        project_id = machine_config.project_id(Path(repo_root), config_path)
    except Exception:
        project_id = None
    if project_id is None:
        return None
    return _policy_value_for_id(project_id, key)


def _policy_value_for_id(
    project_id: int,
    key: str,
    *,
    db_path: str | None = None,
) -> Any:
    try:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.project_policy_capabilities import (
            project_policy_value,
        )

        conn = connect(db_path)
        try:
            return project_policy_value(conn, int(project_id), key)
        finally:
            conn.close()
    except Exception:
        return None


def _mapped_checkouts(
    machine_config_path: Path | str | None,
) -> List[Tuple[Path, int]]:
    from yoke_core.domain import machine_config
    from yoke_contracts.machine_config.schema import mapped_checkouts

    cfg = machine_config.load_config(machine_config_path)
    return [
        (Path(checkout).expanduser(), project_id)
        for checkout, project_id in mapped_checkouts(cfg)
    ]


def _default_for_key(key: str, override: str | None) -> str:
    if override is not None:
        return str(override)
    try:
        return RECOGNIZED_PROJECT_KEYS[key][0]
    except KeyError as exc:
        raise KeyError(key) from exc


def _string_value(value: Any, default: str) -> str:
    if value in (None, ""):
        return default
    return str(value)


def _int_value(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


__all__ = [
    "DB_PROJECT_POLICY_KEYS",
    "LOCAL_PROJECT_KEYS",
    "RECOGNIZED_PROJECT_KEYS",
    "checkout_root",
    "get_project_int",
    "get_project_int_for_id",
    "get_project_str",
    "get_project_str_for_id",
    "offer_project_config_dir",
]
