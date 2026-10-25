"""Live QA ownership remains unsettled independently of attempt history."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.qa_obligation_settlement import (
    effective_obligations,
    item_supersession_settled,
    requirement_retracted_at_select,
)
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_review_waits import requirement_awaits_human_review
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.work_claim_targets import TARGET_KIND_QA_ADMISSION


def answered_by_run_copy(
    conn: Any, item_id: int, requirement_id: int, sources: set[int]
) -> bool:
    """A post-deploy source whose accepted run copies already answer it.

    The item's own capture on that source owes no verdict once the completion
    run accepts the copies: the copies' acceptance is the source's settlement,
    which is the same reading the terminal verdict gate applies.
    """
    return int(requirement_id) in sources and source_obligation_consumed(
        conn, item_id=int(item_id), source_requirement_id=int(requirement_id)
    )


def live_qa_leases(conn: Any, item_id: int) -> list[tuple[int, str]]:
    """Find durable plan and submitted-case lease owners, including old attempts."""
    if not _table_exists(conn, "work_claims"):
        return []
    from yoke_core.domain.machine_qa_execution_protocol import (
        HOST_CONTROL_SUBMISSION_RECEIPT_KEY,
    )

    p = marker(conn)
    owners: dict[int, str] = {}
    if _table_exists(conn, "qa_plan_executions") and _column_exists(
        conn, "qa_plan_executions", "test_machine_lease_id"
    ):
        for row in query_rows(
            conn,
            "SELECT id,test_machine_lease_id FROM qa_plan_executions "
            f"WHERE item_id={p} OR deployment_member_item_id={p}",
            (item_id, item_id),
        ):
            execution = dict(row)
            if execution["test_machine_lease_id"] is not None:
                owners[int(execution["test_machine_lease_id"])] = (
                    f"plan {execution['id']}"
                )
            for claim in execution_host_leases(conn, execution):
                owners[claim.id] = f"plan {execution['id']}"
    if _table_exists(conn, "qa_runs") and _table_exists(conn, "qa_requirements"):
        for row in query_rows(
            conn,
            "SELECT r.id,r.raw_result FROM qa_runs r "
            "JOIN qa_requirements q ON q.id=r.qa_requirement_id "
            f"WHERE q.item_id={p} OR q.deployment_member_item_id={p}",
            (item_id, item_id),
        ):
            try:
                raw = row["raw_result"]
                payload = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                receipt = payload.get("evidence", {}).get(
                    HOST_CONTROL_SUBMISSION_RECEIPT_KEY, {}
                )
                lease_id = int(receipt.get("lease_id"))
                if receipt.get("contract_digest"):
                    owners[lease_id] = f"attempt {row['id']}"
            except (ValueError, TypeError, AttributeError):
                continue
    if not owners:
        return []
    rows = query_rows(
        conn,
        f"SELECT id FROM work_claims WHERE id IN ({','.join(p for _ in owners)}) "
        f"AND target_kind={p} AND released_at IS NULL ORDER BY id",
        (*owners, TARGET_KIND_QA_ADMISSION),
    )
    return [(int(row["id"]), owners[int(row["id"])]) for row in rows]


def _blocking_requirement_rows(conn: Any, item_id: int) -> list[dict[str, Any]]:
    placeholder = marker(conn)
    has_methods = _table_exists(conn, "qa_methods") and _column_exists(
        conn, "qa_methods", "runner_id"
    )
    has_runner = _column_exists(conn, "qa_requirements", "runner_id")
    runner = (
        "COALESCE(q.runner_id,m.runner_id) AS effective_runner_id"
        if has_methods and has_runner
        else ("q.runner_id AS effective_runner_id" if has_runner else ("m.runner_id AS effective_runner_id" if has_methods else "NULL AS effective_runner_id"))
    )
    join = "LEFT JOIN qa_methods m ON m.id=q.method_id" if has_methods else ""
    cursor = conn.execute(
        f"SELECT q.*, {runner}, "
        f"{requirement_retracted_at_select(conn, 'q')} "
        f"FROM qa_requirements q {join} "
        f"WHERE q.item_id={placeholder} ORDER BY q.id",
        (int(item_id),),
    )
    columns = [str(column[0]) for column in cursor.description]
    rows = [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]
    rows = effective_obligations(conn, rows)
    from yoke_core.domain.qa_simulation_triage import current_simulation_triage

    for row in rows:
        row["runner_id"] = row.pop("effective_runner_id", row.get("runner_id"))
        row["retracted_at"] = row.get("retracted_at")
        row["triage_discharge"] = bool(current_simulation_triage(conn, int(row["id"])))
    attempts = latest_executions(
        conn,
        [
            row["id"]
            for row in rows
            if not row.get("waived_at")
            and not row.get("retracted_at")
            and not item_supersession_settled(row)
        ],
    )
    for row in rows:
        attempt = attempts.get(int(row["id"]), {})
        row["run_id"] = attempt.get("id")
        for key in (
            "verdict",
            "verdict_reason",
            "execution_status",
            "case_outcome",
            "completed_at",
            "raw_result",
        ):
            row[key] = attempt.get(key)
    from yoke_core.domain.qa_requirement_pass_currency import passing_requirements_for_rows
    from yoke_core.domain.qa_subject_proof import subject_proof_error

    passing = passing_requirements_for_rows(conn, rows, attempts)
    for row in rows:
        attempt = attempts.get(int(row["id"]))
        row["current_passing_proof"] = (
            int(row["id"]) in passing
        )
        row["subject_proof_error"] = (
            subject_proof_error(conn, row, attempt)
            if attempt and row["current_passing_proof"]
            else ""
        )
        if row.get("qa_phase") == "post_deploy" and not row.get("deployment_run_id"):
            row["post_deploy_consumed"] = source_obligation_consumed(
                conn, item_id=item_id, source_requirement_id=int(row["id"])
            )
        row["recorded_head_sha"] = recorded_head_sha(row.get("raw_result"))
        waiting = requirement_awaits_human_review(conn, int(row["id"]))
        row["human_review"] = waiting.as_dict() if waiting else None
    return rows
