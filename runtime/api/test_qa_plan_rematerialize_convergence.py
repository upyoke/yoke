"""Materialize and rematerialize converge a plan's added, amended and lost cases.

Each test reproduces one way the two writers used to leave a subject short of
its plan: an added case with no row, an answered sibling that froze the whole
stage, an answered plan whose stale item row nothing could reach, an explicit
correction colliding with an automatic one, and a correction marker read as
changed content.
"""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import CATALOG_CASES
from yoke_core.domain.qa_deployment_case_content_refresh import (
    case_content_digest,
    refreshed_case_keys,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)
from yoke_core.domain.qa_requirement_replacement import (
    declare_existing_replacement,
)

MEMBER = 9861


def _case(key: str, instructions: str, position: int = 1) -> dict:
    return {
        "case_key": key,
        "position": position,
        "method_id": "command",
        "instructions": instructions,
        "expected_outcome": "the command passes",
        "method_config": {"command": "true"},
    }


def _plan_id(conn, requirement_id: int) -> int:
    return int(
        conn.execute(
            "SELECT plan_id FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()["plan_id"]
    )


def _row(conn, requirement_id: int) -> dict:
    return dict(
        conn.execute(
            "SELECT plan_case_key,instructions,waived_at,replacement_requirement_id "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
    )


def _stage(conn, run_id: str) -> dict:
    return {
        "deployment_run_id": run_id,
        "deployment_stage": ITEM_QA_STAGE,
        "deployment_member_item_id": MEMBER,
    }


def _two_case_stage(conn, run_id: str) -> tuple[int, int, int]:
    """A stage holding the seeded case plus one the plan gained afterwards."""
    first = seed_member_qa_case(conn, run_id=run_id, member_item_id=MEMBER)
    plan_id = _plan_id(conn, first)
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            _case("command-smoke", "run the frozen smoke command", 1),
            _case("second-smoke", "run the second smoke command", 2),
        ],
    )
    conn.commit()
    result = rematerialize_for_deployment_stage(conn, **_stage(conn, run_id))
    assert len(result["created_requirement_ids"]) == 1
    return plan_id, first, int(result["created_requirement_ids"][0])


def test_stage_rematerialize_converges_a_mixed_roster_case_by_case(test_db) -> None:
    run_id = "run-converge-mixed"
    plan_id, failed, pending = _two_case_stage(test_db, run_id)
    record_case_verdict(test_db, failed, "fail", evidence=True)
    replace_plan_cases(
        test_db,
        plan_id=plan_id,
        cases=[
            _case("command-smoke", "run the corrected smoke command", 1),
            _case("second-smoke", "run the corrected second command", 2),
        ],
    )
    test_db.commit()

    result = rematerialize_for_deployment_stage(test_db, **_stage(test_db, run_id))

    # The unjudged sibling refreshes; the failed one is not refused but
    # carried by exactly one corrected row declared its replacement.
    assert result["refreshed_requirement_ids"] == [pending]
    assert len(result["created_requirement_ids"]) == 1
    corrected = int(result["created_requirement_ids"][0])
    assert _row(test_db, pending)["instructions"] == "run the corrected second command"
    assert _row(test_db, corrected)["plan_case_key"].startswith("command-smoke@")
    assert _row(test_db, failed)["replacement_requirement_id"] == corrected
    assert _row(test_db, failed)["instructions"] == "run the frozen smoke command"

    again = rematerialize_for_deployment_stage(test_db, **_stage(test_db, run_id))
    assert again["created_requirement_ids"] == []


def test_stage_rematerialize_leaves_answered_cases_whose_content_held(test_db) -> None:
    run_id = "run-converge-answered"
    _plan, failed, passed = _two_case_stage(test_db, run_id)
    record_case_verdict(test_db, failed, "fail", evidence=True)
    record_case_verdict(test_db, passed, "pass", evidence=True)

    result = rematerialize_for_deployment_stage(test_db, **_stage(test_db, run_id))

    assert result["created_requirement_ids"] == []
    assert result["refreshed_requirement_ids"] == []
    assert result["waived_requirement_ids"] == []


