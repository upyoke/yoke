"""Item QA subjects that name their deployment run.

``--item PREFIX-N --stage S --deployment-run-id RUN`` lets the item's holder
pick the run when several could answer. The server validates the choice; an
older server may ignore the argument, so the receipt must name that run.
"""

from __future__ import annotations

from typing import Any

from typing import Callable
from yoke_contracts.api.function_call import FunctionError
from yoke_contracts.qa_item_run_selection_receipt import selected_run_mismatch


def subject_refusal(parsed: Any) -> str:
    """Name the subject rule a flag combination breaks, or return ''."""
    if not (parsed.item or parsed.deployment_run_id):
        return "one of --item or --deployment-run-id is required"
    if parsed.item and parsed.deployment_run_id and not parsed.stage:
        return "--item with --deployment-run-id requires --stage"
    return ""


def dispatch_subject(
    dispatch_and_emit: Callable[..., int],
    function_id: str,
    parsed: Any,
    target: Any,
    payload: dict,
) -> int:
    """Send the item's named run and refuse a receipt that answered another."""
    requested = parsed.deployment_run_id if parsed.item else None
    if not requested:
        return dispatch_and_emit(
            function_id=function_id,
            target=target,
            payload=payload,
            session_id=parsed.session_id,
            json_mode=parsed.json_mode,
        )
    def verify_receipt(response, _actor):
        refusal = response.success and selected_run_mismatch(
            function_id, requested, response.result
        )
        if not refusal:
            return response
        return response.model_copy(
            update={
                "success": False,
                "error": FunctionError(
                    code="function_argument_version_skew", message=refusal
                ),
            }
        )

    return dispatch_and_emit(
        function_id=function_id,
        target=target,
        payload={**payload, "deployment_run_id": requested},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        response_recovery=verify_receipt,
    )


__all__ = ["dispatch_subject", "subject_refusal"]
