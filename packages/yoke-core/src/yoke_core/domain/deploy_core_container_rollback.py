"""Health-gate rollback for the core-container deploy executor.

Before the container swap, the executor records the image the box is
currently running. When a post-swap health gate fails (container health,
origin nginx, public URL), the box would otherwise be left running the
NEW broken image; this module redeploys the recorded prior image — one
bounded attempt, loud `[core-deploy]` logging, and a
``DeploymentCoreContainerRolledBack`` event either way.

Rollback is recovery, not success: the caller re-raises the original
health-gate failure after the attempt, the stage still FAILS, and the
run still halts. First deploys (no prior container) skip rollback with
an explicit note.
"""

from __future__ import annotations

import sys
from typing import Callable

from yoke_core.domain.deploy_core_container_remote import (
    RemoteConvergenceError,
    compose_pull_up,
    wait_container_healthy,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import (
    CommandRunner,
    push_remote_file,
    run_remote,
)


def capture_running_image_ref(
    runner: CommandRunner,
    env: DeployEnvironment,
    emit: Callable[[str], None],
) -> str:
    """Record the image the core container is running BEFORE the swap.

    Returns ``""`` when no container is running (first deploy on a fresh
    box, or docker absent) — the caller proceeds; rollback is simply
    unavailable for that deploy.
    """
    probe = run_remote(
        runner,
        env,
        "docker inspect --format '{{.Config.Image}}' "
        f"{env.deploy_namespace}-core",
        timeout=30,
    )
    ref = (probe.stdout or "").strip()
    if not probe.ok or not ref:
        emit(
            "  [core-deploy] no running container before swap (first "
            "deploy?) — health-gate rollback unavailable for this deploy"
        )
        return ""
    emit(f"  [core-deploy] pre-swap running image recorded: {ref}")
    return ref


def attempt_rollback(
    runner: CommandRunner,
    env: DeployEnvironment,
    *,
    prior_image_ref: str,
    failed_image_ref: str,
    render_compose: Callable[[str], str],
    emit: Callable[[str], None],
) -> bool:
    """One bounded rollback to ``prior_image_ref`` after a failed health gate.

    ``render_compose`` maps an image ref to the compose YAML for this env
    (the executor passes its own renderer so the rollback compose matches
    the failed deploy in everything but the image). Returns True when the
    prior container reported healthy again; never raises — the caller
    re-raises the ORIGINAL health-gate failure either way.
    """
    if not prior_image_ref:
        emit(
            "  [core-deploy] ERROR: health gate failed and no pre-swap "
            f"image was recorded — box left on {failed_image_ref}; "
            "recover manually (image_tag override redeploy)"
        )
        return False
    if prior_image_ref == failed_image_ref:
        emit(
            "  [core-deploy] health gate failed on the image that was "
            f"already running ({failed_image_ref}) — rollback would be a "
            "no-op; skipping"
        )
        return False

    emit(
        f"  [core-deploy] ERROR: health gate failed on {failed_image_ref}; "
        f"rolling back to {prior_image_ref} (one attempt)"
    )
    healthy = False
    try:
        push = push_remote_file(
            runner,
            env,
            content=render_compose(prior_image_ref),
            remote_path=f"{env.compose_dir}/docker-compose.yml",
            mode="644",
            sudo=False,
        )
        if not push.ok:
            emit(
                "  [core-deploy] ERROR: rollback compose write failed "
                f"(rc={push.returncode}) — box left on {failed_image_ref}"
            )
        else:
            compose_pull_up(runner, env, emit)
            wait_container_healthy(runner, env, f"{env.deploy_namespace}-core", emit)
            healthy = True
            emit(
                f"  [core-deploy] rolled back: {env.deploy_namespace}-core running "
                f"{prior_image_ref} again (the deploy itself still FAILED)"
            )
    except RemoteConvergenceError as exc:
        emit(
            f"  [core-deploy] ERROR: rollback to {prior_image_ref} did "
            f"not converge: {exc}"
        )
    _emit_rollback_event(
        env, prior_image_ref, failed_image_ref, healthy=healthy
    )
    return healthy


def _emit_rollback_event(
    env: DeployEnvironment,
    prior_image_ref: str,
    failed_image_ref: str,
    *,
    healthy: bool,
) -> None:
    """Record the rollback attempt through the canonical emitter (best-effort)."""
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            "DeploymentCoreContainerRolledBack",
            event_kind="lifecycle",
            event_type="deployment_run",
            source_type="system",
            severity="WARN",
            project=env.project,
            outcome="completed" if healthy else "failed",
            environment=env.env_name,
            context={
                "rolled_back_to": prior_image_ref,
                "failed_image_ref": failed_image_ref,
                "origin_host": env.origin_host,
                "rollback_healthy": healthy,
            },
        )
    except Exception as exc:  # pragma: no cover - telemetry is best-effort
        print(
            f"  [core-deploy] warning: rollback event emission failed: {exc}",
            file=sys.stderr,
        )


__all__ = [
    "attempt_rollback",
    "capture_running_image_ref",
]
