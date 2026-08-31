"""QA requirement and plan-attachment read models for item detail."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_execution_proof import (
    qa_artifact_counts_by_run,
    qa_precondition_reason,
    qa_proof_summary,
    qa_run_outcome,
)
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_plan_attachments import (
    workflow_uses_project_testing_defaults,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def qa_rows(conn: Any, item_id: int) -> list[dict[str, Any]]:
    """Return each requirement with its latest run and proof summary."""
    if not _table_exists(conn, "qa_requirements"):
        return []
    marker = _p(conn)

    def requirement_column(name: str) -> str:
        if _column_exists(conn, "qa_requirements", name):
            return f"q.{name}"
        return f"NULL AS {name}"

    def run_column(name: str) -> str:
        if _column_exists(conn, "qa_runs", name):
            return f"r.{name}"
        return f"NULL AS {name}"

    has_plans = _table_exists(conn, "qa_plans") and _column_exists(
        conn, "qa_requirements", "plan_id"
    )
    has_methods = _table_exists(conn, "qa_methods") and _column_exists(
        conn, "qa_requirements", "method_id"
    )
    has_method_proof_kind = has_methods and _column_exists(
        conn, "qa_methods", "proof_kind"
    )
    has_artifacts = _table_exists(conn, "qa_artifacts")
    select = [
        "q.id",
        "q.qa_kind",
        "q.qa_phase",
        "q.blocking_mode",
        "q.requirement_source",
        "q.success_policy",
        "q.waived_at",
        "q.created_at",
        requirement_column("plan_id"),
        requirement_column("plan_case_key"),
        requirement_column("method_id"),
        requirement_column("workflow_transition_id"),
        requirement_column("instructions"),
        requirement_column("expected_outcome"),
        requirement_column("host_baseline"),
        "p.slug AS plan_slug" if has_plans else "NULL AS plan_slug",
        "p.name AS plan_name" if has_plans else "NULL AS plan_name",
        "m.name AS method_name" if has_methods else "NULL AS method_name",
        "m.proof_kind" if has_method_proof_kind else "NULL AS proof_kind",
        "r.id AS run_id",
        "r.verdict",
        run_column("verdict_reason"),
        "r.execution_status",
        "r.completed_at",
        run_column("case_outcome"),
        run_column("capture_degraded_reason"),
        run_column("raw_result"),
        (
            "(SELECT COUNT(*) FROM qa_artifacts a "
            "WHERE a.qa_run_id = r.id) AS evidence_count"
            if has_artifacts
            else "0 AS evidence_count"
        ),
        (
            "(SELECT a.artifact_type FROM qa_artifacts a "
            "WHERE a.qa_run_id = r.id ORDER BY a.id DESC LIMIT 1) "
            "AS latest_evidence_type"
            if has_artifacts
            else "NULL AS latest_evidence_type"
        ),
    ]
    joins = [
        "FROM qa_requirements q",
        "LEFT JOIN qa_runs r ON r.id = ("
        "  SELECT MAX(latest.id) FROM qa_runs latest "
        "  WHERE latest.qa_requirement_id = q.id"
        ")",
    ]
    if has_plans:
        joins.append("LEFT JOIN qa_plans p ON p.id = q.plan_id")
    if has_methods:
        joins.append("LEFT JOIN qa_methods m ON m.id = q.method_id")
    rows = _dict_rows(
        conn.execute(
            f"SELECT {', '.join(select)} {' '.join(joins)} "
            f"WHERE q.item_id = {marker} OR q.epic_id = {marker} "
            "ORDER BY q.id",
            (item_id, item_id),
        )
    )
    run_ids = {int(row["run_id"]) for row in rows if row.get("run_id") is not None}
    artifacts_by_run = qa_artifact_counts_by_run(conn, run_ids) if has_artifacts else {}
    for row in rows:
        run_id = int(row["run_id"]) if row.get("run_id") is not None else None
        outcome = qa_run_outcome(row)
        raw_result = row.pop("raw_result", None)
        row["recorded_head_sha"] = recorded_head_sha(raw_result)
        precondition_reason = qa_precondition_reason(raw_result)
        row["outcome"] = outcome
        row["precondition_reason"] = precondition_reason
        row["proof_summary"] = qa_proof_summary(
            method_id=row.get("method_id"),
            run_id=run_id,
            raw_result=raw_result,
            artifacts=artifacts_by_run.get(run_id, {}),
            outcome=outcome,
            verdict_reason=row.get("verdict_reason"),
            capture_degraded_reason=row.get("capture_degraded_reason"),
            host_baseline=row.get("host_baseline"),
            precondition_reason=precondition_reason,
            proof_kind=row.get("proof_kind"),
        )
    return rows


def qa_plan_attachments(
    conn: Any,
    *,
    item_id: int,
    project_id: int,
    workflow_id: str,
    requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return project-default and item-specific plan attachments."""
    if not _table_exists(conn, "qa_plans"):
        return []
    marker = _p(conn)
    attachments: dict[tuple[int, str], dict[str, Any]] = {}
    if (
        _table_exists(conn, "qa_plan_project_defaults")
        and workflow_uses_project_testing_defaults(conn, int(item_id))
    ):
        rows = _dict_rows(
            conn.execute(
                "SELECT d.plan_id, d.transition_id, d.qa_phase, d.attached_at, "
                "p.slug AS plan_slug, p.name AS plan_name "
                "FROM qa_plan_project_defaults d "
                "JOIN qa_plans p ON p.id = d.plan_id "
                f"WHERE d.project_id = {marker} AND d.workflow_id = {marker} "
                "ORDER BY d.transition_id, d.plan_id",
                (project_id, workflow_id),
            )
        )
        for row in rows:
            row["source"] = "project default"
            attachments[(int(row["plan_id"]), str(row["transition_id"]))] = row
    if _table_exists(conn, "qa_plan_item_attachments"):
        rows = _dict_rows(
            conn.execute(
                "SELECT a.plan_id, a.transition_id, a.qa_phase, a.attached_at, "
                "p.slug AS plan_slug, p.name AS plan_name "
                "FROM qa_plan_item_attachments a "
                "JOIN qa_plans p ON p.id = a.plan_id "
                f"WHERE a.item_id = {marker} "
                "ORDER BY a.transition_id, a.plan_id",
                (item_id,),
            )
        )
        for row in rows:
            row["source"] = "item attachment"
            attachments[(int(row["plan_id"]), str(row["transition_id"]))] = row
    if not attachments:
        return []

    case_counts: dict[int, int] = {}
    if _table_exists(conn, "qa_plan_cases"):
        plan_ids = sorted({key[0] for key in attachments})
        placeholders = ", ".join(marker for _ in plan_ids)
        rows = _dict_rows(
            conn.execute(
                "SELECT plan_id, COUNT(*) AS total FROM qa_plan_cases "
                f"WHERE plan_id IN ({placeholders}) GROUP BY plan_id",
                tuple(plan_ids),
            )
        )
        case_counts = {int(row["plan_id"]): int(row["total"]) for row in rows}

    for (plan_id, transition_id), attachment in attachments.items():
        materialized = [
            row
            for row in requirements
            if int(row.get("plan_id") or 0) == plan_id
            and (
                not row.get("workflow_transition_id")
                or str(row["workflow_transition_id"]) == transition_id
            )
        ]
        attachment["case_count"] = case_counts.get(plan_id, 0)
        attachment["materialized_count"] = len(materialized)
        attachment["materialized_at"] = next(
            (row.get("created_at") for row in materialized if row.get("created_at")),
            None,
        )
    return list(attachments.values())


__all__ = ["qa_plan_attachments", "qa_rows"]
