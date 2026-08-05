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


def run_not_found_message(run_id: str) -> str:
    """Refuse a missing run by naming the control plane that was read.

    A run lives on the control plane that created it, which for a hosted
    deploy is the release control plane rather than the target
    environment's. Without that, "not found" reads as "this run does not
    exist" and sends the operator looking for the wrong thing.
    """
    return (
        f"Error: deployment run '{run_id}' not found on the "
        f"'{release_control_plane_env()}' control plane. Runs are recorded "
        "on the control plane that created them; for a hosted deploy that "
        "is the release control plane, not the target environment's. Retry "
        "against that control plane's db-admin env."
    )


__all__ = ["release_control_plane_env", "run_not_found_message"]
