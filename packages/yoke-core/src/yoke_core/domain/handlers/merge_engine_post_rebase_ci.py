"""Claim-free recording of merge-gate CI verification evidence.

The merge engine holds a merge lock, not an item claim, so it cannot call
``qa.run.record_verdict`` (claim-gated on the QA subject). This handler is
the merge-internal twin: ensure a covering-eligible ``ci_run`` requirement
on the item, insert a ``qa_runs`` row whose ``raw_result`` carries
``verification_tree.head_sha``, and emit ``QARunCompleted``. Covering-run
readers already accept ``runner_id='ci_run'`` pass evidence, so a later
same-tree merge skips instead of re-dispatching.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.qa_command_plan_registration import declared_ci_workflow
from yoke_core.domain.qa_events import emit_qa_requirement_event
from yoke_core.domain.qa_command_plans import (
    list_registered_commands_for_project_id,
)
from yoke_core.domain.qa_method_config_validation import validate_method_config


class RecordPostRebaseCiRunRequest(BaseModel):
    scope: str
    command: str = ""
    workflow: str = ""
    verdict: str
    raw_result: str
    duration_ms: Optional[int] = None
    performed_by: str = "ci_run"


class RecordPostRebaseCiRunResponse(BaseModel):
    qa_run_id: int
    requirement_id: int
    verdict: str


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _loads_config(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ensure_merge_gate_ci_requirement(
    conn: Any,
    *,
    item_id: int,
    scope: str,
    command: str,
    workflow: str,
) -> int:
    """Find or create an item requirement covering CI merge-gate evidence."""
    marker = _marker(conn)
    item = query_one(
        conn,
        f"SELECT project_id FROM items WHERE id={marker}",
        (int(item_id),),
    )
    if item is None:
        raise LookupError(f"item {item_id} not found")
    project_id = int(item["project_id"])
    config = validate_method_config("command-ci", {
        "command": command or list_registered_commands_for_project_id(
            conn, project_id,
        ).get(scope, ""),
        "registered_scope": scope,
        "ci_workflow": workflow or declared_ci_workflow(conn, project_id),
    })
    rows = query_rows(
        conn,
        "SELECT id, method_config FROM qa_requirements "
        f"WHERE item_id={marker} AND runner_id='ci_run' "
        "AND waived_at IS NULL ORDER BY id ASC",
        (int(item_id),),
    )
    for row in rows:
        stored_config = _loads_config(row.get("method_config"))
        registered_scope = str(
            stored_config.get("registered_scope") or ""
        ).strip()
        if registered_scope and registered_scope != scope:
            continue
        try:
            validate_method_config("command-ci", stored_config)
        except ValueError:
            continue
        return int(row["id"])

    now = iso8601_now()
    cur = conn.execute(
        "INSERT INTO qa_requirements ("
        "item_id, qa_kind, qa_phase, blocking_mode, requirement_source, "
        "method_id, method_name, runner_id, instructions, expected_outcome, "
        "method_config, created_at"
        f") VALUES ({', '.join([marker] * 12)}) RETURNING id",
        (
            int(item_id),
            "plan_case",
            "verification",
            "blocking",
            "flow_derived",
            "command-ci",
            "Command (CI)",
            "ci_run",
            (
                "Merge-gate CI verification of the integrated candidate "
                f"tree ({scope})."
            ),
            "CI workflow concludes successfully for the candidate head.",
            json.dumps(config, sort_keys=True),
            now,
        ),
    )
    row = cur.fetchone()
    requirement_id = int(row["id"] if isinstance(row, dict) else row[0])
    # The merge gate commits this connection after the qa_runs insert below,
    # so the creation event rides the same transaction as the requirement.
    emit_qa_requirement_event(
        conn,
        db_path=None,
        event_name="QARequirementCreated",
        requirement_id=requirement_id,
        qa_kind="plan_case",
        qa_phase="verification",
        source="flow_derived",
        target_row={
            "item_id": int(item_id),
            "epic_id": None,
            "task_num": None,
            "deployment_run_id": None,
        },
        transactional=True,
    )
    return requirement_id


def handle_record_post_rebase_ci_run(request: FunctionCallRequest) -> HandlerOutcome:
    """Ensure a ci_run requirement and insert merge-gate CI evidence."""
    item_id = request.target.item_id
    if item_id is None:
        return _err(
            "target_invalid",
            "record_post_rebase_ci_run requires target.item_id",
        )
    try:
        body = RecordPostRebaseCiRunRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - structured payload error
        return _err("payload_invalid", f"post_rebase CI record payload invalid: {exc}")

    from yoke_core.domain import qa_events
    from yoke_core.domain.qa_constants import case_outcome_for_verdict

    if body.scope not in {"full", "quick"}:
        return _err(
            "payload_invalid",
            "scope must be 'full' or 'quick'",
        )
    automatic_verdicts = ("pass", "fail", "error")
    if body.verdict not in automatic_verdicts:
        return _err(
            "payload_invalid",
            f"automatic CI verdict must be one of {list(automatic_verdicts)}",
        )
    if not str(body.raw_result or "").strip():
        return _err("payload_invalid", "raw_result is required")

    try:
        with _connect_rw() as conn:
            requirement_id = _ensure_merge_gate_ci_requirement(
                conn,
                item_id=int(item_id),
                scope=body.scope,
                command=body.command,
                workflow=body.workflow,
            )
            req = query_one(
                conn,
                f"SELECT qa_kind FROM qa_requirements WHERE id={_marker(conn)}",
                (requirement_id,),
            )
            if req is None:
                raise LookupError(f"requirement {requirement_id} disappeared")
            qa_kind = str(req["qa_kind"])
            now = iso8601_now()
            marker = _marker(conn)
            cur = conn.execute(
                "INSERT INTO qa_runs ("
                "qa_requirement_id, performed_by, qa_kind, verdict, "
                "case_outcome, raw_result, duration_ms, started_at, "
                "completed_at, created_at"
                f") VALUES ({', '.join([marker] * 10)}) RETURNING id",
                (
                    requirement_id,
                    body.performed_by or "ci_run",
                    qa_kind,
                    body.verdict,
                    case_outcome_for_verdict(body.verdict),
                    body.raw_result,
                    body.duration_ms,
                    now,
                    now,
                    now,
                ),
            )
            run_row = cur.fetchone()
            run_id = int(run_row["id"] if isinstance(run_row, dict) else run_row[0])
            conn.commit()
            qa_events.emit_qa_run_event(
                conn,
                db_path=None,
                event_name="QARunCompleted",
                run_id=run_id,
                requirement_id=requirement_id,
                qa_kind=qa_kind,
                verdict=body.verdict,
            )
    except Exception as exc:  # noqa: BLE001 - merge must see a structured failure
        return _err("post_rebase_ci_record_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "qa_run_id": run_id,
            "requirement_id": requirement_id,
            "verdict": body.verdict,
        },
        primary_success=True,
    )


__all__ = [
    "RecordPostRebaseCiRunRequest",
    "RecordPostRebaseCiRunResponse",
    "handle_record_post_rebase_ci_run",
]
