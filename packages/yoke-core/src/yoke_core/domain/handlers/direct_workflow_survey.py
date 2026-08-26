"""Survey request handling for Dash and Blitz direct workflows."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

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


class SurveyPathSize(BaseModel):
    path: str
    current_line_count: int = Field(..., ge=0)
    remaining_headroom: int
    at_or_over_limit: bool
    limit: int = Field(..., gt=0)
    classification: str


class SurveyRequest(BaseModel):
    paths: List[str] = Field(default_factory=list)
    integration_target: str = "main"
    path_sizes: List[SurveyPathSize] = Field(default_factory=list)
    no_changes: bool = False


class SurveyResponse(BaseModel):
    item_id: int
    workflow_id: str
    clear: bool
    fingerprint: str
    blockers: List[dict[str, Any]]
    touch_paths: List[str]
    integration_target: str
    path_sizes: List[dict[str, Any]]
    no_changes: bool
    recorded: bool
    touch_path_update: Literal["replace"] = "replace"
    recovered_from_durable_state: bool = False


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
        if payload.no_changes and expected_workflow != "dash":
            return _error(
                "invalid_payload",
                "no_changes is available only for Dash conflict surveys",
            )
        if payload.no_changes == bool(payload.paths):
            return _error(
                "invalid_payload",
                "provide intended paths or no_changes=true, but not both",
            )
        if expected_workflow == "dash":
            sized_paths = [row.path for row in payload.path_sizes]
            if sized_paths != [path.removeprefix("./") for path in payload.paths]:
                return _error(
                    "survey_sizing_required",
                    "Dash survey requires one ordered path-size result per path",
                )
            if any(
                row.remaining_headroom != row.limit - row.current_line_count
                or row.at_or_over_limit != (
                    row.current_line_count >= row.limit
                )
                for row in payload.path_sizes
            ):
                return _error(
                    "survey_sizing_invalid",
                    "Dash survey path-size headroom or limit flag is inconsistent",
                )
        reservation = reserve_conflict_survey_record(conn, item_id=item_id)
        try:
            survey = survey_conflicts(
                conn,
                item_id=item_id,
                touch_paths=payload.paths,
                integration_target=payload.integration_target,
                no_changes=payload.no_changes,
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
            integration_target=survey.integration_target,
            path_sizes=[row.model_dump() for row in payload.path_sizes],
            no_changes=survey.no_changes,
            recorded=recorded,
        ).model_dump(),
    )


__all__ = ["SurveyRequest", "SurveyResponse", "handle_survey"]
