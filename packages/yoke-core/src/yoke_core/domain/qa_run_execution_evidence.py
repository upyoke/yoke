"""Bind verdicts to their actual plan execution and its captured artifacts."""

from __future__ import annotations

import json
import sys
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_plan_execution_store import result_rows, select_plan_execution
from yoke_core.domain.schema_common import _table_exists


def _execution(
    conn: Any, requirement: dict[str, Any], run_id: int | None
) -> dict | None:
    """Prefer an exact captured attempt; aggregate obligations use the scoped walk."""
    rows = query_rows(
        conn,
        "SELECT e.id,r.result_json FROM qa_plan_executions e "
        "JOIN qa_plan_execution_results r ON r.execution_id=e.id "
        "WHERE r.requirement_id=%s ORDER BY e.created_at DESC,e.id DESC",
        (int(requirement["id"]),),
    )
    for row in rows:
        result = json.loads(row["result_json"])
        if run_id is not None and (
            result.get("qa_run_id") == run_id or result.get("run_id") == run_id
        ):
            return select_plan_execution(conn, str(row["id"]), lock=False)
    if requirement.get("deployment_run_id") and requirement.get("deployment_stage"):
        rows = query_rows(
            conn,
            "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
            "AND deployment_stage=%s AND COALESCE(deployment_member_item_id,0)=%s "
            "AND execution_target_digest=%s "
            "AND state IN ('active','waiting','walking','awaiting_walk_review','completed') "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (
                requirement["deployment_run_id"],
                requirement["deployment_stage"],
                requirement.get("deployment_member_item_id") or 0,
                requirement.get("execution_target_digest") or "",
            ),
        )
    elif requirement.get("standalone_execution_id"):
        return select_plan_execution(
            conn, requirement["standalone_execution_id"], lock=False
        )
    elif requirement.get("item_id"):
        rows = query_rows(
            conn,
            "SELECT id,roster_json FROM qa_plan_executions WHERE item_id=%s "
            "AND state IN ('active','waiting','walking','awaiting_walk_review','completed') "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (int(requirement["item_id"]),),
        )
        if not rows or not any(
            int(case["requirement_id"]) == int(requirement["id"])
            for case in json.loads(rows[0]["roster_json"])
        ):
            return None
    else:
        return None
    if not rows:
        return None
    execution = select_plan_execution(conn, str(rows[0]["id"]), lock=False)
    if not requirement.get("deployment_run_id") and not any(
        int(case["requirement_id"]) == int(requirement["id"])
        for case in execution["roster"]
    ):
        return None
    return execution


def execution_evidence_payload(
    conn: Any, run_id: int | None, *, run: dict[str, Any] | None = None
) -> str | None:
    """Compose execution and concrete artifact ids without changing other proof."""
    if not _table_exists(conn, "qa_plan_executions"):
        return
    if run is None:
        run = query_one(conn, "SELECT * FROM qa_runs WHERE id=%s", (run_id,))
    if run is None:
        return
    requirement = query_one(
        conn, "SELECT * FROM qa_requirements WHERE id=%s", (run["qa_requirement_id"],)
    )
    execution = _execution(conn, requirement, run_id)
    if execution is None:
        return
    evidence_runs = (
        ({run_id} if run_id is not None else set())
        if requirement.get("method_id")
        else {
            int(value)
            for row in result_rows(conn, str(execution["id"]))
            if (value := row["result"].get("qa_run_id") or row["result"].get("run_id"))
        }
    )
    artifacts = []
    if evidence_runs:
        places = ",".join("%s" for _ in evidence_runs)
        artifacts = [
            int(row["id"])
            for row in query_rows(
                conn,
                f"SELECT id FROM qa_artifacts WHERE qa_run_id IN ({places}) ORDER BY id",
                tuple(sorted(evidence_runs)),
            )
        ]
    raw = run.get("raw_result")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        parsed = None
    payload = (
        dict(parsed) if isinstance(parsed, dict) else ({"evidence": raw} if raw else {})
    )
    payload.update(execution_id=str(execution["id"]), evidence_artifact_ids=artifacts)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class VerdictSettlementRefused(ValueError):
    """The active deployment stage could not settle a just-written verdict."""

    code = "qa_verdict_settlement_refused"


def commit_settled_verdict(conn: Any, run_id: int) -> None:
    """Commit a pending run write together with its active stage's settlement.

    Settlement commits the verdict once the stage reaches a final outcome, so
    a failure after that point leaves the verdict durable; the refusal reads
    back which side of that commit it reached.
    """
    try:
        _settle_recorded_verdict(conn, run_id)
    except ValueError as exc:
        conn.rollback()
        recorded = query_one(
            conn,
            "SELECT r.verdict,q.deployment_run_id FROM qa_runs r "
            "JOIN qa_requirements q ON q.id=r.qa_requirement_id WHERE r.id=%s",
            (run_id,),
        )
        state = (
            "The verdict is recorded; re-drive its deployment run with "
            f"`yoke --env CONTROL-PLANE watch deploy -- {recorded['deployment_run_id']}` so the "
            "runner adopts it."
            if recorded and recorded["verdict"] is not None
            else "The verdict was not recorded; repair the named cause, then "
            "record the same verdict again."
        )
        raise VerdictSettlementRefused(
            f"{VerdictSettlementRefused.code}: QA run {run_id}'s deployment "
            f"stage could not settle: {exc}. {state}"
        ) from exc
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    from yoke_core.domain.deployment_member_close_out_retry import (
        after_verdict_recorded,
    )

    after_verdict_recorded(conn, run_id)


def commit_settled_verdict_or_exit(conn: Any, run_id: int) -> None:
    """Exit the CLI writer with the named refusal when settlement fails."""
    try:
        commit_settled_verdict(conn, run_id)
    except VerdictSettlementRefused as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _settle_recorded_verdict(conn: Any, run_id: int) -> None:
    """Re-evaluate the active stage a verdict belongs to, if one is executing."""
    subject = query_one(
        conn,
        "SELECT q.* "
        "FROM qa_runs r JOIN qa_requirements q ON q.id=r.qa_requirement_id "
        "WHERE r.id=%s AND r.verdict IS NOT NULL",
        (run_id,),
    )
    if subject is not None and all(
        subject.get(key)
        for key in ("deployment_run_id", "deployment_stage", "execution_target_digest")
    ):
        run = query_one(
            conn,
            "SELECT status,current_stage FROM deployment_runs WHERE id=%s",
            (subject["deployment_run_id"],),
        )
        if (
            run is None
            or run["status"] != "executing"
            or run["current_stage"] != subject["deployment_stage"]
        ):
            return
        from yoke_core.domain.deployment_qa_shared_plans import (
            requirement_subject,
            shared_target_identity,
        )

        if shared_target_identity(subject.get("execution_target_json")):
            from yoke_core.domain.deployment_qa_stage_settlement import (
                settle_plan_group,
            )

            settle_plan_group(conn, requirement_subject(conn, int(subject["id"])))
            return
        from yoke_core.domain.deployment_qa_stage_settlement import settle_subject

        settle_subject(
            conn,
            run_id=str(subject["deployment_run_id"]),
            stage=str(subject["deployment_stage"]),
            member=subject["deployment_member_item_id"],
        )
