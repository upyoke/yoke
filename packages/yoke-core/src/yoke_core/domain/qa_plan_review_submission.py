"""Validate and persist one complete agent-verdict batch."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.qa_capture_settlement import stamp_reviewed_capture
from yoke_core.domain.qa_constants import (
    UNDETERMINED_VERDICT,
    case_outcome_for_verdict,
)
from yoke_core.domain.qa_plan_execution_result_state import aggregate_state
from yoke_core.domain.qa_plan_execution_store import canonical, marker
from yoke_core.domain.qa_plan_review import QaPlanReviewError, _public_bundle
from yoke_core.domain.qa_undetermined_evidence import (
    require_agent_undetermined_evidence,
)


def _validated_verdicts(
    cases: Sequence[Mapping[str, Any]],
    raw: Sequence[Mapping[str, Any]],
) -> dict[int, tuple[str, str]]:
    expected = {int(case["requirement_id"]) for case in cases}
    result: dict[int, tuple[str, str]] = {}
    for row in raw:
        requirement_id = int(row.get("requirement_id") or 0)
        verdict = str(row.get("verdict") or "")
        rationale = str(row.get("rationale") or "").strip()
        if (
            requirement_id not in expected
            or requirement_id in result
            or verdict not in {"pass", "fail", UNDETERMINED_VERDICT}
            or not rationale
            or len(rationale) > 8000
        ):
            raise QaPlanReviewError("agent review verdict batch is invalid")
        result[requirement_id] = (verdict, rationale)
    if set(result) != expected:
        raise QaPlanReviewError(
            "agent review must submit exactly one verdict for every bundle case"
        )
    return result


def _reviewed_execution_state(
    recorded_results: Sequence[Mapping[str, Any]],
    reviewed_verdicts: Mapping[int, tuple[str, str]],
) -> str:
    """Fold reviewer verdicts into every durable execution result."""
    state = "passed"
    seen_reviewed: set[int] = set()
    for row in recorded_results:
        requirement_id = int(row.get("requirement_id") or 0)
        raw_result = row.get("result")
        if requirement_id < 1 or not isinstance(raw_result, Mapping):
            raise QaPlanReviewError(
                "QA execution contains an invalid durable case result"
            )
        result = dict(raw_result)
        if requirement_id in reviewed_verdicts:
            verdict = reviewed_verdicts[requirement_id][0]
            result["verdict"] = verdict
            result["case_outcome"] = case_outcome_for_verdict(verdict)
            seen_reviewed.add(requirement_id)
        state = aggregate_state(state, result)
    if seen_reviewed != set(reviewed_verdicts):
        raise QaPlanReviewError(
            "agent review cases do not match durable execution results"
        )
    return state


def _record_verdict(
    conn: Any,
    *,
    bundle_id: str,
    case: Mapping[str, Any],
    verdict: str,
    rationale: str,
    created_at: str,
) -> int:
    p = marker(conn)
    require_agent_undetermined_evidence(
        conn, performed_by="agent",
        verdict=verdict,
        run_ids=(int(case["capture_run_id"]),),
    )
    raw_result = canonical(
        {
            "review_bundle_id": bundle_id,
            "capture_run_id": int(case["capture_run_id"]),
            "rationale": rationale,
        }
    )
    run = conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,performed_by,qa_kind,verdict,verdict_reason,"
        "case_outcome,raw_result,started_at,completed_at,created_at"
        f") VALUES({', '.join([p] * 10)}) RETURNING id",
        (
            int(case["requirement_id"]),
            "agent",
            str(case["qa_kind"]),
            verdict,
            rationale,
            case_outcome_for_verdict(verdict),
            raw_result,
            created_at,
            created_at,
            created_at,
        ),
    ).fetchone()
    run_id = int(run[0])
    conn.execute(
        "INSERT INTO qa_plan_review_verdicts("
        "bundle_id,requirement_id,capture_run_id,review_run_id,verdict,"
        f"rationale,created_at) VALUES({', '.join([p] * 7)})",
        (
            bundle_id,
            int(case["requirement_id"]),
            int(case["capture_run_id"]),
            run_id,
            verdict,
            rationale,
            created_at,
        ),
    )
    stamp_reviewed_capture(
        conn,
        case,
        verdict=verdict,
        rationale=rationale,
        created_at=created_at,
    )
    from yoke_core.domain.item_activity import touch_for_qa_requirement

    touch_for_qa_requirement(conn, int(case["requirement_id"]))
    return run_id


def _ensure_requests(
    conn: Any,
    *,
    bundle_id: str,
    verdicts: Mapping[int, tuple[str, str]],
    run_ids: Mapping[int, int],
    reviewer_actor_id: str | None,
    reviewer_session_id: str,
) -> dict[int, int]:
    p = marker(conn)
    requests: dict[int, int] = {}
    for requirement_id, (verdict, rationale) in verdicts.items():
        if verdict != UNDETERMINED_VERDICT:
            continue
        from yoke_core.domain.qa_review_requests import ensure_qa_review_request

        request, _created = ensure_qa_review_request(
            conn,
            requirement_id=requirement_id,
            run_id=run_ids[requirement_id],
            originator_actor_id=(
                int(reviewer_actor_id)
                if reviewer_actor_id and str(reviewer_actor_id).isdigit()
                else None
            ),
            session_id=reviewer_session_id,
            commit=False,
        )
        if request is None:
            continue
        request_id = int(request["id"])
        requests[requirement_id] = request_id
        conn.execute(
            "UPDATE qa_plan_review_verdicts SET decision_request_id="
            f"{p} WHERE bundle_id={p} AND requirement_id={p}",
            (request_id, bundle_id, requirement_id),
        )
    return requests


def _emit_review_events(
    conn: Any,
    *,
    bundle: Mapping[str, Any],
    verdicts: Mapping[int, tuple[str, str]],
    run_ids: Mapping[int, int],
) -> None:
    from yoke_core.domain import qa_events

    cases = {int(case["requirement_id"]): case for case in bundle["cases"]}
    for requirement_id, (verdict, rationale) in verdicts.items():
        qa_events.emit_qa_run_event(
            conn,
            db_path=None,
            event_name="QARunCompleted",
            run_id=run_ids[requirement_id],
            requirement_id=requirement_id,
            qa_kind=str(cases[requirement_id]["qa_kind"]),
            verdict=verdict,
            verdict_reason=rationale,
        )
    conn.commit()


def submit_plan_review(
    conn: Any,
    execution: dict[str, Any],
    *,
    bundle_id: str,
    bundle_digest: str,
    verdicts: Sequence[Mapping[str, Any]],
    reviewer_actor_id: str | None,
    reviewer_session_id: str,
) -> dict[str, Any]:
    """Atomically persist every agent verdict, then create only needed Inbox work."""
    p = marker(conn)
    from yoke_core.domain import db_backend

    execution_before = {
        key: execution.get(key)
        for key in ("state", "machine_lease_id", "completed_at", "release_reason")
    }
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    try:
        stored = query_one(
            conn,
            f"SELECT * FROM qa_plan_review_bundles "
            f"WHERE id={p} AND execution_id={p}{lock}",
            (bundle_id, str(execution["id"])),
        )
        if stored is None or str(stored["bundle_digest"]) != bundle_digest:
            raise QaPlanReviewError("agent review bundle identity does not match")
        bundle = _public_bundle(stored)
        validated = _validated_verdicts(bundle["cases"], verdicts)
        existing = {
            int(row["requirement_id"]): row
            for row in query_rows(
                conn,
                f"SELECT * FROM qa_plan_review_verdicts WHERE bundle_id={p}",
                (bundle_id,),
            )
        }
        now = iso8601_now()
        run_ids: dict[int, int] = {}
        created_run_ids: dict[int, int] = {}
        for case in bundle["cases"]:
            requirement_id = int(case["requirement_id"])
            verdict, rationale = validated[requirement_id]
            prior = existing.get(requirement_id)
            if prior is not None:
                if prior["verdict"] != verdict or prior["rationale"] != rationale:
                    raise QaPlanReviewError("agent review replay changed a verdict")
                run_ids[requirement_id] = int(prior["review_run_id"])
                stamp_reviewed_capture(
                    conn,
                    case,
                    verdict=verdict,
                    rationale=rationale,
                    created_at=now,
                )
            else:
                run_id = _record_verdict(
                    conn,
                    bundle_id=bundle_id,
                    case=case,
                    verdict=verdict,
                    rationale=rationale,
                    created_at=now,
                )
                run_ids[requirement_id] = run_id
                created_run_ids[requirement_id] = run_id
        completed_replay = str(stored["state"]) == "completed"
        if not completed_replay:
            conn.execute(
                "UPDATE qa_plan_review_bundles "
                "SET state='completed',reviewer_actor_id="
                f"{p},reviewer_session_id={p},reviewed_at={p} "
                f"WHERE id={p} AND state='pending'",
                (reviewer_actor_id, reviewer_session_id, now, bundle_id),
            )
            if execution["state"] != "completed":
                from yoke_core.domain.qa_plan_execution_lifecycle import (
                    finish_plan_execution,
                )

                finish_plan_execution(
                    conn,
                    execution,
                    state="completed",
                    reason="qa-plan-agent-review-complete",
                    commit=False,
                )
        elif created_run_ids:
            raise QaPlanReviewError(
                "completed agent review is missing durable verdict rows"
            )
        requests = _ensure_requests(
            conn,
            bundle_id=bundle_id,
            verdicts=validated,
            run_ids=run_ids,
            reviewer_actor_id=reviewer_actor_id,
            reviewer_session_id=reviewer_session_id,
        )
        from yoke_core.domain.qa_plan_execution_store import result_rows

        settled_state = _reviewed_execution_state(
            result_rows(conn, str(execution["id"])),
            validated,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        execution.update(execution_before)
        raise
    if created_run_ids:
        try:
            _emit_review_events(
                conn,
                bundle=bundle,
                verdicts={
                    requirement_id: validated[requirement_id]
                    for requirement_id in created_run_ids
                },
                run_ids=created_run_ids,
            )
        except Exception:
            conn.rollback()
    return {
        "execution_id": str(execution["id"]),
        "bundle_id": bundle_id,
        "state": settled_state,
        "submission": "persisted",
        "verdicts": [
            {
                "requirement_id": requirement_id,
                "verdict": verdict,
                "rationale": rationale,
                "review_run_id": run_ids[requirement_id],
                "decision_request_id": requests.get(requirement_id),
            }
            for requirement_id, (verdict, rationale) in sorted(validated.items())
        ],
    }


__all__ = ["submit_plan_review"]
