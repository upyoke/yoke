"""A bound standalone case still captures, reviews, and satisfies the gate."""

from __future__ import annotations

import json
from unittest.mock import patch

from runtime.api.domain.test_standalone_requirement_execution_target import (
    PREVIEW_URL,
    TRANSITION,
    _bound_browser_payload,
    _environment,
    _request,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers import qa_browser_writes, qa_requirement_create
from yoke_core.domain.qa_browser_evidence_check import check_browser_evidence_present
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update


def test_update_to_unregistered_name_clears_snapshot() -> None:
    with test_database() as conn:
        insert_item(conn, id=6408, title="Rebind to draft", status="implementing")
        _environment(conn, project_id=1, name="local", url=PREVIEW_URL)
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                6408,
                _bound_browser_payload(conn, 6408, target_env="local"),
            )
        )
        assert outcome.primary_success, outcome.error
        req_id = int(outcome.result_payload["requirement_id"])
        result = apply_requirement_update(conn, req_id, "target_env", "later")
        assert result.ok, result.message
        row = conn.execute(
            "SELECT target_env, execution_target_json, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (req_id,),
        ).fetchone()
        assert row["target_env"] == "later"
        assert row["execution_target_json"] is None
        assert row["execution_target_digest"] is None


def test_bound_item_case_reaches_gate_after_linked_review() -> None:
    now = "2026-09-17T00:00:00Z"
    with test_database() as conn:
        insert_item(conn, id=6409, title="Bound then reviewed", workflow_id="issue")
        _environment(conn, project_id=1, name="local", url=PREVIEW_URL)
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(
                6409,
                _bound_browser_payload(
                    conn,
                    6409,
                    target_env="local",
                    workflow_transition_id=TRANSITION,
                ),
            )
        )
        assert outcome.primary_success, outcome.error
        req_id = int(outcome.result_payload["requirement_id"])
        execution = begin_plan_execution(
            conn,
            item_id=6409,
            transition_id=TRANSITION,
            actor_id="7",
            session_id="standalone-gate",
        )
        assert execution["execution_target"]["environment"] == {"name": "local"}
        with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
            added = qa_browser_writes.handle_qa_run_add(
                FunctionCallRequest(
                    function="qa.run.add",
                    actor=ActorContext(actor_id="op", session_id="s-1"),
                    target=TargetRef(kind="qa_requirement", qa_requirement_id=req_id),
                    payload={"performed_by": "browser_substrate"},
                )
            )
            assert added.primary_success, added.error
            capture_id = int(added.result_payload["qa_run_id"])
            completed = qa_browser_writes.handle_qa_run_complete(
                FunctionCallRequest(
                    function="qa.run.complete",
                    actor=ActorContext(actor_id="op", session_id="s-1"),
                    target=TargetRef(kind="qa_requirement", qa_requirement_id=req_id),
                    payload={"run_id": capture_id, "execution_status": "captured"},
                )
            )
            assert completed.primary_success, completed.error
        conn.execute(
            "INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, "
            "artifact_handle, created_at) VALUES (%s, 'browser_screenshot', "
            "'image/png', %s, %s)",
            (
                capture_id,
                json.dumps({"backend": "local", "path": "/tmp/shot.png"}),
                now,
            ),
        )
        review_id = conn.execute(
            "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, "
            "verdict, case_outcome, started_at, completed_at, created_at) "
            "VALUES (%s, 'agent', 'method_case', 'pass', 'passed', %s, %s, %s) "
            "RETURNING id",
            (req_id, now, now, now),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO qa_plan_review_bundles (id, execution_id, roster_digest, "
            "bundle_digest, bundle_json, state, created_at) VALUES "
            "(%s, %s, 'd', 'digest', '{}', 'completed', %s)",
            ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", execution["id"], now),
        )
        conn.execute(
            "INSERT INTO qa_plan_review_verdicts (bundle_id, requirement_id, "
            "capture_run_id, review_run_id, verdict, rationale, created_at) "
            "VALUES (%s, %s, %s, %s, 'pass', 'read the capture', %s)",
            (
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                req_id,
                capture_id,
                int(review_id),
                now,
            ),
        )
        conn.commit()
        gate = check_browser_evidence_present(
            conn,
            where="r.item_id = %s",
            params=(6409,),
            name="browser-evidence",
            transition_name="done",
        )
        assert gate is None
