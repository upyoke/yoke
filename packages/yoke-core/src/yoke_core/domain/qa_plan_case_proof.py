"""Environment and baseline proof reads for QA plan cases."""

from __future__ import annotations

from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_catalog_reads import _outcome
from yoke_core.domain.qa_execution_proof import (
    qa_evidence_run_id,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.sql_json import json_get


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decode(value: Any, fallback: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def _case_result(
    conn: Any,
    plan_id: int,
    case_key: str,
    host_baseline: str | None,
    deployment_run_id: str | None,
    target_env: str | None = None,
) -> dict:
    marker = _placeholder(conn)
    deployment_filter = ""
    params: tuple[Any, ...] = (plan_id, case_key, host_baseline or "")
    if deployment_run_id is not None:
        deployment_filter = f" AND q.deployment_run_id={marker}"
        params += (deployment_run_id,)
    if target_env is not None:
        deployment_filter += f" AND q.target_env={marker}"
        params += (target_env,)
    row = query_one(
        conn,
        "SELECT q.id AS requirement_id, q.host_baseline, "
        "q.deployment_run_id, q.standalone_execution_id, q.waived_at, "
        "r.id AS run_id, r.performed_by, r.verdict, r.verdict_reason, "
        "r.execution_status, "
        "r.case_outcome, r.raw_result, "
        "r.capture_degraded_reason, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at "
        "FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.id=("
        f"{latest_execution_id_sql('q.id')}"
        f") WHERE q.plan_id={marker} AND q.plan_case_key={marker} "
        f"AND COALESCE(q.host_baseline, '')={marker} "
        f"AND NOT {settled_obligation_sql(conn, 'q')} "
        f"{deployment_filter} "
        "ORDER BY happened_at DESC, q.id DESC LIMIT 1",
        params,
    )
    if row is None:
        return {
            "requirement_id": None,
            "run_id": None,
            "deployment_run_id": deployment_run_id,
            "host_baseline": host_baseline,
            "target_env": target_env,
            "outcome": "not_run",
            "output_tail": None,
            "evidence": [],
        }
    raw_result = _decode(row["raw_result"], {})
    review = _review_state(conn, int(row["requirement_id"]), row)
    evidence_run_id = qa_evidence_run_id(
        conn,
        requirement_id=int(row["requirement_id"]),
        run_id=int(row["run_id"]) if row["run_id"] is not None else None,
        performed_by=row["performed_by"],
        raw_result=row["raw_result"],
    )
    evidence = []
    if evidence_run_id is not None:
        evidence = [
            {
                "id": int(artifact["id"]),
                "artifact_type": str(artifact["artifact_type"]),
                "content_type": artifact["content_type"],
                "artifact_handle": artifact["artifact_handle"],
                "metadata": _decode(artifact["metadata"], {}),
            }
            for artifact in query_rows(
                conn,
                "SELECT id, artifact_type, content_type, artifact_handle, "
                f"metadata FROM qa_artifacts WHERE qa_run_id={marker} "
                "ORDER BY id",
                (int(evidence_run_id),),
            )
        ]
    return {
        "requirement_id": int(row["requirement_id"]),
        "run_id": int(row["run_id"]) if row["run_id"] is not None else None,
        "deployment_run_id": row["deployment_run_id"],
        "standalone_execution_id": row["standalone_execution_id"],
        "host_baseline": row["host_baseline"],
        "target_env": target_env,
        "outcome": _outcome(row),
        "capture_degraded_reason": row["capture_degraded_reason"],
        "happened_at": row["happened_at"],
        "output_tail": (
            raw_result.get("output_tail") if isinstance(raw_result, dict) else None
        ),
        "evidence": evidence,
        "review": review,
    }


def _review_state(
    conn: Any,
    requirement_id: int,
    run: Any,
) -> dict[str, Any]:
    performed_by = str(run["performed_by"] or "")
    raw = _decode(run["raw_result"], {})
    rationale = run["verdict_reason"]
    capture_run_id = raw.get("capture_run_id") if isinstance(raw, dict) else None
    agent_verdict = run["verdict"] if performed_by == "agent" else None
    agent_run_id = int(run["run_id"]) if performed_by == "agent" else None
    reviewed = None
    if run["run_id"] is not None and _table_exists(conn, "qa_plan_review_verdicts"):
        marker = _placeholder(conn)
        reviewed = query_one(
            conn,
            "SELECT capture_run_id,verdict,rationale FROM qa_plan_review_verdicts "
            f"WHERE requirement_id={marker} AND capture_run_id={marker}",
            (requirement_id, int(run["run_id"])),
        )
        if reviewed is not None:
            capture_run_id = int(reviewed["capture_run_id"])
            agent_run_id = capture_run_id
            agent_verdict = reviewed["verdict"]
            rationale = reviewed["rationale"]
    request = None
    if agent_run_id is not None and _table_exists(conn, "decision_requests"):
        marker = _placeholder(conn)
        request_row = query_one(
            conn,
            "SELECT id,status,subject_context,resolution_action,"
            "resolution_note,resolved_at "
            "FROM decision_requests "
            "WHERE kind='qa_needs_review' AND subject_type='qa_requirement' "
            f"AND subject_key={marker} "
            f"AND CAST({json_get('subject_context', '$.run_id')} AS TEXT)={marker} "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (str(requirement_id), str(agent_run_id)),
        )
        context = (
            _decode(request_row["subject_context"], {})
            if request_row is not None
            else {}
        )
        request_run_id = context.get("run_id")
        if (
            request_row is not None
            and agent_run_id is not None
            and str(request_run_id) == str(agent_run_id)
        ):
            request = {
                "id": int(request_row["id"]),
                "status": str(request_row["status"]),
                "resolution_action": request_row["resolution_action"],
                "resolution_note": request_row["resolution_note"],
                "resolved_at": request_row["resolved_at"],
            }
    if performed_by == "human_review" or (
        request is not None and request["status"] == "resolved"
    ):
        state = "human_review_resolved"
    elif agent_run_id is not None and agent_verdict == "undetermined":
        state = (
            "human_review_requested"
            if request is not None and request["status"] == "pending"
            else "agent_undetermined"
        )
    elif agent_run_id is not None:
        state = "agent_reviewed"
    elif run["case_outcome"] == "needs_review" or run["execution_status"] == "captured":
        state = "awaiting_agent_review"
    else:
        state = "not_applicable"
    return {
        "state": state,
        "capture_runner": (
            performed_by
            if performed_by in {"browser_substrate", "host_control"}
            else None
        ),
        "review_runner": (
            "human_review"
            if state == "human_review_resolved"
            else "agent"
            if agent_run_id is not None
            else None
        ),
        "agent_verdict": agent_verdict,
        "rationale": rationale,
        "capture_run_id": (int(capture_run_id) if capture_run_id is not None else None),
        "decision_request": request,
    }
