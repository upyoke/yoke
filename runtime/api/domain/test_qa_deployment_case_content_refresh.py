"""A corrected plan case reaches a member whose frozen row was discharged.

Stage materialization is idempotent per plan, which strands a member once its
only row is waived and the plan's case is then corrected: the discharged row
satisfies idempotency, so the fix never arrives. These cover the narrow
opening — changed content plus a row that no longer answers — and the cases
that must stay idempotent around it.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    record_case_verdict,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_deployment_case_content_refresh import (
    REFRESH_KEY_SEPARATOR,
    base_case_key,
    case_content_digest,
)
from yoke_core.domain.qa_requirement_ops import waive_requirement

MEMBER = 9821


def _seed(conn: Any, run_id: str) -> tuple[str, int]:
    """Seed a QA stage that pins no cases, so a project plan is selected.

    That is the shape the stranding was found in: the stage names no cases,
    the worker selects a plan, and the plan's own rows are live rather than
    frozen into the run.
    """
    slug = f"smoke-{run_id}"
    create_smoke_plan(conn, project="yoke", slug=slug)
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(MEMBER,),
        lineage="b" * 40,
    )
    result = _materialize(conn, run_id, plan=slug)
    return slug, int(result["created_requirement_ids"][0])


def _materialize(conn: Any, run_id: str, *, plan: str) -> dict[str, Any]:
    return materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        agent_plan=plan,
    )


def _edit_plan_case(conn: Any, slug: str, command: str) -> None:
    """Correct the selected plan's case content behind the frozen row."""
    conn.execute(
        "UPDATE qa_plan_cases SET method_config=%s WHERE plan_id="
        "(SELECT id FROM qa_plans WHERE slug=%s)",
        (json.dumps({"command": command}), slug),
    )
    conn.commit()


def _rows(conn: Any, run_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id,plan_case_key,method_config FROM qa_requirements "
            "WHERE deployment_run_id=%s AND deployment_stage=%s "
            "AND deployment_member_item_id=%s ORDER BY id",
            (run_id, ITEM_QA_STAGE, MEMBER),
        ).fetchall()
    ]


def test_corrected_case_reaches_a_member_whose_row_was_waived(test_db) -> None:
    run_id = "run-refresh-waived"
    slug, requirement_id = _seed(test_db, run_id)
    waive_requirement(
        test_db,
        requirement_id,
        "frozen case was broken; correcting the plan",
        source="operator",
        force=True,
    )
    _edit_plan_case(test_db, slug, "probe --corrected")

    result = _materialize(test_db, run_id, plan=slug)
    assert len(result["created_requirement_ids"]) == 1, result

    rows = _rows(test_db, run_id)
    assert len(rows) == 2
    # The waived row survives untouched as history; the corrected content
    # arrives beside it under a key the unique index can accept.
    frozen, corrected = rows
    assert frozen["id"] == requirement_id
    assert REFRESH_KEY_SEPARATOR not in str(frozen["plan_case_key"])
    assert REFRESH_KEY_SEPARATOR in str(corrected["plan_case_key"])
    assert base_case_key(corrected["plan_case_key"]) == str(frozen["plan_case_key"])
    assert "probe --corrected" in str(corrected["method_config"])


def test_corrected_case_reaches_a_member_whose_row_failed(test_db) -> None:
    run_id = "run-refresh-failed"
    slug, requirement_id = _seed(test_db, run_id)
    record_case_verdict(test_db, requirement_id, "fail", evidence=False)
    _edit_plan_case(test_db, slug, "probe --corrected")

    result = _materialize(test_db, run_id, plan=slug)
    assert len(result["created_requirement_ids"]) == 1, result
    assert len(_rows(test_db, run_id)) == 2


def test_unchanged_case_stays_idempotent_after_a_waiver(test_db) -> None:
    run_id = "run-refresh-unchanged"
    slug, requirement_id = _seed(test_db, run_id)
    waive_requirement(
        test_db,
        requirement_id,
        "operator released the stage without this case",
        source="operator",
        force=True,
    )

    result = _materialize(test_db, run_id, plan=slug)
    # Nothing about the case changed, so re-running the plan must not
    # manufacture work the waiver deliberately discharged.
    assert result["created_requirement_ids"] == []
    assert result["existing_requirement_ids"] == [requirement_id]
    assert len(_rows(test_db, run_id)) == 1


def test_changed_case_still_answered_stays_idempotent(test_db) -> None:
    run_id = "run-refresh-live"
    slug, _requirement_id = _seed(test_db, run_id)
    # Neither waived nor failed: the row is still the live obligation, so a
    # corrected plan must not race a second row alongside it.
    _edit_plan_case(test_db, slug, "probe --corrected")

    result = _materialize(test_db, run_id, plan=slug)
    assert result["created_requirement_ids"] == []
    assert len(_rows(test_db, run_id)) == 1


def test_content_digest_ignores_encoding_but_not_content() -> None:
    decoded = {"method_id": "command", "method_config": {"command": "probe"}}
    encoded = {"method_id": "command", "method_config": '{"command": "probe"}'}
    assert case_content_digest(decoded) == case_content_digest(encoded)

    changed = {"method_id": "command", "method_config": {"command": "probe -v"}}
    assert case_content_digest(decoded) != case_content_digest(changed)


def test_stage_picks_up_the_members_attached_plan_without_a_flag(test_db) -> None:
    """The wake needs no --plan choice once the member owns a plan.

    The member attaches its plan the ordinary way, before landing; stage
    materialization resolves it, so nobody picks a plan under pressure
    against an already-deployed candidate.
    """
    run_id = "run-attached-plan"
    slug = f"smoke-{run_id}"
    plan_id = create_smoke_plan(test_db, project="yoke", slug=slug)
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(MEMBER,),
        lineage="b" * 40,
    )
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments"
        "(item_id,plan_id,transition_id,qa_phase,attached_at)"
        " VALUES (%s,%s,%s,'post_deploy',%s)",
        (MEMBER, int(plan_id), "reviewing-implementation", "2026-09-18T00:00:00Z"),
    )
    test_db.commit()

    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    assert len(result["created_requirement_ids"]) == 1, result
    row = test_db.execute(
        "SELECT plan_id,plan_case_key FROM qa_requirements WHERE id=%s",
        (result["created_requirement_ids"][0],),
    ).fetchone()
    assert int(row["plan_id"]) == int(plan_id)
    assert str(row["plan_case_key"]) == "command-smoke"
