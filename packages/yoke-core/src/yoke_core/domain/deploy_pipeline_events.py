"""Best-effort event emission for deployment pipeline stages."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def emit_deployment_event(
    event_name: str,
    *,
    event_kind: str,
    event_type: str,
    source_type: str,
    severity: str,
    project: str,
    outcome: str,
    context: Dict[str, Any],
    item_id: Optional[str] = None,
    sd: Optional[str] = None,
) -> None:
    """Emit a deployment event through the native event contract."""
    del sd  # retained for callers that pass the pipeline's script directory
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            event_name,
            event_kind=event_kind,
            event_type=event_type,
            source_type=source_type,
            severity=severity,
            project=project,
            outcome=outcome,
            context=context,
            item_id=item_id,
        )
    except Exception:
        pass


def emit_run_event(
    name: str,
    outcome: str,
    context: Dict[str, Any],
    *,
    member_items: List[str],
    project: str = "yoke",
    sd: Optional[str] = None,
) -> None:
    """Emit stage events per item and one canonical addressed terminal event."""
    if name in {"DeploymentRunSucceeded", "DeploymentRunFailed"}:
        from yoke_core.domain.deploy_pipeline_completion import emit_completion

        emit_completion(
            str(context["run_id"]),
            name,
            outcome,
            context,
        )
        return
    targets = member_items if member_items else [""]
    for item_id in targets:
        emit_deployment_event(
            name,
            event_kind="lifecycle",
            event_type="deployment_run",
            source_type="system",
            severity="STATUS",
            project=project,
            outcome=outcome,
            context=context,
            item_id=item_id or None,
            sd=sd,
        )


__all__ = ["emit_deployment_event", "emit_run_event"]
