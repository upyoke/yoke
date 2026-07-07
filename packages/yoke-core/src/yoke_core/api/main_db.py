"""DB connection factories for the API."""

from __future__ import annotations

from pathlib import Path

from yoke_core.api.repo_root import find_repo_root


def _ensure_repo_backend_env() -> None:
    from yoke_core.api.service_client_shared_io import _ensure_repo_backend_env

    _ensure_repo_backend_env()


def get_config_path() -> Path:
    """Return the Yoke machine config path without requiring SQLite."""
    from yoke_core.api.routing_config import config_path_from_db_path

    try:
        return config_path_from_db_path(get_db_path())
    except Exception:
        from yoke_core.domain.worktree_paths import resolve_named_path

        repo_root = find_repo_root(Path(__file__))
        return Path(resolve_named_path("config", cwd=str(repo_root))).resolve()


def get_db_path() -> str:
    """Return the retired local DB path for legacy diagnostics only."""
    from yoke_core.domain.db_helpers import resolve_db_path

    return resolve_db_path()


def get_db_readonly():
    """Return a Postgres authority connection."""
    from yoke_core.domain import db_backend

    _ensure_repo_backend_env()
    return db_backend.connect()


def get_db_readwrite():
    """Return a Postgres authority connection."""
    from yoke_core.domain import db_backend

    _ensure_repo_backend_env()
    return db_backend.connect()


def _get_repo_root() -> str:
    """Return the repository root directory."""
    try:
        db_path = get_db_path()
        return str(Path(db_path).resolve().parent.parent)
    except Exception:
        return str(find_repo_root(Path(__file__)))
