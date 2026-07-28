from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.fixtures.backlog import (
    insert_deployment_run,
    insert_item,
    insert_item_worktree,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.approval_gate import evaluate_lifecycle_approval
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)
from yoke_core.domain.workflow_registry import publish_workflow_version


ITEM_ID = 948


def _stage(definition: dict, stage_id: str) -> dict:
    return next(stage for stage in definition["stages"] if stage["id"] == stage_id)


def _mutate_target(definition: dict, case: str) -> None:
    policies = definition["policies"]
    if case == "work_claim":
        policies["ownership"] = "exclusive_session_work_claim"
    elif case == "path_claim":
        policies["path_claims"] = "required_per_task"
    elif case == "worktree":
        policies["worktrees"] = "worker_and_integration_lanes"
    elif case == "approval":
        policies["approval_defaults"]["reviewing-implementation"] = {
            "roles": ["operator"],
            "actors": [],
        }
    elif case == "qa":
        stage = _stage(definition, "reviewed-implementation")
        stage["gates"] = [
            gate for gate in stage["gates"] if gate["id"] != "qa_verification"
        ]
    elif case == "delivery":
        policies["delivery"] = "after_merge_action"
    elif case == "delivery_executor":
        definition["executor_bindings"][-1]["executor_id"] = "polish"
    elif case == "posture":
        policies["item_posture_allowlist"].remove("deployment")
    elif case == "reached_approval":
        policies["approval_defaults"]["implementing"] = {
            "roles": ["owner"],
            "actors": [],
        }
        _stage(definition, "implementing")["gates"].append({"id": "approval"})
    elif case == "reached_qa":
        _stage(definition, "implementing")["gates"].append({"id": "qa_verification"})


def _publish_pair(test_db, *, case: str = "") -> tuple[dict, dict]:
    source_definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    source_definition["stages"][0]["label"] = "Migration candidate"
    source_definition["policies"]["approval_defaults"] = {
        "reviewing-implementation": {
            "roles": ["owner"],
            "actors": [],
        }
    }
    source = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=source_definition,
    )
    insert_item(
        test_db,
        id=ITEM_ID,
        workflow_id="issue",
        status="implementing",
    )

    target_definition = deepcopy(source_definition)
    target_definition["stages"][0]["label"] = "Migration target"
    if case:
        _mutate_target(target_definition, case)
    target = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=target_definition,
    )
    return source, target


def _item_project_id(test_db) -> int:
    return int(
        test_db.execute(
            "SELECT project_id FROM items WHERE id = %s",
            (ITEM_ID,),
        ).fetchone()[0]
    )


def _seed_work_claim(test_db) -> None:
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, offered_at, last_heartbeat"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "migration-session",
            "codex",
            "openai",
            "test-model",
            "primary",
            "/tmp/migration",
            _item_project_id(test_db),
            now,
            now,
        ),
    )
    test_db.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, item_id, claimed_at, last_heartbeat, reason"
        ") VALUES (%s, 'item', %s, %s, %s, %s)",
        ("migration-session", ITEM_ID, now, now, "migration fixture"),
    )
    test_db.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, epic_id, task_num, claimed_at, "
        "last_heartbeat, reason"
        ") VALUES (%s, 'epic_task', %s, 1, %s, %s, %s)",
        ("migration-session", ITEM_ID, now, now, "task migration fixture"),
    )
    test_db.commit()