def test_stage_rematerialize_keeps_a_passed_case_and_waives_a_lost_one(test_db) -> None:
    run_id = "run-converge-lost"
    plan_id, passed, lost = _two_case_stage(test_db, run_id)
    record_case_verdict(test_db, passed, "pass", evidence=True)
    replace_plan_cases(
        test_db,
        plan_id=plan_id,
        cases=[_case("command-smoke", "a later wording of the smoke command", 1)],
    )
    test_db.commit()

    result = rematerialize_for_deployment_stage(test_db, **_stage(test_db, run_id))

    assert result["created_requirement_ids"] == []
    assert result["waived_requirement_ids"] == [lost]
    assert _row(test_db, lost)["waived_at"]
    assert _row(test_db, passed)["instructions"] == "run the frozen smoke command"


def test_explicit_replacement_suppresses_the_automatic_one(test_db) -> None:
    run_id = "run-converge-explicit"
    failed = seed_member_qa_case(test_db, run_id=run_id, member_item_id=MEMBER)
    record_case_verdict(test_db, failed, "fail", evidence=True)
    digest = test_db.execute(
        "SELECT execution_target_digest FROM qa_requirements WHERE id=%s", (failed,)
    ).fetchone()["execution_target_digest"]
    scope = {
        "run_id": run_id,
        "stage_name": ITEM_QA_STAGE,
        "member_item_id": MEMBER,
        "plan_id": _plan_id(test_db, failed),
        "execution_target_digest": str(digest),
        "cases": [_case("command-smoke", "run the corrected smoke command")],
    }

    assert list(refreshed_case_keys(test_db, **scope)) == ["command-smoke"]
    assert (
        refreshed_case_keys(test_db, **scope, explicitly_replaced=frozenset({failed}))
        == {}
    )


def test_correction_marker_is_not_changed_content() -> None:
    case = _case("command-smoke", "run it")
    marked = {**case, "method_config": '{"command": "true", "_corrected": true}'}
    assert case_content_digest(marked) == case_content_digest(case)


def _item_release_plan(conn, item_id: int, cases: list[dict]) -> int:
    plan = create_plan(conn, project="yoke", slug=f"converge-{item_id}", name="c")
    replace_plan_cases(conn, plan_id=plan["id"], cases=cases)
    set_project_default(
        conn, plan_id=plan["id"], workflow_id="issue", transition_id="release"
    )
    return int(plan["id"])


def test_item_rematerialize_reaches_a_plan_a_delivery_already_answered() -> None:
    with test_database() as conn:
        item = insert_item(conn, id=71, project_sequence=71, workflow_id="issue")
        plan_id = _item_release_plan(conn, 71, [CATALOG_CASES[0]])
        (requirement_id,) = materialize_for_item(
            conn, item_id=int(item["id"]), transition_id="release"
        )["created_requirement_ids"]
        amended = {**CATALOG_CASES[0], "instructions": "Run the corrected suite."}
        replace_plan_cases(conn, plan_id=plan_id, cases=[amended, CATALOG_CASES[1]])
        conn.commit()
        with patch(
            "yoke_core.domain.qa_plan_rematerialize.attachments_still_owed",
            return_value=({}, True),
        ):
            result = rematerialize_for_item(
                conn, item_id=int(item["id"]), transition_id="release"
            )
        instructions = _row(conn, requirement_id)["instructions"]

    assert result["plan_ids"] == [plan_id]
    assert result["refreshed_requirement_ids"] == [requirement_id]
    # Answered: the existing row comes current, but no fresh obligation.
    assert result["created_requirement_ids"] == []
    assert instructions == "Run the corrected suite."


def test_item_case_accepts_a_declared_replacement() -> None:
    with test_database() as conn:
        item = insert_item(conn, id=72, project_sequence=72, workflow_id="issue")
        _item_release_plan(conn, 72, CATALOG_CASES)
        failed, corrected = materialize_for_item(
            conn, item_id=int(item["id"]), transition_id="release"
        )["created_requirement_ids"]
        record_case_verdict(conn, failed, "fail", evidence=True)
        receipt = declare_existing_replacement(
            conn, failed_id=failed, replacement_id=corrected
        )
        conn.commit()
        pointer = _row(conn, failed)["replacement_requirement_id"]

    assert receipt["replacement_requirement_id"] == corrected
    assert receipt["workflow_transition_id"] == "release"
    assert pointer == corrected
