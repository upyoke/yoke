"""How the done gate explains the blocking requirements still holding an item.

Split out of :mod:`qa_gates` to stay under the authored file line budget. The
gate decides which rows still block; this renders why each one does and what
clears it, which differs by phase: a row that has never run is executed, while
a post_deploy row may already have a passing run recorded against a candidate
this delivery is not about, and is cleared instead by delivery, by a corrected
case that supersedes the defective admitted copy, or by an authorized waiver.
"""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.deployment_qa_source_obligation import POST_DEPLOY_RECOVERY
from yoke_core.domain.qa_review_requests import requirement_awaits_human_review

POST_DEPLOY_PHASE = "post_deploy"


def _phase(row: Any) -> str:
    return str(row["qa_phase"] or "")


def _run_id(row: Any) -> str:
    try:
        value = row["deployment_run_id"]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(value or "").strip()


def done_gate_refusal_errors(conn: Any, rows: Sequence[Any], *, name: str) -> list[str]:
    """The operator-facing refusal for rows that still hold ``done``."""
    errors = [
        f"Error: Cannot transition {name} to 'done' -- {len(rows)} blocking "
        "QA requirement(s) unsatisfied.",
        "  All blocking requirements must have a passing run or be waived.",
        "  Satisfy each requirement or use the registered waiver "
        "surface with explicit authorization.",
    ]
    for row in rows:
        waiting = requirement_awaits_human_review(conn, int(row["id"]))
        if waiting:
            errors.extend([f"  - {waiting.detail}", f"    {waiting.recovery}"])
            continue
        reason = (
            "not accepted on the completion run"
            if _phase(row) == POST_DEPLOY_PHASE
            else "no passing run"
        )
        run = _run_id(row)
        if _phase(row) == POST_DEPLOY_PHASE:
            errors.append(_target_recovery(conn, int(row["id"])))
        bound = f", run={run}" if run else ""
        errors.append(
            f"  - Requirement #{row['id']} ({row['qa_kind']}, "
            f"phase={row['qa_phase']}{bound}): {reason}"
        )
    if any(_phase(row) == POST_DEPLOY_PHASE for row in rows):
        errors.append(f"  {POST_DEPLOY_RECOVERY}")
    return errors


def _target_recovery(conn: Any, requirement_id: int) -> str:
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        requirement_target_environment,
    )
    from yoke_core.domain.db_helpers import query_one, query_rows

    row = query_one(
        conn,
        "SELECT target_env,execution_target_json,item_id FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    )
    if row is None:
        return ""
    name = requirement_target_environment(
        row["target_env"], row["execution_target_json"]
    )
    if not name:
        return ""
    flows = query_rows(
        conn,
        "SELECT df.id FROM deployment_flows df JOIN items i ON i.project_id=df.project_id "
        "WHERE i.id=%s AND df.status='active' AND EXISTS ("
        "SELECT 1 FROM jsonb_array_elements(df.stages::jsonb) stage "
        "WHERE stage->>'stage_kind'='qa' AND stage->>'scope'='item' AND stage->'target'->>'environment'=%s)",
        (row["item_id"], name),
    )
    carriers = ", ".join(str(flow["id"]) for flow in flows)
    recovery = (
        f"deliver the same candidate through flow(s) {carriers} and accept its item QA stage"
        if carriers
        else f"configure an active delivery flow with an item QA stage targeting {name!r}, then deliver the same candidate and accept that stage"
    )
    return f"    missing_target_proof: requirement #{requirement_id} needs accepted {name!r} proof; {recovery}."


def done_gate_refusal_text(conn: Any, rows: Sequence[Any], *, item_id: int) -> str:
    """Render :func:`done_gate_refusal_errors` for one item id."""
    from yoke_core.domain.project_identity import render_item_ref

    return "\n".join(
        done_gate_refusal_errors(conn, rows, name=render_item_ref(conn, int(item_id)))
    )


__all__ = ["done_gate_refusal_errors", "done_gate_refusal_text"]
