"""Ordered acceptance facts required before a later deployment QA stage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND = "deployment_stage_acceptance"


def _latest_verdict(conn: Any, requirement_id: int) -> str:
    row = conn.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        return ""
    return str(row["verdict"] if hasattr(row, "keys") else row[0] or "")


def _subjects(conn: Any, run_id: str, stage: Mapping[str, Any]) -> list[int | None]:
    if stage.get("scope") != "item":
        return [None]
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return [int(row["item_id"] if hasattr(row, "keys") else row[0]) for row in rows]


def prior_stage_refusals(
    conn: Any,
    *,
    run_id: str,
    stages: Sequence[Mapping[str, Any]],
    start_stage: str,
) -> list[str]:
    """Return missing/rejected scoped acceptances before ``start_stage``."""
    names = [str(stage.get("name") or "") for stage in stages]
    if start_stage not in names:
        return []
    refusals: list[str] = []
    for stage in stages[: names.index(start_stage)]:
        if stage.get("stage_kind") != "qa" or stage.get("step_runner") != "qa":
            continue
        subjects = _subjects(conn, run_id, stage)
        if not subjects:
            refusals.append(f"stage {stage['name']!r} has no attached item subjects")
            continue
        for member in subjects:
            rows = conn.execute(
                "SELECT id,waived_at FROM qa_requirements "
                "WHERE deployment_run_id=%s AND deployment_stage=%s "
                "AND COALESCE(deployment_member_item_id,0)=%s AND qa_kind=%s "
                "ORDER BY id",
                (
                    run_id,
                    str(stage["name"]),
                    member or 0,
                    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
                ),
            ).fetchall()
            if len(rows) != 1:
                refusals.append(
                    f"stage {stage['name']!r} member {member!r} has "
                    f"{len(rows)} acceptance records"
                )
                continue
            row = rows[0]
            requirement_id = int(row["id"] if hasattr(row, "keys") else row[0])
            waived_at = row["waived_at"] if hasattr(row, "keys") else row[1]
            if not waived_at and _latest_verdict(conn, requirement_id) != "pass":
                refusals.append(
                    f"stage {stage['name']!r} member {member!r} is not accepted"
                )
    return refusals


def require_prior_stage_acceptance(
    conn: Any,
    *,
    run_id: str,
    stages: Sequence[Mapping[str, Any]],
    start_stage: str,
) -> None:
    refusals = prior_stage_refusals(
        conn, run_id=run_id, stages=stages, start_stage=start_stage
    )
    if refusals:
        raise ValueError(
            "deployment QA stage cannot begin before prior scoped QA acceptance: "
            + "; ".join(refusals)
            + ". Recovery: finish or explicitly waive every named prior stage subject."
        )


__all__ = [
    "DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND",
    "prior_stage_refusals",
    "require_prior_stage_acceptance",
]
