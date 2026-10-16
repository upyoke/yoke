"""A QA case declares whether its stage or steering starts it.

``wake_path`` defaults to ``automatic``. ``manual`` needs a one-line
``wake_evidence`` naming what must exist first. The pair round-trips through
plan authoring, rides into the requirement a case materializes, and a live
requirement is corrected in place, evidence first.
"""

import pytest

from runtime.api.domain.test_deployment_qa_manual_wake import EVIDENCE
from yoke_core.domain.qa_plan_case_definition import (
    materialized_definition,
    plan_cases,
)
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_edit import _current_cases
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    _plan_row,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update

CASE = {
    "case_key": "real-traffic",
    "method_id": "command",
    "instructions": "Read the run that real traffic produced.",
    "expected_outcome": "The run shows the behavior under real traffic.",
    "method_config": {"command": "true"},
}


def _plan(conn):
    return create_plan(conn, project="yoke", slug="manual-wake")


def test_manual_case_round_trips_and_materializes_its_wake_path(test_db):
    plan = _plan(test_db)
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[
            {**CASE, "wake_path": "manual", "wake_evidence": f"  {EVIDENCE}  "},
            {**CASE, "case_key": "stage-entry"},
        ],
    )

    stored = _current_cases(test_db, plan["id"])
    assert [(c["wake_path"], c["wake_evidence"]) for c in stored] == [
        ("manual", EVIDENCE),
        ("automatic", None),
    ]
    detail = get_plan(test_db, plan_id=plan["id"])["cases"][0]
    assert (detail["wake_path"], detail["wake_evidence"]) == ("manual", EVIDENCE)
    definition = materialized_definition(
        plan=_plan_row(test_db, plan["id"]),
        case=plan_cases(test_db, plan["id"])[0],
        qa_phase="post_deploy",
        baseline=None,
        baseline_position=0,
        transition_id=None,
    )
    assert (definition["wake_path"], definition["wake_evidence"]) == (
        "manual",
        EVIDENCE,
    )


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"wake_path": "manual"}, "wake_evidence_required"),
        ({"wake_path": "manual", "wake_evidence": "   "}, "wake_evidence_required"),
        ({"wake_evidence": EVIDENCE}, "wake_evidence_without_manual_wake"),
        ({"wake_path": "later"}, "wake_path_invalid"),
        (
            {"wake_path": "manual", "wake_evidence": "one\ntwo"},
            "wake_evidence_not_one_line",
        ),
    ],
)
def test_impossible_wake_declarations_refuse_by_name(test_db, fields, code):
    plan = _plan(test_db)
    with pytest.raises(QaPlanError, match=code):
        replace_plan_cases(test_db, plan_id=plan["id"], cases=[{**CASE, **fields}])


def _item_requirement(conn) -> int:
    row = conn.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,method_id,"
        "created_at) VALUES (1,'plan_case','post_deploy','command',%s) RETURNING id",
        ("2026-10-16T00:00:00Z",),
    ).fetchone()
    conn.commit()
    return int(row[0])


def test_live_requirement_is_marked_manual_evidence_first(test_db):
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(test_db, id=1, project_sequence=1, workflow_id="issue")
    requirement_id = _item_requirement(test_db)

    early = apply_requirement_update(test_db, requirement_id, "wake_path", "manual")
    assert not early.ok and "wake_evidence_required" in early.message
    assert "--field wake_evidence" in early.message

    assert apply_requirement_update(
        test_db, requirement_id, "wake_evidence", EVIDENCE
    ).ok
    assert apply_requirement_update(test_db, requirement_id, "wake_path", "manual").ok
    stored = test_db.execute(
        "SELECT wake_path, wake_evidence FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    assert tuple(stored) == ("manual", EVIDENCE)

    cleared = apply_requirement_update(test_db, requirement_id, "wake_evidence", None)
    assert not cleared.ok and "--field wake_path --value automatic" in cleared.message
    assert apply_requirement_update(
        test_db, requirement_id, "wake_path", "automatic"
    ).ok
    assert apply_requirement_update(test_db, requirement_id, "wake_evidence", None).ok
