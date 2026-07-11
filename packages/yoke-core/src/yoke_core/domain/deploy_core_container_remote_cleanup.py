"""Post-health image cleanup for core-container remote deploys."""

from __future__ import annotations

import shlex
from typing import Callable

from yoke_core.domain.deploy_core_container_remote_errors import (
    RemoteConvergenceError,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandRunner, run_remote


def prune_superseded_images(
    runner: CommandRunner,
    env: DeployEnvironment,
    emit: Callable[[str], None],
    *,
    keep_image_ref: str,
) -> None:
    """Remove superseded images only from this project's repository.

    The template-owned helper protects every container-owned image plus the
    explicit healthy deployment ref. It never invokes global ``prune --all``,
    so unrelated repositories and intentionally pre-pulled images remain
    outside this deploy's cleanup authority.
    """
    repository = f"{env.registry_host}/{env.repository_name}"
    program = _cleanup_program()
    command = (
        "python3 -"
        f" --repository {shlex.quote(repository)}"
        f" --keep {shlex.quote(keep_image_ref)}"
        " --attempts 1"
    )
    attempts = 3
    last_failure = "unknown Docker failure"
    for attempt in range(1, attempts + 1):
        try:
            prune = run_remote(
                runner,
                env,
                command,
                input_text=program,
                timeout=180,
            )
        except Exception as exc:  # noqa: BLE001 — normalize runner boundaries
            last_failure = exc.__class__.__name__
        else:
            if prune.ok:
                summary = next(
                    (
                        line.strip()
                        for line in reversed((prune.stdout or "").splitlines())
                        if line.strip().startswith("image cleanup: complete")
                    ),
                    "repository-scoped image cleanup complete",
                )
                emit(f"  [core-deploy] {summary}")
                return
            detail = (prune.stderr or prune.stdout or "").strip()[-500:]
            last_failure = detail or f"docker cleanup rc={prune.returncode}"

        if attempt < attempts:
            emit(
                "  [core-deploy] image prune attempt "
                f"{attempt}/{attempts} failed ({last_failure}); retrying"
            )

    raise RemoteConvergenceError(
        "[core-deploy] repository-scoped image cleanup failed after "
        f"{attempts} attempts ({last_failure}); the new container is healthy "
        "but origin disk reclamation is incomplete; rerun the idempotent deploy"
    )


def _cleanup_program() -> str:
    """Load the generic, template-owned shared-host cleanup implementation."""
    from yoke_core.domain.install_bundle import server_tree_root

    path = (
        server_tree_root()
        / "templates"
        / "webapp"
        / "ops"
        / "docker_image_cleanup.py"
    )
    if not path.is_file():
        raise RemoteConvergenceError(
            f"[core-deploy] image cleanup template missing: {path}"
        )
    return path.read_text(encoding="utf-8")
