"""A bound standalone case still captures, reviews, and satisfies the gate."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

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
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
)
from yoke_core.domain.qa_requirement_config_update import apply_requirement_update
from yoke_core.domain.qa_requirement_pass_currency import (
    has_current_passing_run,
    recorded_execution_target_digest,
    stamp_executed_method_config,
)
from yoke_core.domain.qa_review_requests import apply_qa_review_resolution


_BROWSER_STEPS = [
    {"action": "navigate", "route": "/"},
    {"action": "screenshot", "capture": True},
]


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
                    conn, 6409, workflow_transition_id=TRANSITION
                ),
            )
        )
        assert outcome.primary_success, outcome.error
        req_id = int(outcome.result_payload["requirement_id"])
        with pytest.raises(QaPlanExecutionStateError, match="requirement"):
            begin_plan_execution(
                conn,
                item_id=6409,
                transition_id=TRANSITION,
                actor_id="7",
                session_id="standalone-unbound",
            )
        bound = apply_requirement_update(conn, req_id, "target_env", "local")
        assert bound.ok, bound.message
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
                    payload={"run_id": capture_id, "execution_status": "captured",
                             "capture_degraded_reason": "fixture_no_shot"},
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
        requirement = conn.execute(
            "SELECT method_config, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (req_id,),
        ).fetchone()
        review_id = conn.execute(
            "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, "
            "verdict, case_outcome, raw_result, started_at, completed_at, "
            "created_at) VALUES (%s, 'agent', 'method_case', 'pass', 'passed', "
            "%s, %s, %s, %s) RETURNING id",
            (
                req_id,
                stamp_executed_method_config(
                    None,
                    requirement["method_config"],
                    execution_target_digest=requirement["execution_target_digest"],
                ),
                now,
                now,
                now,
            ),
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
        assert has_current_passing_run(conn, req_id)
        gate = check_browser_evidence_present(
            conn,
            where="r.item_id = %s",
            params=(6409,),
            name="browser-evidence",
            transition_name="done",
        )
        assert gate is None


def test_recorded_green_on_target_a_does_not_satisfy_target_b() -> None:
    config = {"base_url": PREVIEW_URL, "steps": _BROWSER_STEPS}
    with test_database() as conn:
        insert_item(conn, id=6410, title="Retarget after green", status="implementing")
        _environment(conn, project_id=1, name="local", url=PREVIEW_URL)
        _environment(conn, project_id=1, name="preview", url="http://127.0.0.1:8932")
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(6410, _bound_browser_payload(conn, 6410, target_env="local"))
        )
        assert outcome.primary_success, outcome.error
        req_id = int(outcome.result_payload["requirement_id"])
        digest_a = conn.execute(
            "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
            (req_id,),
        ).fetchone()["execution_target_digest"]
        conn.execute(
            "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, "
            "verdict, raw_result, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                req_id,
                "browser_substrate",
                "method_case",
                "pass",
                stamp_executed_method_config(
                    "{}", config, execution_target_digest=digest_a
                ),
                "2026-09-17T00:00:00Z",
            ),
        )
        conn.commit()
        assert has_current_passing_run(conn, req_id)
        result = apply_requirement_update(conn, req_id, "target_env", "preview")
        assert result.ok, result.message
        assert not has_current_passing_run(conn, req_id)
        assert int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM qa_runs WHERE qa_requirement_id=%s",
                (req_id,),
            ).fetchone()["n"]
        ) == 1
        digest_b = conn.execute(
            "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
            (req_id,),
        ).fetchone()["execution_target_digest"]
        assert digest_b != digest_a
        conn.execute(
            "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, "
            "verdict, raw_result, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                req_id,
                "browser_substrate",
                "method_case",
                "pass",
                stamp_executed_method_config(
                    "{}", config, execution_target_digest=digest_b
                ),
                "2026-09-17T00:00:01Z",
            ),
        )
        conn.commit()
        assert has_current_passing_run(conn, req_id)
        assert int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM qa_runs WHERE qa_requirement_id=%s",
                (req_id,),
            ).fetchone()["n"]
        ) == 2


def test_approving_pending_review_keeps_capture_target_not_live() -> None:
    config = {"base_url": PREVIEW_URL, "steps": _BROWSER_STEPS}
    with test_database() as conn:
        insert_item(conn, id=6411, title="Stale human review", status="implementing")
        _environment(conn, project_id=1, name="local", url=PREVIEW_URL)
        _environment(conn, project_id=1, name="preview", url="http://127.0.0.1:8932")
        outcome = qa_requirement_create.handle_qa_requirement_add(
            _request(6411, _bound_browser_payload(conn, 6411, target_env="local"))
        )
        assert outcome.primary_success, outcome.error
        req_id = int(outcome.result_payload["requirement_id"])
        digest_a = conn.execute(
            "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
            (req_id,),
        ).fetchone()["execution_target_digest"]
        capture_id = conn.execute(
            "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, "
            "verdict, verdict_reason, raw_result, created_at) VALUES "
            "(%s, 'browser_substrate', 'method_case', 'undetermined', "
            "'needs human review of the capture', %s, %s) RETURNING id",
            (
                req_id,
                stamp_executed_method_config(
                    "{}", config, execution_target_digest=digest_a
                ),
                "2026-09-17T00:00:00Z",
            ),
        ).fetchone()["id"]
        conn.commit()
        result = apply_requirement_update(conn, req_id, "target_env", "preview")
        assert result.ok, result.message
        digest_b = conn.execute(
            "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
            (req_id,),
        ).fetchone()["execution_target_digest"]
        assert digest_b != digest_a
        apply_qa_review_resolution(
            conn,
            requirement_id=req_id,
            action="approve",
            actor_id=1,
            note="Looks good against the captured preview.",
            reviewed_run_id=int(capture_id),
        )
        human = conn.execute(
            "SELECT raw_result FROM qa_runs WHERE qa_requirement_id=%s "
            "AND performed_by='human_review'",
            (req_id,),
        ).fetchone()
        assert recorded_execution_target_digest(human["raw_result"]) == digest_a
        assert not has_current_passing_run(conn, req_id)
        assert int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM qa_runs WHERE qa_requirement_id=%s",
                (req_id,),
            ).fetchone()["n"]
        ) == 2

