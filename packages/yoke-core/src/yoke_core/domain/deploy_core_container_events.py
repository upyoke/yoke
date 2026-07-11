"""Lifecycle event emission for core-container deployments."""

from __future__ import annotations

import sys

from yoke_core.domain.deploy_environment_settings import DeployEnvironment


def emit_deploy_event(
    env: DeployEnvironment,
    image_ref: str,
    request_id: str,
) -> None:
    """Record a completed deployment without making telemetry a deploy gate."""
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            "DeploymentCoreContainerDeployed",
            event_kind="lifecycle",
            event_type="deployment_run",
            source_type="system",
            severity="STATUS",
            project=env.project,
            outcome="completed",
            environment=env.env_name,
            request_id=request_id,
            context={
                "image_ref": image_ref,
                "origin_host": env.origin_host,
                "log_group": env.log_group,
            },
        )
    except Exception as exc:  # pragma: no cover - telemetry is best-effort
        print(
            f"  [core-deploy] warning: deploy event emission failed: {exc}",
            file=sys.stderr,
        )
