"""Immutable batched review bundles and agent-verdict persistence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping
from uuid import uuid4

from yoke_core.domain.db_helpers import instant_parameter, utc_now, query_one
from yoke_core.domain.qa_plan_review_dispatch import dispatch_contract
from yoke_core.domain.qa_review_evidence import (
    capture_artifacts,
)
from yoke_core.domain.qa_plan_execution_store import (
    canonical,
    marker,
)
from yoke_core.domain.qa_review_verdict_modes import (
    stage_review_verdicts,
)


class QaPlanReviewError(ValueError):
    """A review bundle or its verdict submission violates durable authority."""


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _capture_run(
    conn: Any,
    requirement_id: int,
    capture_run_id: int,
) -> dict[str, Any] | None:
    p = marker(conn)
    return query_one(
        conn,
        "SELECT id,performed_by,qa_kind,verdict,execution_status,"
        "case_outcome,capture_degraded_reason,raw_result,completed_at "
        "FROM qa_runs "
        f"WHERE id={p} AND qa_requirement_id={p} "
        "AND performed_by IN ('browser_substrate','host_control','agent_mission') "
        "AND completed_at IS NOT NULL",
        (int(capture_run_id), int(requirement_id)),
    )


def _review_case(
    conn: Any,
    case: Mapping[str, Any],
    capture_run_id: int,
    *,
    completed_only: bool = False,
) -> dict[str, Any] | None:
    requirement_id = int(case["requirement_id"])
    capture = _capture_run(conn, requirement_id, capture_run_id)
    if capture is None:
        if completed_only:
            return None
        raise QaPlanReviewError(
            f"agent-verdict case {requirement_id} has no matching completed "
            f"capture run {capture_run_id}"
        )
    if capture["verdict"] in {"fail", "error"} or capture["case_outcome"] in {
        "failed",
        "blocked_on_precondition",
    }:
        return None
    if capture["verdict"] not in {None, "undetermined"}:
        raise QaPlanReviewError(
            f"agent-verdict case {requirement_id} has an invalid capture verdict"
        )
    if (
        capture["case_outcome"] != "needs_review"
        and capture["execution_status"] != "captured"
    ):
        raise QaPlanReviewError(
            f"agent-verdict case {requirement_id} is not ready for review"
        )
    return {
        "requirement_id": requirement_id,
        "plan_id": (int(case["plan_id"]) if case.get("plan_id") is not None else None),
        "case_key": str(case["case_key"]),
        "case_position": int(case["case_position"]),
        "baseline_position": int(case["baseline_position"]),
        "host_baseline": case.get("host_baseline"),
        "method_id": str(case["method_id"]),
        "runner_id": str(case["runner_id"]),
        "method_config": dict(case.get("method_config") or {}),
        "executor": (case.get("method_config") or {}).get("executor"),
        "instructions": str(case.get("instructions") or ""),
        "expected_outcome": str(case.get("expected_outcome") or ""),
        "capture_run_id": int(capture["id"]),
        "capture_runner": str(capture["performed_by"]),
        "capture_degraded_reason": capture["capture_degraded_reason"],
        "transcript": _json_object(capture["raw_result"]),
        "artifacts": capture_artifacts(
            conn, requirement_id=requirement_id, run_id=int(capture["id"])
        ),
        "qa_kind": str(capture["qa_kind"]),
    }


def _execution_capture_run_id(
    case: Mapping[str, Any],
    result: Mapping[str, Any],
) -> int:
    runner_id = str(case.get("runner_id") or "")
    key = {
        "browser_substrate": "qa_run_id",
        "host_control": "run_id",
        "agent_mission": "run_id",
    }.get(runner_id)
    if key is None:
        raise QaPlanReviewError(
            f"agent-verdict case {case['requirement_id']} uses unsupported "
            f"capture runner {runner_id!r}"
        )
    try:
        run_id = int(result.get(key) or 0)
    except (TypeError, ValueError):
        run_id = 0
    if run_id < 1:
        raise QaPlanReviewError(
            f"agent-verdict case {case['requirement_id']} execution result "
            "does not identify its capture run"
        )
    return run_id


def _chain_blocked(
    roster: list[Mapping[str, Any]],
    recorded: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Cases never run because the case whose machine they inherit failed."""
    from yoke_core.domain.qa_plan_case_chain import INHERITED_PREDECESSOR_NOT_PASSED

    blocked = []
    for case in roster:
        result = recorded.get(int(case["requirement_id"])) or {}
        if result.get("error_code") == INHERITED_PREDECESSOR_NOT_PASSED:
            blocked.append(
                {
                    "requirement_id": int(case["requirement_id"]),
                    "case_key": str(case["case_key"]),
                    "error_code": INHERITED_PREDECESSOR_NOT_PASSED,
                    "reason": str(result.get("error") or ""),
                }
            )
    return blocked


