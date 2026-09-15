"""Ordered acceptance facts required before a later deployment QA stage."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from yoke_core.domain.deployment_stage_receipts import (
    deployment_stage_receipt_for_qa,
)


DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND = "deployment_stage_acceptance"


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _latest_verdict(conn: Any, requirement_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT verdict,raw_result FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        return {"verdict": "", "raw_result": {}}
    return {
        "verdict": str(row["verdict"] if hasattr(row, "keys") else row[0] or ""),
        "raw_result": _object(row["raw_result"] if hasattr(row, "keys") else row[1]),
    }


def _binding_refusal(
    conn: Any,
    *,
    run_id: str,
    stage: Mapping[str, Any],
    member: int | None,
    requirement: Any,
    verdict: Mapping[str, Any],
) -> str | None:
    target = _object(
        requirement["execution_target_json"]
        if hasattr(requirement, "keys")
        else requirement[2]
    )
    policy_target = stage.get("target")
    observation = target.get("observation")
    deployment = target.get("deployment")
    if not all(isinstance(value, Mapping) for value in (policy_target, observation, deployment)):
        return "acceptance has no complete receipt binding"
    if (
        str(deployment.get("run_id") or "") != run_id
        or str(deployment.get("stage") or "") != str(stage["name"])
        or deployment.get("member_item_id") != member
    ):
        return "acceptance target does not match its run/stage/member subject"
    try:
        deployment_stage_receipt_for_qa(
            conn,
            run_id=run_id,
            source_stage=str(policy_target.get("source_stage") or ""),
            expected_target_kind=str(policy_target.get("kind") or ""),
            expected_target_name=(
                str(policy_target.get("environment") or "")
                if policy_target.get("kind") == "persistent_environment"
                else None
            ),
            expected_release_lineage=str(deployment.get("release_lineage") or ""),
            expected_artifact_identity=deployment.get("artifact_identity"),
            receipt_id=int(observation.get("receipt_id") or 0),
        )
    except (LookupError, TypeError, ValueError) as exc:
        return f"acceptance receipt is no longer current: {exc}"
    if verdict.get("verdict") != "pass":
        return None
    execution_id = str(verdict.get("raw_result", {}).get("execution_id") or "")
    if not execution_id:
        requirement_id = int(
            requirement["id"] if hasattr(requirement, "keys") else requirement[0]
        )
        history = conn.execute(
            "SELECT raw_result FROM qa_runs WHERE qa_requirement_id=%s "
            "ORDER BY created_at DESC,id DESC",
            (requirement_id,),
        ).fetchall()
        execution_id = next(
            (
                str(_object(row["raw_result"])["execution_id"])
                for row in history
                if _object(row["raw_result"]).get("execution_id")
            ),
            "",
        )
    execution = conn.execute(
        "SELECT state,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,execution_target_json "
        "FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()
    if execution is None:
        return "passing acceptance does not identify its completed execution"
    if (
        str(execution["state"]) != "completed"
        or str(execution["deployment_run_id"]) != run_id
        or str(execution["deployment_stage"]) != str(stage["name"])
        or execution["deployment_member_item_id"] != member
        or _object(execution["execution_target_json"]) != target
    ):
        return "passing acceptance does not match its completed scoped execution"
    return None


def _current_acceptance(
    conn: Any,
    *,
    run_id: str,
    stage: Mapping[str, Any],
    member: int | None,
) -> tuple[Any, dict[str, Any]] | None:
    rows = conn.execute(
        "SELECT id,waived_at,execution_target_json FROM qa_requirements "
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
    valid: list[tuple[Any, dict[str, Any]]] = []
    for candidate in rows:
        candidate_id = int(
            candidate["id"] if hasattr(candidate, "keys") else candidate[0]
        )
        candidate_verdict = _latest_verdict(conn, candidate_id)
        refusal = _binding_refusal(
            conn,
            run_id=run_id,
            stage=stage,
            member=member,
            requirement=candidate,
            verdict=candidate_verdict,
        )
        if refusal is None:
            valid.append((candidate, candidate_verdict))
    if len(valid) != 1:
        return None
    return valid[0]


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
                "SELECT id,waived_at,execution_target_json FROM qa_requirements "
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
            valid: list[tuple[Any, dict[str, Any]]] = []
            invalid_reasons: list[str] = []
            for candidate in rows:
                candidate_id = int(
                    candidate["id"] if hasattr(candidate, "keys") else candidate[0]
                )
                candidate_verdict = _latest_verdict(conn, candidate_id)
                refusal = _binding_refusal(
                    conn,
                    run_id=run_id,
                    stage=stage,
                    member=member,
                    requirement=candidate,
                    verdict=candidate_verdict,
                )
                if refusal is None:
                    valid.append((candidate, candidate_verdict))
                else:
                    invalid_reasons.append(refusal)
            if len(valid) != 1:
                refusals.append(
                    f"stage {stage['name']!r} member {member!r} has "
                    f"{len(valid)} current acceptance records"
                    + (f" ({'; '.join(invalid_reasons)})" if invalid_reasons else "")
                )
                continue
            row, latest = valid[0]
            waived_at = row["waived_at"] if hasattr(row, "keys") else row[1]
            if not waived_at and latest["verdict"] != "pass":
                refusals.append(
                    f"stage {stage['name']!r} member {member!r} is not accepted"
                )
    return refusals


def current_item_scoped_qa_accepted(conn: Any, *, item_id: int) -> bool:
    """True when this item's latest run accepted every item-scoped QA stage."""
    from yoke_core.domain.schema_common import _table_exists

    required = ("deployment_runs", "deployment_run_items", "deployment_flows")
    if not all(_table_exists(conn, table) for table in required):
        return False
    row = conn.execute(
        "SELECT dr.id, df.stages FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dri.run_id = dr.id "
        "JOIN deployment_flows df ON df.id = dr.flow "
        "WHERE dri.item_id = %s "
        "ORDER BY dr.created_at DESC, dr.id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return False
    run_id = str(row["id"] if hasattr(row, "keys") else row[0])
    try:
        stages = json.loads(str(row["stages"] if hasattr(row, "keys") else row[1]))
    except (TypeError, ValueError):
        return False
    if not isinstance(stages, list):
        return False
    qa_stages = [
        dict(stage)
        for stage in stages
        if isinstance(stage, Mapping)
        and stage.get("stage_kind") == "qa"
        and stage.get("step_runner") == "qa"
        and stage.get("scope") == "item"
    ]
    if not qa_stages:
        return False
    for stage in qa_stages:
        current = _current_acceptance(
            conn, run_id=run_id, stage=stage, member=int(item_id)
        )
        if current is None:
            return False
        record, latest = current
        waived_at = record["waived_at"] if hasattr(record, "keys") else record[1]
        if not waived_at and latest["verdict"] != "pass":
            return False
    return True


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
    "current_item_scoped_qa_accepted",
    "prior_stage_refusals",
    "require_prior_stage_acceptance",
]
