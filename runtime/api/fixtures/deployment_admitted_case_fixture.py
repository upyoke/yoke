"""Seed a delivery whose admitted post-deploy copy failed on the candidate.

``deployment_scoped_qa_run_fixture`` seeds the plan-backed shape, where a
stage's cases come from a project QA plan. This seeds the other one: an item
that owes a ``post_deploy`` obligation, a run that froze that obligation into
an admitted copy, and a copy that recorded ``fail`` against the deployed
target. That is the state every discharge question is asked from.

The run is deliberately left executing on its QA stage. Scoped QA writes
require the active stage, so authoring and running a corrected case is only
possible here -- which is also the honest window for the correction the
freeze refusal prescribes.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
    _seed_selected_requirement_run,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_acceptance import stage_acceptance
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)

#: The item-scoped QA stage `_seed_selected_requirement_run` pins.
MEMBER_QA_STAGE = "member-qa"


def intake_requirement(conn: Any, *, item_id: int) -> int:
    """One blocking post-deploy obligation the item owes every delivery."""
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type) "
        "VALUES(1,'browser-control') ON CONFLICT DO NOTHING"
    )
    requirement_id = _original_requirement(
        conn, item_id=item_id, method_id="browser-inspection"
    )
    conn.execute(
        "UPDATE qa_requirements SET workflow_transition_id=%s WHERE id=%s",
        (ITEM_POSTURE_VERIFICATION_TRANSITION, requirement_id),
    )
    conn.commit()
    return requirement_id


def admitted_copy(conn: Any, *, run_id: str, item_id: int) -> int:
    """Freeze the item's obligation onto this run's stage; return the copy."""
    created = materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=MEMBER_QA_STAGE,
        deployment_member_item_id=item_id,
    )
    return int(created["created_requirement_ids"][0])


def corrected_sibling(conn: Any, *, broken_id: int) -> int:
    """A second blocking case pinned to the same subject and target.

    Every column is copied so the replacement carries a complete execution
    snapshot, exactly as a case re-authored against the real target does;
    only its key, its position and its own discharge state differ.
    """
    columns = [
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name<>'id' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    projected = [
        "%s"
        if column == "plan_case_key"
        else "case_position+1"
        if column == "case_position"
        else "NULL"
        if column in ("superseded_by_requirement_id", "superseded_at")
        else column
        for column in columns
    ]
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) "
        f"SELECT {','.join(projected)} FROM qa_requirements WHERE id=%s "
        "RETURNING id",
        ("corrected-against-deployed-target", int(broken_id)),
    ).fetchone()
    conn.commit()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def execute_member_stage(
    conn: Any, *, run_id: str, item_id: int, verdicts: dict[int, str]
) -> None:
    """Run the member's scoped execution, recording one verdict per case."""
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=MEMBER_QA_STAGE,
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id=f"qa-{run_id}",
    )
    for ordinal, entry in enumerate(execution["roster"]):
        requirement_id = int(entry["requirement_id"])
        verdict = verdicts[requirement_id]
        qa_run_id = record_case_verdict(
            conn, requirement_id, verdict, evidence=verdict == "pass"
        )
        advance_plan_execution(
            conn,
            execution,
            ordinal=ordinal,
            requirement_id=requirement_id,
            result={
                "requirement_id": requirement_id,
                "verdict": verdict,
                "case_outcome": "passed" if verdict == "pass" else "failed",
                "run_id": qa_run_id,
            },
        )
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    conn.commit()


def succeed_run(conn: Any, run_id: str) -> None:
    conn.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s", (run_id,)
    )
    conn.commit()


def member_stage_acceptance(conn: Any, run_id: str, item_id: int):
    """Read the stage's acceptance without requiring it to be the live one.

    The done gate reads a stage the run has already left, so every read here
    passes ``require_active=False`` for the same reason it does.
    """
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=MEMBER_QA_STAGE,
        member_item_id=item_id,
        require_active=False,
    )
    return stage_acceptance(
        conn,
        subject=subject,
        target=deployment_qa_execution_target(conn, subject),
        acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    )


def deliver_with_failing_admitted_copy(
    conn: Any, *, item_id: int, run_id: str, corrected: bool
) -> tuple[int, int, int]:
    """Deliver the item as far as its QA stage, the admitted copy failing.

    Returns the intake row, the broken admitted copy, and the corrected
    sibling (``0`` when this delivery authored none).
    """
    intake_id = intake_requirement(conn, item_id=item_id)
    _seed_selected_requirement_run(
        conn, run_id=run_id, item_id=item_id, requirement_id=intake_id
    )
    broken_id = admitted_copy(conn, run_id=run_id, item_id=item_id)
    corrected_id = corrected_sibling(conn, broken_id=broken_id) if corrected else 0
    verdicts = {broken_id: "fail"}
    if corrected_id:
        verdicts[corrected_id] = "pass"
    execute_member_stage(conn, run_id=run_id, item_id=item_id, verdicts=verdicts)
    return intake_id, broken_id, corrected_id


__all__ = [
    "MEMBER_QA_STAGE",
    "admitted_copy",
    "corrected_sibling",
    "deliver_with_failing_admitted_copy",
    "execute_member_stage",
    "intake_requirement",
    "member_stage_acceptance",
    "succeed_run",
]
