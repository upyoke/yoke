"""Permanent coverage for clearing positions off plan-less QA requirements.

The rows this entry corrects were written by the admission materializer
before it stopped stamping positions onto a copy that belongs to no plan.
They are unrunnable until it runs: every execution begin reads the number as
"this requirement joined a plan after the roster froze" and refuses.
"""

from __future__ import annotations

import importlib

import pytest

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0045_plan_less_admitted_qa_case_positions"
)


def _requirement(
    conn,
    *,
    plan_id: int | None,
    case_position: int | None,
    baseline_position: int | None,
    case_key: str,
) -> int:
    row = conn.execute(
        "INSERT INTO qa_requirements(deployment_run_id,deployment_stage,"
        "qa_kind,qa_phase,blocking_mode,"
        "requirement_source,created_at,plan_id,plan_case_key,case_position,"
        "baseline_position,method_id,method_name,runner_id,verdict_path) "
        "VALUES ('run-position-repair','member-qa',"
        "'release_qa','post_deploy','blocking','flow_derived',"
        "'2026-09-19T12:26:00Z',%s,%s,%s,%s,'exploratory-mission',"
        "'Exploratory mission','agent_mission','agent_review') RETURNING id",
        (plan_id, case_key, case_position, baseline_position),
    ).fetchone()
    return int(row["id"])


def _positions(conn, requirement_id: int) -> tuple[int | None, int | None]:
    row = conn.execute(
        "SELECT case_position,baseline_position FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    return row["case_position"], row["baseline_position"]


def test_an_admitted_copy_loses_the_positions_it_never_owned(test_db) -> None:
    admitted = _requirement(
        test_db,
        plan_id=None,
        case_position=2,
        baseline_position=1,
        case_key="admitted-requirement-27748",
    )

    MIGRATION.apply(test_db)

    assert _positions(test_db, admitted) == (None, None)
    MIGRATION.invariants(test_db)


def test_a_planned_case_keeps_the_positions_its_plan_assigned(test_db) -> None:
    plan = int(
        test_db.execute(
            "INSERT INTO qa_plans(project_id,slug,name,created_at,updated_at) "
            "VALUES (1,'position-retention','Position retention',"
            "'2026-09-19T12:26:00Z','2026-09-19T12:26:00Z') RETURNING id"
        ).fetchone()["id"]
    )
    planned = _requirement(
        test_db,
        plan_id=plan,
        case_position=3,
        baseline_position=2,
        case_key="planned-case",
    )

    MIGRATION.apply(test_db)

    assert _positions(test_db, planned) == (3, 2)


def test_a_half_positioned_plan_less_row_is_cleared_too(test_db) -> None:
    half = _requirement(
        test_db,
        plan_id=None,
        case_position=None,
        baseline_position=1,
        case_key="admitted-requirement-27749",
    )

    MIGRATION.apply(test_db)

    assert _positions(test_db, half) == (None, None)


def test_the_entry_is_idempotent_against_rows_already_written_correctly(
    test_db,
) -> None:
    already_correct = _requirement(
        test_db,
        plan_id=None,
        case_position=None,
        baseline_position=None,
        case_key="admitted-requirement-27750",
    )

    MIGRATION.apply(test_db)
    MIGRATION.apply(test_db)

    assert _positions(test_db, already_correct) == (None, None)
    MIGRATION.invariants(test_db)


def test_the_invariant_names_a_plan_less_row_that_still_holds_a_position(
    test_db,
) -> None:
    _requirement(
        test_db,
        plan_id=None,
        case_position=1,
        baseline_position=1,
        case_key="admitted-requirement-27751",
    )

    with pytest.raises(AssertionError, match="plan-less row"):
        MIGRATION.invariants(test_db)
