"""Read-only recorded-survey + live conflict status for direct workflows.

Companion to :mod:`direct_workflow_execution`: that module RECORDS a
survey; this one only READS the recorded envelope and re-runs the
conflict check without persisting anything. It exists so worktree
preparation can validate an item's recorded survey over any connection
mode -- in-process against local Postgres, or relayed to the control
plane over https -- instead of opening a local ``connect()`` the https
transport refuses.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.conflict_survey import (
    ConflictSurveyRecordState,
    DURABLE_RECORDED,
)
from yoke_core.domain.conflict_survey import (
    read_recorded_survey_state,
    survey_conflicts,
)


class ConflictSurveyStatusRequest(BaseModel):
    pass


class ConflictSurveyStatusResponse(BaseModel):
    item_id: int
    workflow_id: str
    durable_state: ConflictSurveyRecordState
    found: bool
    clear: bool
    touch_paths: List[str]
    integration_target: str
    fingerprint: str
    observed_at: str
    blockers: List[dict[str, Any]]
    no_changes: bool


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
            "invalid_target", "target must carry kind='item' and item_id",
        )
    return int(request.target.item_id), None


def handle_conflict_survey_status(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the recorded survey and a fresh conflict re-check.

    READ-ONLY: reads the persisted survey envelope and re-runs
    :func:`survey_conflicts`; it never records or mutates state.

    ALL-MODES note: ``survey_conflicts`` supplements its authoritative
    signals with a git-diff over OTHER in-flight items' worktree paths
    (``conflict_survey._git_touched_paths``). Those worktrees only exist
    on the machine that created them, so on an https control-plane server
    the git subprocess finds no path, fails, and is caught -- yielding an
    empty supplement (confirmed: ``_git_touched_paths`` returns ``[]`` for
    a missing path and swallows ``OSError``/``SubprocessError`` and any
    non-zero git exit; it never raises). The AUTHORITATIVE conflict
    signals -- registered ``path_claims`` and File-Budget-declared paths
    from non-terminal items -- are pure DB reads and are identical in
    every connection mode, so the block decision this status feeds is
    stable across local and https. The worktree-git supplement is a
    machine-local best-effort enrichment, and its absence server-side is
    acceptable and intended.
    """
    item_id, invalid = _item_id(request)
    if invalid:
        return invalid
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        row = conn.execute(
            "SELECT workflow_id FROM items WHERE id = %s", (item_id,),
        ).fetchone()
        if row is None:
            return _error("unknown_item", f"item {item_id} does not exist")
        workflow_id = str(row[0])
        record = read_recorded_survey_state(conn, item_id)
        if record.state != DURABLE_RECORDED:
            return HandlerOutcome(
                result_payload=ConflictSurveyStatusResponse(
                    item_id=item_id,
                    workflow_id=workflow_id,
                    durable_state=record.state,
                    found=False,
                    clear=False,
                    touch_paths=[],
                    integration_target="main",
                    fingerprint="",
                    observed_at="",
                    blockers=[],
                    no_changes=False,
                ).model_dump(),
            )
        recorded = record.payload or {}
        integration_target = str(recorded.get("integration_target") or "main")
        try:
            survey = survey_conflicts(
                conn,
                item_id=item_id,
                touch_paths=recorded.get("touch_paths") or (),
                integration_target=integration_target,
                no_changes=recorded.get("no_changes") is True,
            )
        except (LookupError, ValueError) as exc:
            return _error("survey_refused", str(exc))
    return HandlerOutcome(
        result_payload=ConflictSurveyStatusResponse(
            item_id=item_id,
            workflow_id=workflow_id,
            durable_state=DURABLE_RECORDED,
            found=True,
            clear=survey.clear,
            touch_paths=list(survey.touch_paths),
            integration_target=survey.integration_target,
            fingerprint=survey.fingerprint,
            observed_at=survey.observed_at,
            no_changes=survey.no_changes,
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
        ).model_dump(),
    )


REGISTRATIONS: list[dict[str, Any]] = [
    {
        "function_id": "direct_workflow.conflict_survey.status",
        "handler": handle_conflict_survey_status,
        "request_model": ConflictSurveyStatusRequest,
        "response_model": ConflictSurveyStatusResponse,
        "stability": "stable",
        "owner_module": (
            "yoke_core.domain.handlers.direct_workflow_conflict_survey_status"
        ),
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": ["direct_workflow_only"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "ConflictSurveyStatusRequest",
    "ConflictSurveyStatusResponse",
    "REGISTRATIONS",
    "handle_conflict_survey_status",
]
