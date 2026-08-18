"""Registered item-bound deployment-run composition."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome

from yoke_core.domain.handlers.deployment_common import error


def handle_deployment_run_start_for_item(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return error(
            "target_invalid",
            "deployment_runs.start_for_item requires target.kind='item'",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    for key in (
        "project", "flow", "environment", "release_lineage", "created_by",
    ):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            return error(
                "payload_invalid",
                f"{key} must be a string when present",
                jsonpath=f"$.payload.{key}",
            )
    created_by = str(
        payload.get("created_by")
        or request.actor.actor_id
        or request.actor.session_id
        or "operator"
    )
    from yoke_core.engines.runs_start_for_item import start_for_item

    result = start_for_item(
        int(request.target.item_id),
        project=(payload.get("project") or None),
        flow=(payload.get("flow") or None),
        environment=(payload.get("environment") or None),
        release_lineage=(payload.get("release_lineage") or None),
        created_by=created_by,
    )
    if not result.ok:
        suffix = f"; run_id={result.run_id}" if result.run_id else ""
        return error(
            result.error_code or "start_for_item_failed",
            f"{result.error_phase}: {result.error}{suffix}",
            jsonpath=None if result.error_code else "$.payload",
        )
    return HandlerOutcome(
        result_payload={
            "run_id": str(result.run_id),
            "item_id": int(request.target.item_id),
            "project": str(result.project),
            "flow": str(result.flow),
            "target_tier": str(result.target_tier or ""),
            "target_environment": str(result.target_environment_name or ""),
            "validation_message": result.validation_message,
        },
        primary_success=True,
    )


__all__ = ["handle_deployment_run_start_for_item"]
