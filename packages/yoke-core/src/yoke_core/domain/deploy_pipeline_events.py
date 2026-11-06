"""Best-effort event emission for deployment pipeline stages."""

from __future__ import annotations

from typing import Any, Dict, Optional


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
    item_ref: Optional[str] = None,
    sd: Optional[str] = None,
) -> None:
    """Emit a deployment event through the native event contract.

    ``item_ref`` is the member's public ref (PREFIX-N); it travels as
    ``public_ref`` and the dispatcher resolves the event's item key.
    """
    del sd  # retained for callers that pass the pipeline's script directory
    try:
        from yoke_contracts.api.function_call import TargetRef
        from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
        call_dispatcher = get_structured_dispatch().call_dispatcher

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
        if item_ref is not None:
            payload["public_ref"] = item_ref
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
    project: str = "",
    sd: Optional[str] = None,
) -> None:
    """Emit one run-level event; membership lives in ``deployment_run_items``."""
    emit_deployment_event(
        name,
        event_kind="lifecycle",
        event_type="deployment_run",
        source_type="system",
        severity="STATUS",
        project=project,
        outcome=outcome,
        context=context,
        sd=sd,
    )


__all__ = ["emit_deployment_event", "emit_run_event"]
