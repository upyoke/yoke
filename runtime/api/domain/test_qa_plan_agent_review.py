"""Batched agent inspection and human-escalation invariants."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    TEST_MACHINE_SETTINGS,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_review import (
    QaPlanReviewError,
    begin_plan_review,
)
from yoke_core.domain.qa_plan_review_submission import submit_plan_review
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings


def _review_execution(conn, item_id: int):
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


def test_bundle_is_immutable_complete_and_does_not_ask_a_human() -> None:
    with test_database() as conn:
        execution, requirement_id, capture_run_id = _review_execution(conn, 4501)
        bundle = begin_plan_review(conn, execution)
        assert bundle is not None
        assert execution["state"] == "awaiting_agent_review"
        assert bundle["dispatch"]["subagent_type"] == "yoke-tester"
        assert bundle["execution_target"] == execution["execution_target"]
        assert bundle["execution_target_digest"] == execution["execution_target_digest"]
        assert bundle["dispatch"]["authority"] == {
            "state": "bound",
            "environment": execution["execution_target"]["environment"]["name"],
            "execution_target_digest": execution["execution_target_digest"],
        }
        assert bundle["dispatch"]["artifact_read_commands"] == [
            "yoke qa artifact read "
            f"--requirement-id {requirement_id} "
            f"--artifact-id {bundle['cases'][0]['artifacts'][0]['id']}"
        ]
        assert bundle["cases"] == [
            {
                "requirement_id": requirement_id,
                "plan_id": bundle["cases"][0]["plan_id"],
                "case_key": "review-frame",
                "case_position": 1,
                "baseline_position": 1,
                    "host_baseline": None,
                    "method_id": "terminal-inspection",
                    "runner_id": "host_control",
                    "method_config": bundle["cases"][0]["method_config"],
                    "executor": None,
                    "instructions": "Inspect the final review frame.",
                "expected_outcome": "The frame summarizes the selected project.",
                "capture_run_id": capture_run_id,
                "capture_runner": "host_control",
                "capture_degraded_reason": None,
                "transcript": {
                    "evidence": {
                        "steps": [
                            {
                                "key": "review-frame",
                                "transcript": "Project: yoke",
                            }
                        ]
                    }
                },
                "artifacts": [
                    {
                        "id": bundle["cases"][0]["artifacts"][0]["id"],
                        "artifact_type": "terminal_screenshot",
                        "content_type": "image/png",
                        "artifact_handle": json.dumps(
                            {
                                "backend": "local",
                                "path": "/tmp/review-frame.png",
                            }
                        ),
                        "metadata": {"checkpoint": "review-frame"},
                    }
                ],
                "qa_kind": "plan_case",
            }
        ]
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM decision_requests "
                "WHERE kind='qa_needs_review' AND subject_key=%s",
                (str(requirement_id),),
            ).fetchone()[0]
            == 0
        )
        replay = begin_plan_review(conn, execution)
        assert replay["bundle_digest"] == bundle["bundle_digest"]


def test_bundle_uses_this_execution_capture_not_latest_requirement_run() -> None:
    with test_database() as conn:
        execution, requirement_id, capture_run_id = _review_execution(conn, 4502)
        now = "2026-07-29T00:01:00Z"
        later_run_id = int(
            conn.execute(
                "INSERT INTO qa_runs("
                "qa_requirement_id,performed_by,qa_kind,case_outcome,raw_result,"
                "started_at,completed_at,created_at"
                ") VALUES(%s,'host_control','plan_case','needs_review',%s,%s,%s,%s) "
                "RETURNING id",
                (
                    requirement_id,
                    json.dumps({"evidence": {"transcript": "unrelated rerun"}}),
                    now,
                    now,
                    now,
                ),
            ).fetchone()[0]
        )
        assert later_run_id > capture_run_id

        bundle = begin_plan_review(conn, execution)

        assert bundle is not None
        assert bundle["cases"][0]["capture_run_id"] == capture_run_id
        assert "unrelated rerun" not in json.dumps(bundle["cases"][0]["transcript"])


@pytest.mark.parametrize(
    ("verdict", "expected_state", "review_state", "request_count"),
    (
        ("pass", "passed", "agent_reviewed", 0),
        ("fail", "failed", "agent_reviewed", 0),
        ("undetermined", "needs_review", "human_review_requested", 1),
    ),
)
def test_agent_verdict_is_per_case_and_only_undetermined_escalates(
    verdict: str,
    expected_state: str,
    review_state: str,
    request_count: int,
) -> None:
    with test_database() as conn:
        execution, requirement_id, _capture_run_id = _review_execution(
            conn,
            4510 + request_count + (1 if verdict == "fail" else 0),
        )
        bundle = begin_plan_review(conn, execution)
        result = submit_plan_review(
            conn,
            execution,
            bundle_id=bundle["bundle_id"],
            bundle_digest=bundle["bundle_digest"],
            verdicts=[
                {
                    "requirement_id": requirement_id,
                    "verdict": verdict,
                    "rationale": f"Recorded {verdict} from the supplied evidence.",
                }
            ],
            reviewer_actor_id=None,
            reviewer_session_id="review-session",
        )
        assert result["state"] == expected_state
        assert execution["state"] == "completed"
        run = conn.execute(
            "SELECT performed_by,verdict,verdict_reason,raw_result "
            "FROM qa_runs WHERE id=%s",
            (result["verdicts"][0]["review_run_id"],),
        ).fetchone()
        assert (run["performed_by"], run["verdict"]) == ("agent", verdict)
        assert (
            run["verdict_reason"] == f"Recorded {verdict} from the supplied evidence."
        )
        assert "rationale" in json.loads(run["raw_result"])
        plan_id = int(
            conn.execute(
                "SELECT plan_id FROM qa_requirements WHERE id=%s",
                (requirement_id,),
            ).fetchone()[0]
        )
        proof = get_plan(conn, plan_id=plan_id)["cases"][0]["last_result"]
        assert proof["review"]["state"] == review_state
        assert proof["review"]["capture_run_id"] is not None
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM decision_requests "
                "WHERE kind='qa_needs_review' AND subject_key=%s",
                (str(requirement_id),),
            ).fetchone()[0]
            == request_count
        )


def test_submission_refuses_partial_or_changed_batches() -> None:
    with test_database() as conn:
        execution, requirement_id, _capture_run_id = _review_execution(conn, 4520)
        bundle = begin_plan_review(conn, execution)
        with pytest.raises(QaPlanReviewError, match="exactly one"):
            submit_plan_review(
                conn,
                execution,
                bundle_id=bundle["bundle_id"],
                bundle_digest=bundle["bundle_digest"],
                verdicts=[],
                reviewer_actor_id="7",
                reviewer_session_id="review-session",
            )
        assert requirement_id > 0
