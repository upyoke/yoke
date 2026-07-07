"""Repo-root, subprocess PYTHONPATH, and Postgres connection factories.

Owns the low-level IO infrastructure consumed by every service_client
sub-module: importable repo root, the PYTHONPATH propagated to spawned
subprocesses, the read-only and read-write connection factories, and the
routing-config loader.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the repo root is importable when called from anywhere
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


def _subprocess_pythonpath() -> str:
    """Return a PYTHONPATH that keeps Yoke importable in child processes."""
    existing = os.environ.get("PYTHONPATH", "")
    return f"{_repo_root}{os.pathsep}{existing}" if existing else _repo_root


def _connected_env_allowed_in_this_process() -> bool:
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        or "pytest" in sys.modules
    ):
        from yoke_core.domain import yoke_connected_env

        return os.environ.get(yoke_connected_env.PYTEST_ENABLE_ENV) == "1"
    return True


def _repo_connected_backend_env() -> dict:
    """Return connected-env credential vars anchored on this service-client root."""
    if not _connected_env_allowed_in_this_process():
        return {}
    try:
        from yoke_core.domain import db_backend, machine_config, yoke_connected_env

        start = Path.cwd() if "pytest" in sys.modules else Path(_repo_root)
        binding = yoke_connected_env.find_binding(start)
        if not binding:
            return {}
        env = {machine_config.CONFIG_FILE_ENV: str(binding)}
        env.update(
            yoke_connected_env.process_env_overrides(
                dsn_env=db_backend.PG_DSN_ENV,
                dsn_file_env=db_backend.PG_DSN_FILE_ENV,
                start=start,
            )
        )
        return env
    except Exception:
        return {}


def _ensure_repo_backend_env() -> None:
    """Let direct service-client invocations find connected authority off-root."""
    from yoke_core.domain import db_backend

    if os.environ.get(db_backend.PG_DSN_ENV) or os.environ.get(
        db_backend.PG_DSN_FILE_ENV
    ):
        return
    os.environ.update(_repo_connected_backend_env())


def _subprocess_backend_env() -> dict:
    """Postgres authority env vars to forward to a delegated child process."""
    from yoke_core.domain import db_backend

    env = {
        key: os.environ[key]
        for key in (
            db_backend.PG_DSN_ENV,
            db_backend.PG_DSN_FILE_ENV,
        )
        if os.environ.get(key)
    }
    if db_backend.PG_DSN_ENV not in env and db_backend.PG_DSN_FILE_ENV not in env:
        env.update(_repo_connected_backend_env())
    return env


def _subprocess_service_env() -> dict:
    """Environment for delegated Yoke Python children on the same backend."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": _subprocess_pythonpath(),
        **_subprocess_backend_env(),
    }
    return env


def _get_db_path() -> str:
    """Resolve the Yoke DB path via the canonical worktree-aware resolver."""
    from yoke_core.domain.db_helpers import resolve_db_path

    return resolve_db_path()


def _get_config_path() -> Path:
    """Resolve machine config without requiring a live SQLite DB path."""
    from yoke_core.api.routing_config import config_path_from_db_path

    fixture_db = os.environ.get("YOKE_DB")
    if fixture_db and os.environ.get("PYTEST_CURRENT_TEST"):
        return config_path_from_db_path(fixture_db)
    try:
        return config_path_from_db_path(_get_db_path())
    except Exception:
        from yoke_core.domain.worktree_paths import resolve_named_path

        try:
            return Path(resolve_named_path("config", cwd=_repo_root)).resolve()
        except RuntimeError:
            from yoke_core.domain import machine_config

            return machine_config.config_path().resolve()


def _get_db_readonly():
    """Return a Postgres authority connection."""
    from yoke_core.domain import db_backend

    _ensure_repo_backend_env()
    return db_backend.connect()


def _get_db_readwrite():
    """Return a Postgres authority connection."""
    from yoke_core.domain import db_backend

    _ensure_repo_backend_env()
    return db_backend.connect()


def _load_routing_config(conn=None, project_id=None):
    """Load effective routing policy from project capability + machine config."""
    from yoke_core.api.routing_config import (
        load_project_routing_settings,
        load_routing_config,
    )

    project_settings = (
        load_project_routing_settings(conn, project_id)
        if conn is not None and project_id is not None
        else None
    )
    return load_routing_config(
        _get_config_path(),
        project_settings=project_settings,
    )
