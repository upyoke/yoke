# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)

from yoke_core.domain.deployment_qa_stage_acceptance import (
    STAGE_ACCEPTED,
    STAGE_DISCHARGED,
    STAGE_CASES_UNRESOLVED,
    stage_acceptance,
)

from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)

from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.deployment_qa_stage_outcome import OUTCOME_DISCHARGED

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)

from yoke_core.domain.qa_requirement_ops import waive_requirement

from yoke_core.domain.qa_requirement_supersession import (
    QaSupersessionError,
    supersede_requirement,
    supersession_history,
)

STAGE = ITEM_QA_STAGE

MEMBER = 9801


def _seed(conn: Any, run_id: str) -> int:
    """Seed one member parked on the QA stage; return its case requirement."""
    return seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)


def _record_verdict(
    conn: Any, requirement_id: int, verdict: str, *, evidence: bool
) -> int:
    return record_case_verdict(conn, requirement_id, verdict, evidence=evidence)


def _execute_stage(
    conn: Any,
    run_id: str,
    verdicts: dict[int, str],
) -> None:
    """Run the member's scoped execution, recording one verdict per case."""
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="member-qa",
    )
    for ordinal, entry in enumerate(execution["roster"]):
        requirement_id = int(entry["requirement_id"])
        verdict = verdicts[requirement_id]
        qa_run_id = _record_verdict(
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


def _corrected_case(conn: Any, *, broken_id: int) -> int:
    """A second blocking case pinned to the same subject and target.

    Copies every column of the frozen row so the replacement carries a
    complete execution snapshot, exactly as a real corrected case does;
    only its key and position differ.
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
        else column
        for column in columns
    ]
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) "
        f"SELECT {','.join(projected)} FROM qa_requirements WHERE id=%s "
        "RETURNING id",
        ("command-smoke-corrected", int(broken_id)),
    ).fetchone()
    conn.commit()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _status(conn: Any, run_id: str) -> dict[str, Any]:
    return deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=STAGE, member_item_id=MEMBER
    )


def _acceptance(conn: Any, run_id: str):
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=STAGE,
        member_item_id=MEMBER,
        require_active=False,
    )
    return stage_acceptance(
        conn,
        subject=subject,
        target=deployment_qa_execution_target(conn, subject),
        acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    )
