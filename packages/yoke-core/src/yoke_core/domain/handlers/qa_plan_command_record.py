"""Record a declared-host Command through its owning execution and cursor."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field
from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_contracts.qa_case_starting_state import is_host_command
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.handlers.qa_plan_execution_models import PlanExecutionStateRequest


class PlanCommandRecordRequest(PlanExecutionStateRequest):
    ordinal: int = Field(ge=0)
    requirement_id: int = Field(ge=1)
    raw_result: str
    duration_ms: int = Field(ge=0)
    run_id: int | None = Field(default=None, ge=1)
    verdict: Literal["pass", "fail", "error"] | None = None


class PlanCommandRecordResponse(BaseModel):
    qa_run_id: int
    requirement_id: int


def handle_plan_command_record(request) -> HandlerOutcome:
    from yoke_core.domain.handlers.qa_plan_execution_ownership import _owned_execution
    from yoke_core.domain.qa_plan_execution_roster import expected_plan_case
    from yoke_core.domain.qa_plan_execution_reentry import admitted_case

    parsed = PlanCommandRecordRequest.model_validate(request.payload)
    owned = _owned_execution(request, parsed)
    if isinstance(owned, HandlerOutcome):
        return owned
    conn, execution = owned
    try:
        case = expected_plan_case(
            execution, ordinal=parsed.ordinal, requirement_id=parsed.requirement_id,
        )
        if (
            not is_host_command(case) or case["verdict_path"] != "automatic"
            or admitted_case(execution) != parsed.ordinal
        ):
            raise ValueError(
                "qa_plan_command_not_admitted: begin the declared-host Command "
                "through the execution's current Test Machine lease"
            )
        run_id = _record(conn, execution, case, parsed)
        conn.commit()
        return HandlerOutcome(
            primary_success=True,
            result_payload={"qa_run_id": run_id, "requirement_id": parsed.requirement_id},
        )
    except ValueError as exc:
        conn.rollback()
        return HandlerOutcome(
            primary_success=False, error=FunctionError(
                code="qa_plan_command_record_refused", message=str(exc), jsonpath="$.payload",
            ),
        )
    finally:
        conn.close()


def _record(conn, execution, case, parsed) -> int:
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_constants import case_outcome_for_verdict
    from yoke_core.domain.qa_merging_identity import recorded_head_sha
    from yoke_core.domain.qa_plan_execution_store import canonical
    from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config
    from yoke_core.domain.qa_run_verdict_record import insert_qa_run, update_qa_run

    if (parsed.run_id is None) != (parsed.verdict is None):
        raise ValueError("Command settlement supplies both run_id and verdict; capture supplies neither.")
    raw = json.loads(parsed.raw_result)
    if not isinstance(raw, dict):
        raise ValueError("Command proof must be a JSON object.")
    frozen_sha = case.get("lane_commit_sha") or case.get("standalone_source_revision")
    if frozen_sha and recorded_head_sha(parsed.raw_result) != frozen_sha:
        raise ValueError(
            f"qa_lane_moved: command proof does not name frozen commit {frozen_sha}; "
            "restore the checkout at that SHA before running the partition"
        )
    execution_id = str(execution["id"])
    raw["plan_execution_id"] = execution_id
    encoded = stamp_executed_method_config(
        canonical(raw), case["method_config"],
        execution_target_digest=case["execution_target_digest"],
    )
    now = utc_now()
    if parsed.run_id is None:
        return insert_qa_run(
            conn,
            qa_requirement_id=parsed.requirement_id, performed_by="worktree_run",
            qa_kind=case["qa_kind"], raw_result=encoded, duration_ms=parsed.duration_ms,
            started_at=now, created_at=now,
        ).run_id
    row = query_one(
        conn, "SELECT raw_result,verdict FROM qa_runs WHERE id=%s AND qa_requirement_id=%s",
        (parsed.run_id, parsed.requirement_id),
    )
    prior = json.loads(row["raw_result"] or "{}") if row else {}
    if not isinstance(prior, dict) or prior.get("plan_execution_id") != execution_id:
        raise ValueError("qa_plan_command_run_mismatch: use the run id this execution opened.")
    if row["verdict"] is not None and row["verdict"] != parsed.verdict:
        raise ValueError("qa_plan_command_run_settled: inspect the verdict already recorded on this run.")
    update_qa_run(
        conn, parsed.run_id,
        {
            "verdict": parsed.verdict, "case_outcome": case_outcome_for_verdict(parsed.verdict),
            "raw_result": encoded, "duration_ms": parsed.duration_ms,
        },
        unjudged_only=True, default_completed_at=now,
    )
    return parsed.run_id