def _public_bundle(conn: Any, stored: Mapping[str, Any]) -> dict[str, Any]:
    payload = _json_object(stored["bundle_json"])
    result = {
        **payload,
        "bundle_id": str(stored["id"]),
        "bundle_digest": str(stored["bundle_digest"]),
        "state": str(stored["state"]),
    }
    from yoke_core.domain.qa_plan_review_subject import public_review_subject

    subject = result.get("subject") or {}
    allowed_verdicts = stage_review_verdicts(
        conn, {**subject, "execution_target": result.get("execution_target")}
    )
    try:
        result["subject"] = public_review_subject(conn, subject)
    except ValueError as exc:
        raise QaPlanReviewError(str(exc)) from exc
    result["dispatch"] = dispatch_contract(
        result, allowed_verdicts=allowed_verdicts, conn=conn
    )
    return result


def begin_plan_review(
    conn: Any,
    execution: dict[str, Any],
    *,
    completed_captures_only: bool = False,
) -> dict[str, Any] | None:
    """Persist review authority for a full walk or a terminated walk's captures."""
    if not completed_captures_only and int(execution["cursor_ordinal"]) != len(
        execution["roster"]
    ):
        raise QaPlanReviewError(
            "agent review cannot begin before deterministic capture completes"
        )
    p = marker(conn)
    existing = query_one(
        conn,
        f"SELECT * FROM qa_plan_review_bundles WHERE execution_id={p}",
        (str(execution["id"]),),
    )
    if existing is not None:
        return _public_bundle(conn, existing)
    from yoke_core.domain.qa_plan_execution_store import result_rows

    recorded = {
        int(row["requirement_id"]): row["result"]
        for row in result_rows(conn, str(execution["id"]))
    }
    if not completed_captures_only and len(recorded) != len(execution["roster"]):
        raise QaPlanReviewError(
            "agent review requires one recorded result for every execution case"
        )
    cases = [
        review
        for case in execution["roster"]
        if str(case.get("verdict_path") or "") == "agent"
        and int(case["requirement_id"]) in recorded
        and (
            not completed_captures_only
            or (
                recorded[int(case["requirement_id"])].get("qa_run_id")
                or recorded[int(case["requirement_id"])].get("run_id")
            )
        )
        and (
            review := _review_case(
                conn,
                case,
                _execution_capture_run_id(
                    case,
                    recorded.get(int(case["requirement_id"]), {}),
                ),
                completed_only=completed_captures_only,
            )
        )
        is not None
    ]
    if not cases:
        return None
    payload = {
        "execution_id": str(execution["id"]),
        "roster_digest": str(execution["roster_digest"]),
        "execution_target": execution.get("execution_target"),
        "execution_target_digest": str(execution.get("execution_target_digest") or ""),
        "subject": {
            key: execution.get(key)
            for key in (
                "standalone_plan_id",
                "item_id",
                "deployment_run_id",
                "deployment_stage",
                "deployment_member_item_id",
            )
        },
        "cases": cases,
        "chain_blocked": _chain_blocked(execution["roster"], recorded),
    }
    encoded = canonical(payload)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    bundle_id = str(uuid4())
    now = instant_parameter(conn, utc_now())
    conn.execute(
        "INSERT INTO qa_plan_review_bundles("
        "id,execution_id,roster_digest,bundle_digest,bundle_json,state,created_at"
        f") VALUES({', '.join([p] * 7)})",
        (
            bundle_id,
            str(execution["id"]),
            str(execution["roster_digest"]),
            digest,
            encoded,
            "pending",
            now,
        ),
    )
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    if not completed_captures_only:
        finish_plan_execution(
            conn,
            execution,
            state="awaiting_agent_review",
            reason="qa-plan-awaiting-agent-review",
        )
    stored = query_one(
        conn,
        f"SELECT * FROM qa_plan_review_bundles WHERE id={p}",
        (bundle_id,),
    )
    assert stored is not None
    return _public_bundle(conn, stored)


__all__ = [
    "QaPlanReviewError",
    "begin_plan_review",
]