def _seed_path_claim(test_db) -> None:
    actor_id = int(
        test_db.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO path_claims ("
        "state, mode, actor_id, item_id, owner_kind, owner_item_id, "
        "integration_target, registered_at"
        ") VALUES ('active', 'exclusive', %s, %s, 'item', %s, 'main', %s)",
        (actor_id, ITEM_ID, ITEM_ID, iso8601_now()),
    )
    test_db.commit()


def _seed_approval(test_db) -> None:
    verdict = evaluate_lifecycle_approval(
        test_db,
        item_id=ITEM_ID,
        to_stage_id="reviewing-implementation",
        role_names=("owner",),
    )
    assert verdict.request_status == "pending"
    test_db.execute(
        "UPDATE decision_requests SET status = 'resolved', "
        "resolution_action = 'approve', resolved_at = %s WHERE id = %s",
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
        test_db,
        item_id=ITEM_ID,
        workflow_transition_id="reviewed-implementation",
    )
    insert_qa_run(test_db, qa_requirement_id=int(requirement["id"]))
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments ("
        "item_id, transition_id, plan_id, attached_at"
        ") VALUES (%s, %s, %s, %s)",
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


def _seed_delivery(test_db) -> None:
    run = insert_deployment_run(
        test_db,
        id="run-migration",
        flow="flow-migration",
        status="executing",
        current_stage="deploy",
    )
    now = iso8601_now()
    test_db.execute(
        "UPDATE items SET deployment_flow = %s WHERE id = %s",
        ("flow-migration", ITEM_ID),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
        "VALUES (%s, %s, %s)",
        (run["id"], ITEM_ID, now),
    )
    test_db.commit()


def _seed_case(test_db, case: str) -> None:
    if case == "work_claim":
        _seed_work_claim(test_db)
    elif case == "path_claim":
        _seed_path_claim(test_db)
    elif case == "worktree":
        insert_item_worktree(
            test_db,
            item_id=ITEM_ID,
            branch="codex/migration-fixture",
        )
    elif case == "approval":
        _seed_approval(test_db)
    elif case == "qa":
        _seed_qa(test_db)
    elif case in {"delivery", "delivery_executor"}:
        _seed_delivery(test_db)
    elif case == "posture":
        test_db.execute(
            "UPDATE items SET workflow_posture = %s WHERE id = %s",
            ('{"deployment": true}', ITEM_ID),
        )
        test_db.commit()


def _pin(test_db) -> tuple[int, str]:
    row = test_db.execute(
        "SELECT workflow_version_id, status FROM items WHERE id = %s",
        (ITEM_ID,),
    ).fetchone()
    return int(row[0]), str(row[1])


def test_label_only_migration_preserves_all_live_bindings(test_db):
    source, target = _publish_pair(test_db)
    _seed_work_claim(test_db)
    _seed_path_claim(test_db)
    insert_item_worktree(
        test_db,
        item_id=ITEM_ID,
        branch="codex/migration-compatible",
    )
    _seed_approval(test_db)
    _seed_qa(test_db)
    _seed_delivery(test_db)

    result = migrate_item_workflow_pin(
        test_db,
        item_id=ITEM_ID,
        target_version=int(target["version"]),
    )

    assert result["changed"] is True
    assert result["before"]["workflow_version_id"] == source["version_id"]
    assert result["after"]["workflow_version_id"] == target["version_id"]
    assert result["after"]["status"] == "implementing"
    counts = test_db.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM work_claims "
        " WHERE item_id = %s OR epic_id = %s), "
        "(SELECT COUNT(*) FROM path_claims WHERE owner_item_id = %s), "
        "(SELECT COUNT(*) FROM item_worktrees WHERE item_id = %s), "
        "(SELECT COUNT(*) FROM decision_requests "
        " WHERE subject_key LIKE %s), "
        "(SELECT COUNT(*) FROM qa_requirements WHERE item_id = %s), "
        "(SELECT COUNT(*) FROM qa_plan_item_attachments WHERE item_id = %s), "
        "(SELECT COUNT(*) FROM qa_plan_executions WHERE item_id = %s), "
        "(SELECT COUNT(*) FROM deployment_run_items WHERE item_id = %s)",
        (
            ITEM_ID,
            ITEM_ID,
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
        ("delivery_executor", "delivery executor stages"),
        ("posture", "disallows item posture keys"),
    ),
)
def test_incompatible_live_state_rejects_migration_atomically(
    test_db,
    case: str,
    message: str,
):
    _source, target = _publish_pair(test_db, case=case)
    _seed_case(test_db, case)
    before = _pin(test_db)

    with pytest.raises(WorkflowRegistryError, match=message):
        migrate_item_workflow_pin(
            test_db,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )

    assert _pin(test_db) == before
