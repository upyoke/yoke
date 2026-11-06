from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_human_reviewer

from runtime.api.domain.workflow_item_migration_compatibility_test_support import (
    ITEM_ID as ITEM_ID,
    _item_project_id as _item_project_id,
    _mutate_target as _mutate_target,
    _pin as _pin,
    _publish_pair as _publish_pair,
    _seed_delivery as _seed_delivery,
    _seed_path_claim as _seed_path_claim,
    _seed_work_claim as _seed_work_claim,
    _stage as _stage,
)


import pytest

from runtime.api.fixtures.backlog import (
    insert_item_worktree,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.approval_gate import evaluate_lifecycle_approval
from yoke_core.domain.approval_policy import ApprovalPolicy
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_subject_context import (
    APPROVAL_SOURCE_WORKFLOW_DEFAULT,
)
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_versioning import migrate_item_workflow_pin
from yoke_core.domain.work_claim_targets import make_epic_task_target, make_item_target


def _seed_approval(test_db) -> None:
    seed_human_reviewer(test_db, _item_project_id(test_db))
    verdict = evaluate_lifecycle_approval(
        test_db,
        item_id=ITEM_ID,
        to_stage_id="reviewing-implementation",
        policy=ApprovalPolicy(roles=("owner",)),
        approval_source={
            "kind": APPROVAL_SOURCE_WORKFLOW_DEFAULT,
            "entry": "approval_defaults.reviewing-implementation",
        },
    )
    assert verdict.request_status == "pending"
    test_db.execute(
        "UPDATE decision_requests SET status = 'resolved', resolution_action = 'approve', resolved_at = %s WHERE id = %s",
        (iso8601_now(), verdict.request_id),
    )
    test_db.commit()


def _seed_qa(test_db) -> None:
    plan = create_plan(
        test_db,
        project="yoke",
        slug="migration-compatibility",
        name="Migration compatibility",
    )
    requirement = insert_qa_requirement(
        test_db, item_id=ITEM_ID, workflow_transition_id="reviewed-implementation"
    )
    insert_qa_run(test_db, qa_requirement_id=int(requirement["id"]))
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments (item_id, transition_id, plan_id, attached_at) VALUES (%s, %s, %s, %s)",
        (ITEM_ID, "reviewed-implementation", plan["id"], now),
    )
    test_db.execute(
        "INSERT INTO qa_plan_executions ("
        "id, item_id, transition_id, session_id, roster_digest, roster_json, "
        "state, created_at, heartbeat_at"
        ") VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s)",
        (
            "qa-execution-migration",
            ITEM_ID,
            "reviewed-implementation",
            "migration-session",
            "digest",
            "[]",
            now,
            now,
        ),
    )
    test_db.commit()


def _seed_case(test_db, case: str) -> None:
    if case == "work_claim":
        _seed_work_claim(test_db)
    elif case == "worktree":
        insert_item_worktree(test_db, item_id=ITEM_ID, branch="codex/migration-fixture")
    elif case == "approval":
        _seed_approval(test_db)
    elif case == "qa":
        _seed_qa(test_db)
    elif case in {"delivery", "delivery_skill"}:
        _seed_delivery(test_db)
    elif case == "posture":
        test_db.execute(
            "UPDATE items SET workflow_posture = %s WHERE id = %s",
            ('{"deployment": true}', ITEM_ID),
        )
        test_db.commit()


def test_label_only_migration_preserves_all_live_bindings(test_db):
    source, target = _publish_pair(test_db)
    _seed_work_claim(test_db)
    insert_item_worktree(test_db, item_id=ITEM_ID, branch="codex/migration-compatible")
    _seed_approval(test_db)
    _seed_qa(test_db)
    _seed_delivery(test_db)

    result = migrate_item_workflow_pin(
        test_db, item_id=ITEM_ID, target_version=int(target["version"])
    )

    assert result["changed"] is True
    assert result["before"]["workflow_version_id"] == source["version_id"]
    assert result["after"]["workflow_version_id"] == target["version_id"]
    assert result["after"]["status"] == "implementing"
    item_target = make_item_target(ITEM_ID)
    task_target = make_epic_task_target(ITEM_ID, 1)
    counts = test_db.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM work_claims "
        " WHERE (target_kind = %s AND scope = %s) "
        " OR (target_kind = %s AND scope = %s)), "
        "(SELECT COUNT(*) FROM path_claims WHERE owner_item_id = %s), "
        "(SELECT COUNT(*) FROM item_worktrees WHERE item_id = %s), "
        "(SELECT COUNT(*) FROM decision_requests "
        " WHERE subject_key LIKE %s), "
        "(SELECT COUNT(*) FROM qa_requirements WHERE item_id = %s), "
        "(SELECT COUNT(*) FROM qa_plan_item_attachments WHERE item_id = %s), "
        "(SELECT COUNT(*) FROM qa_plan_executions WHERE item_id = %s), "
        "(SELECT COUNT(*) FROM deployment_run_items WHERE item_id = %s)",
        (
            item_target.kind,
            item_target.scope_json(),
            task_target.kind,
            task_target.scope_json(),
            ITEM_ID,
            ITEM_ID,
            f"{ITEM_ID}:%",
            ITEM_ID,
            ITEM_ID,
            ITEM_ID,
            ITEM_ID,
        ),
    ).fetchone()
    assert tuple(int(value) for value in counts) == (2, 1, 1, 1, 1, 1, 1, 1)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("work_claim", "live work claims"),
        ("path_claim", "live path claims"),
        ("worktree", "active worktree lanes"),
        ("approval", "approval authority"),
        ("qa", "QA gate semantics changed"),
        ("delivery", "live delivery bindings"),
        ("delivery_skill", "delivery skill stages"),
        ("posture", "disallows item posture keys"),
    ),
)
def test_incompatible_live_state_rejects_migration_atomically(
    test_db, case: str, message: str
):
    _source, target = _publish_pair(test_db, case=case)
    _seed_case(test_db, case)
    before = _pin(test_db)

    with pytest.raises(WorkflowRegistryError, match=message):
        migrate_item_workflow_pin(
            test_db, item_id=ITEM_ID, target_version=int(target["version"])
        )

    assert _pin(test_db) == before
