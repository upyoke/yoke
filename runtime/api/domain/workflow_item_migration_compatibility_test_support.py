# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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

from yoke_core.domain.approval_policy import ApprovalPolicy

from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.decision_request_subject_context import (
    APPROVAL_SOURCE_WORKFLOW_DEFAULT,
)

from yoke_core.domain.qa_plan_management import create_plan

from yoke_core.domain.workflow_definition_builders import with_generated_epic_tasks

from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError

from yoke_core.domain.workflow_item_versioning import migrate_item_workflow_pin

from yoke_core.domain.workflow_registry import publish_workflow_version

from yoke_core.domain.work_claim_targets import make_epic_task_target, make_item_target

ITEM_ID = 948


def _stage(definition: dict, stage_id: str) -> dict:
    return next(stage for stage in definition["stages"] if stage["id"] == stage_id)


def _mutate_target(definition: dict, case: str) -> None:
    policies = definition["policies"]
    if case == "work_claim":
        policies["ownership"] = "exclusive_session_work_claim"
    elif case == "path_claim":
        policies["path_claims"] = "required_per_task"
        with_generated_epic_tasks(definition)
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
    elif case == "delivery_skill":
        definition["skill_bindings"][-1]["skill_id"] = "polish"
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
        "reviewing-implementation": {"roles": ["owner"], "actors": []}
    }
    source = publish_workflow_version(
        test_db, workflow_id="issue", definition=source_definition
    )
    insert_item(test_db, id=ITEM_ID, workflow_id="issue", status="implementing")

    target_definition = deepcopy(source_definition)
    target_definition["stages"][0]["label"] = "Migration target"
    if case:
        _mutate_target(target_definition, case)
    target = publish_workflow_version(
        test_db, workflow_id="issue", definition=target_definition
    )
    _seed_path_claim(test_db)
    return source, target


def _item_project_id(test_db) -> int:
    return int(
        test_db.execute(
            "SELECT project_id FROM items WHERE id = %s", (ITEM_ID,)
        ).fetchone()[0]
    )


def _seed_work_claim(test_db) -> None:
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_level, workspace, "
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
        "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, last_heartbeat, reason) VALUES (%s, 'item', %s, %s, %s, %s)",
        (
            "migration-session",
            make_item_target(ITEM_ID).scope_json(),
            now,
            now,
            "migration fixture",
        ),
    )
    test_db.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, last_heartbeat, reason) VALUES (%s, 'epic_task', %s, %s, %s, %s)",
        (
            "migration-session",
            make_epic_task_target(ITEM_ID, 1).scope_json(),
            now,
            now,
            "task migration fixture",
        ),
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
        "state, mode, owner_kind, owner_item_id, registered_by_actor_id, "
        "integration_target, registered_at, exception_reason"
        ") VALUES ('active', 'exception', 'item', %s, %s, 'main', %s, %s)",
        (ITEM_ID, actor_id, iso8601_now(), "migration compatibility fixture"),
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
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) VALUES (%s, %s, %s)",
        (run["id"], ITEM_ID, now),
    )
    test_db.commit()


def _pin(test_db) -> tuple[int, str]:
    row = test_db.execute(
        "SELECT workflow_version_id, status FROM items WHERE id = %s", (ITEM_ID,)
    ).fetchone()
    return int(row[0]), str(row[1])
