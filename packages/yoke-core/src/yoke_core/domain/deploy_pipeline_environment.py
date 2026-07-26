"""Deployment pipeline release-control-plane environment labels."""

import os

from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
)


def _normalize_release_control_plane_env(value: str) -> str:
    label = value.strip()
    if label.endswith(DB_ADMIN_ENV_SUFFIX):
        return label[: -len(DB_ADMIN_ENV_SUFFIX)]
    return label


def release_control_plane_env() -> str:
    """Describe where deployment run metadata is being written."""
    active_env = os.environ.get(ENV_OVERRIDE, "")
    if active_env.strip():
        return _normalize_release_control_plane_env(active_env)
    return "unbound"


__all__ = ["release_control_plane_env"]
