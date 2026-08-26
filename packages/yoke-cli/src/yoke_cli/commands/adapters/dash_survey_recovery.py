"""Recover a timed-out Dash survey from its durable status row."""

from __future__ import annotations

from typing import Any, Callable, Dict

from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallResponse,
    FunctionWarning,
    TargetRef,
)
from yoke_contracts.conflict_survey import (
    DURABLE_RECORDED,
    DURABLE_UNREADABLE,
)

_STATUS_FUNCTION = "direct_workflow.conflict_survey.status"
_TRANSPORT_FAILURE = "https_transport_failed"


def _warning(detail: str) -> FunctionWarning:
    return FunctionWarning(
        code="survey_timeout_recovery",
        step="durable_conflict_survey_status",
        detail=detail,
        recovery_function=_STATUS_FUNCTION,
    )


def _with_recovery_detail(
    response: FunctionCallResponse,
    detail: str,
) -> FunctionCallResponse:
    error = response.error
    if error is not None:
        error = error.model_copy(
            update={"message": f"{error.message}; {detail}"},
        )
    return response.model_copy(
        update={
            "error": error,
            "warnings": [*response.warnings, _warning(detail)],
        }
    )


def _recover_survey_timeout(
    response: FunctionCallResponse,
    actor: ActorContext,
    *,
    target: TargetRef,
    payload: Dict[str, Any],
) -> FunctionCallResponse:
    if (
        response.success
        or response.error is None
        or response.error.code != _TRANSPORT_FAILURE
    ):
        return response

    status = call_dispatcher(
        function_id=_STATUS_FUNCTION,
        target=target,
        payload={},
        actor=actor,
    )
    if not status.success:
        code = status.error.code if status.error is not None else "unknown"
        return _with_recovery_detail(
            response,
            f"durable survey status check failed ({code})",
        )

    durable = status.result or {}
    state = str(durable.get("durable_state") or DURABLE_UNREADABLE)
    expected_paths = [
        str(row.get("path") or "") for row in payload.get("path_sizes") or []
    ]
    durable_paths = [str(path) for path in durable.get("touch_paths") or []]
    target_matches = (
        durable_paths == expected_paths
        and bool(durable.get("no_changes")) == bool(payload.get("no_changes"))
        and str(durable.get("integration_target") or "main")
        == str(payload.get("integration_target") or "main")
    )
    if state != DURABLE_RECORDED or not durable.get("found") or not target_matches:
        mismatch = (
            " for a different touch set" if state == DURABLE_RECORDED else ""
        )
        return _with_recovery_detail(
            response,
            f"durable survey state is {state}{mismatch}",
        )

    result = {
        "item_id": durable.get("item_id"),
        "workflow_id": durable.get("workflow_id"),
        "clear": bool(durable.get("clear")),
        "fingerprint": str(durable.get("fingerprint") or ""),
        "blockers": list(durable.get("blockers") or []),
        "touch_paths": durable_paths,
        "integration_target": str(durable.get("integration_target") or "main"),
        "path_sizes": list(payload.get("path_sizes") or []),
        "no_changes": bool(durable.get("no_changes")),
        "recorded": True,
        "touch_path_update": "replace",
        "recovered_from_durable_state": True,
    }
    detail = "relay timed out after the matching survey was durably recorded"
    return response.model_copy(
        update={
            "success": True,
            "result": result,
            "error": None,
            "warnings": [*response.warnings, *status.warnings, _warning(detail)],
            "event_ids": list(
                dict.fromkeys(
                    [
                        *response.event_ids,
                        *status.event_ids,
                    ]
                )
            ),
        }
    )


def build_survey_timeout_recovery(
    target: TargetRef,
    payload: Dict[str, Any],
) -> Callable[[FunctionCallResponse, ActorContext], FunctionCallResponse]:
    """Bind one survey request to its read-after-timeout recovery."""
    return lambda response, actor: _recover_survey_timeout(
        response,
        actor,
        target=target,
        payload=payload,
    )


__all__ = ["build_survey_timeout_recovery"]
