"""Explicit refresh reaches discharged rows; selectors preserve frozen content.

A plan selector never refreshes an existing admission from live content.
Explicit rematerialization carries a correction beside failed or discharged
history, and subsequent selection reuses that canonical frozen identity.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

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
from runtime.api.fixtures.qa_declared_replacement_fixture import declare
from yoke_core.domain.qa_requirement_ops import waive_requirement
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

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

    selected = _materialize(test_db, run_id, plan=slug)
    assert selected["created_requirement_ids"] == []
    assert selected["existing_requirement_ids"] == [requirement_id]
    result = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        plan=slug,
    )
    assert len(result["created_requirement_ids"]) == 1, result
    selected = _materialize(test_db, run_id, plan=slug)
    assert selected["created_requirement_ids"] == []
    assert selected["existing_requirement_ids"] == result["created_requirement_ids"]

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

    selected = _materialize(test_db, run_id, plan=slug)
    assert selected["created_requirement_ids"] == []
    assert selected["existing_requirement_ids"] == [requirement_id]
    result = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        plan=slug,
    )
    assert len(result["created_requirement_ids"]) == 1, result
    selected = _materialize(test_db, run_id, plan=slug)
    assert selected["created_requirement_ids"] == []
    assert selected["existing_requirement_ids"] == result["created_requirement_ids"]
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


def test_changed_live_plan_does_not_refresh_unjudged_frozen_selection(test_db) -> None:
    run_id = "run-refresh-live"
    slug, requirement_id = _seed(test_db, run_id)
    before = _rows(test_db, run_id)
    _edit_plan_case(test_db, slug, "probe --corrected")
    selected = _materialize(test_db, run_id, plan=slug)
    assert selected["created_requirement_ids"] == []
    assert selected["existing_requirement_ids"] == [requirement_id]
    assert _rows(test_db, run_id) == before
    refreshed = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        plan=slug,
    )
    assert refreshed["refreshed_requirement_ids"] == [requirement_id]
    assert "probe --corrected" in _rows(test_db, run_id)[0]["method_config"]


def test_content_digest_ignores_encoding_but_not_content() -> None:
    decoded = {"method_id": "command", "method_config": {"command": "probe"}}
    encoded = {"method_id": "command", "method_config": '{"command": "probe"}'}
    assert case_content_digest(decoded) == case_content_digest(encoded)

    changed = {"method_id": "command", "method_config": {"command": "probe -v"}}
    assert case_content_digest(decoded) != case_content_digest(changed)


@pytest.mark.parametrize("number", [0, 180, -45, 1000000])
def test_content_identity_preserves_numeric_value_across_json_encoding(number):
    source = {"method_config": {"actions": [{"ready_timeout_seconds": number}]}}
    copy = {
        "method_config": json.dumps(
            {"actions": [{"ready_timeout_seconds": float(number)}]}
        )
    }
    assert case_content_digest(source) == case_content_digest(copy)


@pytest.mark.parametrize("changed", [180.5, "180", True, None])
def test_content_identity_keeps_different_values_and_json_types_distinct(changed):
    source = {"method_config": {"ready_timeout_seconds": 180}}
    other = {"method_config": {"ready_timeout_seconds": changed}}
    assert case_content_digest(source) != case_content_digest(other)


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
    selected = _materialize(test_db, run_id, plan=slug)
    assert selected["created_requirement_ids"] == []
    assert selected["existing_requirement_ids"] == result["created_requirement_ids"]
    row = test_db.execute(
        "SELECT plan_id,plan_case_key FROM qa_requirements WHERE id=%s",
        (result["created_requirement_ids"][0],),
    ).fetchone()
    assert int(row["plan_id"]) == int(plan_id)
    assert str(row["plan_case_key"]) == "command-smoke"


@pytest.mark.parametrize("verdict", ["pass", None, "fail"])
def test_external_replacement_controls_automatic_correction(test_db, verdict) -> None:
    run_id = f"run-external-replacement-{verdict or 'pending'}"
    slug, original_id = _seed(test_db, run_id)
    record_case_verdict(test_db, original_id, "fail", evidence=True)
    replacement_slug = f"replacement-{run_id}"
    create_smoke_plan(test_db, project="yoke", slug=replacement_slug)
    replacement_id = int(
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=MEMBER,
            agent_plan=replacement_slug,
            replacement_keys={"command-smoke"},
        )["created_requirement_ids"][0]
    )
    declare(test_db, original_id, "command-smoke", [replacement_id])
    if verdict is not None:
        record_case_verdict(test_db, replacement_id, verdict, evidence=True)
    _edit_plan_case(test_db, slug, "probe --corrected")

    result = rematerialize_for_deployment_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        plan=slug,
    )
    created = result["created_requirement_ids"]
    assert len(created) == (1 if verdict == "fail" else 0), result
    assert len(_rows(test_db, run_id)) == (3 if verdict == "fail" else 2)
    selected = _materialize(test_db, run_id, plan=slug)
    assert selected["created_requirement_ids"] == []
    assert selected["existing_requirement_ids"] == (created or [original_id])
