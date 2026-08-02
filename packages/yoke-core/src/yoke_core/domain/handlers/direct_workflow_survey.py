"""Survey request handling for Dash and Blitz direct workflows."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.conflict_survey import (
    cancel_conflict_survey_reservation,
    record_conflict_survey,
    reserve_conflict_survey_record,
    survey_conflicts,
)


class SurveyRequest(BaseModel):
    paths: List[str] = Field(..., min_length=1)
    integration_target: str = "main"


class SurveyResponse(BaseModel):
    item_id: int
    workflow_id: str
    clear: bool
    fingerprint: str
    blockers: List[dict[str, Any]]
    touch_paths: List[str]
    recorded: bool


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _item_id(
    request: FunctionCallRequest,
) -> tuple[Optional[int], Optional[HandlerOutcome]]:
    if request.target.kind != "item" or request.target.item_id is None:
        return None, _error(
            "invalid_target",
            "target must carry kind='item' and item_id",
        )
    return int(request.target.item_id), None


def handle_survey(
    request: FunctionCallRequest,
    *,
    expected_workflow: str,
) -> HandlerOutcome:
    """Record one survey unless a newer request has superseded it."""
    item_id, invalid = _item_id(request)
    if invalid:
        return invalid
    try:
        payload = SurveyRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("invalid_payload", f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        row = conn.execute(
            "SELECT workflow_id FROM items WHERE id = %s",
            (item_id,),
        ).fetchone()
        if row is None:
            return _error("unknown_item", f"item {item_id} does not exist")
        workflow_id = str(row[0])
        if workflow_id != expected_workflow:
            return _error(
                "workflow_mismatch",
                f"item {item_id} uses workflow {workflow_id!r}, "
                f"not {expected_workflow!r}",
            )
        reservation = reserve_conflict_survey_record(conn, item_id=item_id)
        try:
            survey = survey_conflicts(
                conn,
                item_id=item_id,
                touch_paths=payload.paths,
                integration_target=payload.integration_target,
            )
            recorded = record_conflict_survey(
                conn,
                survey,
                reservation=reservation,
            )
        except (LookupError, ValueError) as exc:
            cancel_conflict_survey_reservation(
                conn,
                item_id=item_id,
                reservation=reservation,
            )
            return _error("survey_refused", str(exc))
    return HandlerOutcome(
        result_payload=SurveyResponse(
            item_id=item_id,
            workflow_id=expected_workflow,
            clear=survey.clear,
            fingerprint=survey.fingerprint,
            blockers=[
                {
                    "kind": blocker.kind,
                    "owner_item_id": blocker.owner_item_id,
                    "path": blocker.path,
                    "state": blocker.state,
                    "detail": blocker.detail,
                }
                for blocker in survey.blockers
            ],
            touch_paths=list(survey.touch_paths),
            recorded=recorded,
        ).model_dump(),
    )


__all__ = ["SurveyRequest", "SurveyResponse", "handle_survey"]
