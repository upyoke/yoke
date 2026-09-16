"""Deployment pipeline release-control-plane environment labels and recipes."""

import os

from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
)

#: Stands in for the control-plane connection wherever the reader's machine is
#: unknown, so a recipe teaches the shape rather than naming a wrong universe.
CONTROL_PLANE_ENV_PLACEHOLDER = "<control-plane>"


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


def watch_deploy_command(run_id: str, env: str = "") -> str:
    """The execute recipe for *run_id*, naming a control-plane connection.

    Ordinary delivery runs over whichever connection holds the run row,
    HTTPS included. Only a deploy replacing that control plane's own serving
    API needs the paired local ``*-db-admin`` connection, and the executor
    refuses that one case by name at the moment it applies. Naming the admin
    connection up front instead would send every operator looking for
    control-plane database credentials they do not need — and that a managed
    project, whose control plane is someone else's, cannot obtain at all.
    """
    connection = str(env or "").strip() or CONTROL_PLANE_ENV_PLACEHOLDER
    return f"yoke --env {connection} watch deploy -- {run_id}"


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
        "with `--env` selecting that control plane."
    )


__all__ = [
    "CONTROL_PLANE_ENV_PLACEHOLDER",
    "release_control_plane_env",
    "run_not_found_message",
    "watch_deploy_command",
]
