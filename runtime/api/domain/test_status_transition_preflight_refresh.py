"""Preflight side effects and workflow-pin refresh behavior."""

from __future__ import annotations

from runtime.api.domain.test_status_transition_preflight import (
    TARGET_STATUS,
    _actor_id,
    _isolate_status_effects,
    _publish_approval_workflow,
)
from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain import (
    backlog,
    workflow_status_transition_preflight,
)
from yoke_core.domain.qa_plan_attachments import attach_plan_to_item
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)


def test_status_preflight_materializes_attached_plan(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    item_id = 964
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    plan = create_plan(
        test_db,
        project="yoke",
        slug="status-preflight-plan",
        name="Status preflight plan",
    )
    replace_plan_cases(
        test_db,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the focused smoke check.",
                "expected_outcome": "The check exits successfully.",
                "method_config": {"command": "true"},
            }
        ],
    )
    attach_plan_to_item(
        test_db,
        plan_id=int(plan["id"]),
        item_id=item_id,
        transition_id=TARGET_STATUS,
    )

    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=TARGET_STATUS,
        force=True,
        no_github=True,
        rebuild_board=False,
    )

    assert result["success"] is True
    count = test_db.execute(
        "SELECT COUNT(*) FROM qa_requirements "
        "WHERE item_id=%s AND workflow_transition_id=%s",
        (item_id, TARGET_STATUS),
    ).fetchone()[0]
    assert int(count) == 1


def test_workflow_drift_retries_preflight_and_honors_new_approval(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    source = _publish_approval_workflow(
        test_db,
        label="Status transition source",
        enabled=False,
    )
    item_id = 965
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    target = _publish_approval_workflow(
        test_db,
        label="Status transition approval target",
        enabled=True,
    )
    original_preflight = workflow_status_transition_preflight.prepare_status_transition
    migrated_once = False

    def migrate_after_first_preflight(conn, **kwargs):
        nonlocal migrated_once
        result = original_preflight(conn, **kwargs)
        if result.failure is None and not migrated_once:
            migrated_once = True
            migrated = migrate_item_workflow_pin(
                conn,
                item_id=item_id,
                target_version=int(target["version"]),
            )
            assert migrated["changed"] is True
        return result

    monkeypatch.setattr(
        workflow_status_transition_preflight,
        "prepare_status_transition",
        migrate_after_first_preflight,
    )
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=TARGET_STATUS,
        force=True,
        no_github=True,
        rebuild_board=False,
        originator_actor_id=_actor_id(test_db),
    )

    assert result["error_code"] == "GATE_APPROVAL_REQUIRED"
    row = test_db.execute(
        "SELECT workflow_version_id, status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()
    assert (int(row[0]), str(row[1])) == (
        int(target["version_id"]),
        "idea",
    )
    assert int(source["version_id"]) != int(target["version_id"])
    request_count = test_db.execute(
        "SELECT COUNT(*) FROM decision_requests WHERE subject_key=%s",
        (f"{item_id}:{TARGET_STATUS}",),
    ).fetchone()[0]
    assert int(request_count) == 1
