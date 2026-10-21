"""One digest of the run state deployment QA writers read before the run lock.

A writer reads its run-wide facts unlocked and in batches, then takes the
``deployment_runs`` row lock only to write. Taking this fingerprint before
those reads and again under the lock proves no committed change landed in
between: membership and frozen snapshots, the members' plan attachments,
the run's requirement rows and verdicts, and its stage receipts. One
statement, whatever the run's size.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _table_exists


def _digest(select: str, order: str) -> str:
    return f"(SELECT md5(COALESCE(string_agg(t::text,'|' ORDER BY {order}),'')) FROM ({select}) t)"


def run_qa_fingerprint(
    conn: Any, run_id: str, *, include_progress: bool = False
) -> str:
    """The digest of every fact a QA writer's unlocked read depended on."""
    # A table a schema has not created yet holds no facts to change.
    present = {
        table: _table_exists(conn, table)
        for table in (
            "qa_plan_item_attachments",
            "qa_requirements",
            "qa_runs",
            "deployment_stage_receipts",
            "qa_plan_executions",
            "qa_artifacts",
            "decision_requests",
        )
    }
    parts = [
        _digest(
            "SELECT status,current_stage,settling_at,requirement_snapshot "
            "FROM deployment_runs WHERE id=%s",
            "t.status",
        ),
        _digest(
            "SELECT m.item_id,m.requirement_snapshot,i.status FROM deployment_run_items m "
            "JOIN items i ON i.id=m.item_id WHERE m.run_id=%s",
            "t.item_id",
        ),
    ]
    if present["qa_plan_item_attachments"]:
        parts.append(
            _digest(
                "SELECT a.* FROM qa_plan_item_attachments a "
                "JOIN deployment_run_items m ON m.item_id=a.item_id WHERE m.run_id=%s",
                "t.item_id,t.plan_id,t.transition_id,t.qa_phase",
            )
        )
    if present["qa_requirements"]:
        parts.append(
            _digest(
                # Whole rows: any column a schema carries is a fact read.
                (
                    "SELECT * FROM qa_requirements WHERE deployment_run_id=%s "
                    "OR (deployment_run_id IS NULL AND item_id IN "
                    "(SELECT item_id FROM deployment_run_items WHERE run_id=%s))"
                )
                if include_progress
                else "SELECT * FROM qa_requirements WHERE deployment_run_id=%s",
                "t.id",
            )
        )
        if present["qa_runs"]:
            parts.append(
                _digest(
                    "SELECT r.* FROM qa_runs r JOIN qa_requirements q "
                    "ON q.id=r.qa_requirement_id WHERE q.deployment_run_id=%s",
                    "t.id",
                )
            )
    if include_progress and present["qa_plan_executions"]:
        parts.append(
            _digest(
                "SELECT * FROM qa_plan_executions WHERE deployment_run_id=%s", "t.id"
            )
        )
    if (
        include_progress
        and present["qa_artifacts"]
        and present["qa_runs"]
        and present["qa_requirements"]
    ):
        parts.append(
            _digest(
                "SELECT a.* FROM qa_artifacts a JOIN qa_runs r ON r.id=a.qa_run_id "
                "JOIN qa_requirements q ON q.id=r.qa_requirement_id WHERE q.deployment_run_id=%s",
                "t.id",
            )
        )
    if include_progress and present["decision_requests"]:
        parts.append(
            _digest(
                "SELECT d.* FROM decision_requests d JOIN deployment_run_items m "
                "ON d.subject_type='item_transition' AND d.subject_key=m.item_id::text || ':done' "
                "WHERE m.run_id=%s",
                "t.id",
            )
        )
    if present["deployment_stage_receipts"]:
        parts.append(
            _digest(
                "SELECT id,stage_name,attempt_number,status "
                "FROM deployment_stage_receipts WHERE run_id=%s",
                "t.id",
            )
        )
    sql = f"SELECT md5(concat_ws(',',{','.join(parts)}))"
    row = conn.execute(sql, (str(run_id),) * sql.count("%s")).fetchone()
    return str(row[0])


__all__ = ["run_qa_fingerprint"]
