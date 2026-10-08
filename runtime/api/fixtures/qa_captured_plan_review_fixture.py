"""Seed one real frozen plan capture ready for its agent judgment."""

from __future__ import annotations

import json

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings


def captured_plan_review(conn, item_id: int):
    insert_item(
        conn,
        id=item_id,
        title="Inspect captured terminal evidence",
        workflow_id="issue",
    )
    replace_test_machine_settings(
        conn,
        project="yoke",
        settings=TEST_MACHINE_SETTINGS,
        base_settings=None,
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"inspection-{item_id}",
        name="Inspection",
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "review-frame",
                "position": 1,
                "method_id": "terminal-inspection",
                "instructions": "Inspect the final review frame.",
                "expected_outcome": "The frame summarizes the selected project.",
                "method_config": {
                    "steps": [
                        {
                            "key": "review-frame",
                            "send": "",
                            "expect": "Review",
                        }
                    ],
                    "capture_checkpoints": ["review-frame"],
                },
                "entry_surface": "public-installer",
                "required_completion": "review-frame",
                "starting_state": "as_is",
                "starting_state_reason": "review reads a recorded capture",
            }
        ],
    )
    set_project_default(
        conn,
        plan_id=int(plan["id"]),
        workflow_id="issue",
        transition_id="implemented",
    )
    materialized = materialize_for_item(
        conn,
        item_id=item_id,
        transition_id="implemented",
    )
    requirement_id = int(materialized["created_requirement_ids"][0])
    execution = begin_plan_execution(
        conn,
        item_id=item_id,
        transition_id="implemented",
        actor_id="7",
        session_id="review-session",
    )
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    snapshot = conn.execute(
        "SELECT method_config,execution_target_digest FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    now = "2026-07-29T00:00:00Z"
    capture_run_id = int(
        conn.execute(
            "INSERT INTO qa_runs("
            "qa_requirement_id,performed_by,qa_kind,case_outcome,raw_result,"
            "started_at,completed_at,created_at"
            ") VALUES(%s,'host_control','plan_case','needs_review',%s,%s,%s,%s) "
            "RETURNING id",
            (
                requirement_id,
                stamp_executed_method_config(
                    json.dumps(
                        {
                            "evidence": {
                                "steps": [
                                    {
                                        "key": "review-frame",
                                        "transcript": "Project: yoke",
                                    }
                                ]
                            }
                        }
                    ),
                    snapshot["method_config"],
                    execution_target_digest=snapshot["execution_target_digest"],
                ),
                now,
                now,
                now,
            ),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO qa_artifacts("
        "qa_run_id,artifact_type,content_type,artifact_handle,metadata,created_at"
        ") VALUES(%s,'terminal_screenshot','image/png',%s,%s,%s)",
        (
            capture_run_id,
            json.dumps({"backend": "local", "path": "/tmp/review-frame.png"}),
            json.dumps({"checkpoint": "review-frame"}),
            now,
        ),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "runner_id": "host_control",
            "verdict": None,
            "case_outcome": "needs_review",
            "run_id": capture_run_id,
        },
    )
    return execution, requirement_id, capture_run_id
