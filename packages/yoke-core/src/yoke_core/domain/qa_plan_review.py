"""Immutable batched review bundles and agent-verdict persistence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping
from uuid import uuid4

from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.dispatch_descriptors import DispatchDescriptor
from yoke_core.domain.qa_plan_execution_store import (
    canonical,
    marker,
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
        "AND performed_by IN ('browser_substrate','host_control') "
        "AND completed_at IS NOT NULL",
        (int(capture_run_id), int(requirement_id)),
    )


def _artifacts(conn: Any, run_id: int) -> list[dict[str, Any]]:
    p = marker(conn)
    return [
        {
            "id": int(row["id"]),
            "artifact_type": str(row["artifact_type"]),
            "content_type": row["content_type"],
            "artifact_handle": row["artifact_handle"],
            "metadata": _json_object(row["metadata"]),
        }
        for row in query_rows(
            conn,
            "SELECT id,artifact_type,content_type,artifact_handle,metadata "
            f"FROM qa_artifacts WHERE qa_run_id={p} ORDER BY id",
            (int(run_id),),
        )
    ]


def _review_case(
    conn: Any,
    case: Mapping[str, Any],
    capture_run_id: int,
) -> dict[str, Any] | None:
    requirement_id = int(case["requirement_id"])
    capture = _capture_run(conn, requirement_id, capture_run_id)
    if capture is None:
        raise QaPlanReviewError(
            f"agent-verdict case {requirement_id} has no matching completed "
            f"capture run {capture_run_id}"
        )
    if capture["verdict"] in {"fail", "error"} or capture["case_outcome"] in {
        "failed",
        "blocked_on_precondition",
    }:
        return None
    if capture["verdict"] not in {None, "inconclusive"}:
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
        "plan_id": int(case["plan_id"]),
        "case_key": str(case["case_key"]),
        "case_position": int(case["case_position"]),
        "baseline_position": int(case["baseline_position"]),
        "host_baseline": case.get("host_baseline"),
        "method_id": str(case["method_id"]),
        "instructions": str(case.get("instructions") or ""),
        "expected_outcome": str(case.get("expected_outcome") or ""),
        "capture_run_id": int(capture["id"]),
        "capture_runner": str(capture["performed_by"]),
        "capture_degraded_reason": capture["capture_degraded_reason"],
        "transcript": _json_object(capture["raw_result"]),
        "artifacts": _artifacts(conn, int(capture["id"])),
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


def _dispatch_contract(bundle: Mapping[str, Any]) -> dict[str, Any]:
    descriptor = DispatchDescriptor("tester")
    bundle_id = str(bundle["bundle_id"])
    digest = str(bundle["bundle_digest"])
    cases = bundle["cases"]
    subject = bundle["subject"]
    execution_target = bundle.get("execution_target")
    execution_target_digest = str(bundle.get("execution_target_digest") or "")
    environment = (
        execution_target.get("environment")
        if isinstance(execution_target, Mapping)
        else None
    )
    authority_bound = (
        isinstance(environment, Mapping)
        and bool(str(environment.get("name") or "").strip())
        and bool(execution_target_digest)
    )
    authority = {
        "state": "bound" if authority_bound else "unavailable",
        "environment": (
            str(environment.get("name") or "") if authority_bound else None
        ),
        "execution_target_digest": (
            execution_target_digest if authority_bound else None
        ),
    }
    subject_flag = (
        f"--item-id {int(subject['item_id'])}"
        if subject.get("item_id") is not None
        else f"--deployment-run-id {subject['deployment_run_id']}"
    )
    artifact_read_commands = [
        "yoke qa artifact read "
        f"--requirement-id {int(case['requirement_id'])} "
        f"--artifact-id {int(artifact['id'])}"
        for case in cases
        for artifact in case.get("artifacts", [])
    ]
    if authority_bound:
        prompt = (
            f"Review QA bundle {bundle_id} ({digest}) for immutable target "
            f"environment {authority['environment']} at target digest "
            f"{execution_target_digest}. Inspect every supplied transcript "
            "and visual artifact against that case's instructions and "
            "expected outcome. Return exactly one independent verdict and "
            f"rationale for each of the {len(cases)} cases. Do not infer a "
            "verdict from capture status. Use only the supplied artifact-read "
            "commands for bytes that are not directly available "
            "(add --output PATH to land bytes on disk; prefer the result "
            "path key — artifact_handle.path may be a dead /tmp location), "
            "and refuse a missing or different target authority."
        )
        submit_command = (
            f"yoke qa plan review-submit {subject_flag} "
            f"--execution-id {bundle['execution_id']} --bundle-id {bundle_id} "
            f"--bundle-digest {digest} --stdin"
        )
    else:
        prompt = (
            f"QA bundle {bundle_id} ({digest}) predates immutable review "
            "authority binding and cannot be dispatched. Preserve it as "
            "historical evidence; do not query artifacts or submit verdicts."
        )
        submit_command = None
    return {
        "dispatch_kind": descriptor.dispatch_kind,
        "role": descriptor.role,
        "subagent_type": descriptor.subagent_type,
        "authority": authority,
        "artifact_read_commands": artifact_read_commands,
        "result_schema": {
            "verdicts": [
                {
                    "requirement_id": "integer",
                    "verdict": "pass|fail|inconclusive",
                    "rationale": "non-empty string",
                }
            ]
        },
        "prompt": prompt,
        "submit_command": submit_command,
    }


def _public_bundle(stored: Mapping[str, Any]) -> dict[str, Any]:
    payload = _json_object(stored["bundle_json"])
    result = {
        **payload,
        "bundle_id": str(stored["id"]),
        "bundle_digest": str(stored["bundle_digest"]),
        "state": str(stored["state"]),
    }
    result["dispatch"] = _dispatch_contract(result)
    return result


def begin_plan_review(
    conn: Any,
    execution: dict[str, Any],
) -> dict[str, Any] | None:
    """Persist one review bundle after every deterministic case has captured."""
    if int(execution["cursor_ordinal"]) != len(execution["roster"]):
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
        return _public_bundle(existing)
    from yoke_core.domain.qa_plan_execution_store import result_rows

    recorded = {
        int(row["requirement_id"]): row["result"]
        for row in result_rows(conn, str(execution["id"]))
    }
    if len(recorded) != len(execution["roster"]):
        raise QaPlanReviewError(
            "agent review requires one recorded result for every execution case"
        )
    cases = [
        review
        for case in execution["roster"]
        if str(case.get("verdict_path") or "") == "agent"
        and (
            review := _review_case(
                conn,
                case,
                _execution_capture_run_id(
                    case,
                    recorded.get(int(case["requirement_id"]), {}),
                ),
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
            "item_id": execution.get("item_id"),
            "deployment_run_id": execution.get("deployment_run_id"),
        },
        "cases": cases,
    }
    encoded = canonical(payload)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    bundle_id = str(uuid4())
    now = iso8601_now()
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
    return _public_bundle(stored)


__all__ = [
    "QaPlanReviewError",
    "begin_plan_review",
]
