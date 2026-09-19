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
    environment: Optional[str] = None,
    item_id: Optional[str] = None,
    sd: Optional[str] = None,
) -> None:
    """Emit a deployment event through the native event contract."""
    del sd  # retained for callers that pass the pipeline's script directory
    try:
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )
        payload = {
            "name": event_name,
            "kind": event_kind,
            "type": event_type,
            "source_type": source_type,
            "severity": severity,
            "project": project,
            "outcome": outcome,
            "context": context,
        }
        if item_id is not None:
            payload["item_id"] = item_id
        if environment is not None:
            payload["environment"] = environment
        call_dispatcher(
            function_id="events.emit",
            target=TargetRef(kind="global"),
            payload=payload,
        )
    except Exception:
        pass


def emit_run_event(
    name: str,
    outcome: str,
    context: Dict[str, Any],
    *,
    member_items: List[str],
    project: str = "",
    sd: Optional[str] = None,
) -> None:
    """Emit stage events per item and one canonical terminal run event."""
    targets = (
        [""] if name in {"DeploymentRunSucceeded", "DeploymentRunFailed"}
        else member_items or [""]
    )
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
