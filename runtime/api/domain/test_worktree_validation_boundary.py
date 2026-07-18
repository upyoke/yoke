# ruff: noqa: F401, F811
"""Boundary tests for worktree-local SQLite validation paths."""
from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.test_worktree_validation_surface import (
    _seed_capability,
    _webapp_sqlite_settings,
    control_db,
    control_db_env,
)
from yoke_core.domain.worktree_validation_surface import (
    resolve_validation_db_paths,
)


def test_rejects_worktree_root_yoke_db_validation_path(
    tmp_path: Path, control_db_env: str
) -> None:
    settings = _webapp_sqlite_settings()
    settings["models"]["primary"]["validation_surface"]["provisioning"][
        "path"
    ] = "data/yoke.db"
    _seed_capability(control_db_env, "externalwebapp", settings)

    with pytest.raises(ValueError, match="retired Yoke control-plane"):
        resolve_validation_db_paths(tmp_path, "externalwebapp")
