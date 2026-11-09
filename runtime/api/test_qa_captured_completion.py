"""Completion cannot replace captured evidence or bypass its linked review."""

import json
from unittest.mock import patch

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_agent_reviewed_capture_test_support import (
    browser_evidence_gate,
    capture,
    request,
    seed_case,
)
from yoke_core.domain.handlers import qa_browser_writes, qa_run
from yoke_core.domain.qa_catalog_schema import seed_builtin_qa_methods

REQUIREMENT_ID = 8401
EVIDENCE = json.dumps(
    {
        "verification_tree": {"head_sha": "a" * 40},
        "screenshots": ["/tmp/captured.png"],
        "color_scheme": "dark",
        "artifact_paths": ["/tmp/capture.json"],
    }
)


def _snapshot(conn, run_id):
    return dict(conn.execute("SELECT * FROM qa_runs WHERE id=%s", (run_id,)).fetchone())


def _artifacts(conn, run_id):
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM qa_artifacts WHERE qa_run_id=%s", (run_id,)
        ).fetchall()
    ]


def _seed_capture(conn, method_id="browser-inspection", verdict_path="agent"):
    seed_builtin_qa_methods(conn)
    seed_case(
        conn,
        requirement_id=REQUIREMENT_ID,
        method_id=method_id,
        verdict_path=verdict_path,
    )
    if method_id == "exploratory-mission":
        from yoke_core.domain.qa_run_verdict_record import insert_qa_run
        from yoke_core.domain.db_helpers import utc_now

        run_id = insert_qa_run(
            conn,
            qa_requirement_id=REQUIREMENT_ID,
            performed_by="agent_mission",
            qa_kind="method_case",
            execution_status="captured",
            case_outcome="needs_review",
            started_at=utc_now(),
            completed_at=utc_now(),
            created_at=utc_now(),
        ).run_id
    else:
        run_id = capture(conn, REQUIREMENT_ID)
    conn.execute("UPDATE qa_runs SET raw_result=%s WHERE id=%s", (EVIDENCE, run_id))
    conn.commit()
    return run_id


@pytest.mark.parametrize(
    "method_id,verdict_path",
    [
        ("browser-inspection", "automatic"),
        ("browser-check", "agent"),
        ("exploratory-mission", "agent"),
    ],
)
@pytest.mark.parametrize(
    "payload",
    [
        {"verdict": "pass"},
        {"verdict": "fail"},
        {"verdict": "pass", "raw_result": '{"summary":"done"}'},
        {"execution_status": "captured", "raw_result": ""},
        {"execution_status": "capture_failed", "raw_result": "replacement"},
    ],
)
def test_captured_agent_review_refuses_completion_without_mutation(
    method_id, verdict_path, payload
):
    with test_database() as conn:
        run_id = _seed_capture(conn, method_id, verdict_path)
        before = _snapshot(conn, run_id)
        artifacts = _artifacts(conn, run_id)
        with patch("yoke_core.domain.qa_events.emit_qa_run_event") as emit:
            result = qa_browser_writes.handle_qa_run_complete(
                request(
                    "qa.run.complete", REQUIREMENT_ID, {"run_id": run_id, **payload}
                )
            )
        assert not result.primary_success
        assert result.error.code == "qa_captured_review_required"
        assert "yoke qa run record-verdict" in result.error.message
        assert "--performed-by agent" in result.error.message
        assert _snapshot(conn, run_id) == before
        assert _artifacts(conn, run_id) == artifacts
        emit.assert_not_called()


def test_rejected_failure_leaves_capture_reviewable_with_its_evidence():
    with test_database() as conn:
        run_id = _seed_capture(conn)
        with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
            refused = qa_browser_writes.handle_qa_run_complete(
                request(
                    "qa.run.complete",
                    REQUIREMENT_ID,
                    {"run_id": run_id, "verdict": "fail"},
                )
            )
            assert not refused.primary_success
            reviewed = qa_run.handle_qa_run_record_verdict(
                request(
                    "qa.run.record_verdict",
                    REQUIREMENT_ID,
                    {
                        "performed_by": "agent",
                        "verdict": "pass",
                        "verdict_reason": "Read the preserved screenshot",
                    },
                )
            )
        assert reviewed.primary_success, reviewed.error
        reviewed_evidence = json.loads(_snapshot(conn, run_id)["raw_result"])
        for key, value in json.loads(EVIDENCE).items():
            assert reviewed_evidence[key] == value
        assert (
            conn.execute(
                "SELECT capture_run_id FROM qa_plan_review_verdicts "
                "WHERE requirement_id=%s",
                (REQUIREMENT_ID,),
            ).fetchone()["capture_run_id"]
            == run_id
        )
        assert browser_evidence_gate(conn) is None


def test_automatic_capture_can_complete_with_verdict_and_result():
    with test_database() as conn:
        run_id = _seed_capture(conn, "browser-check", "automatic")
        with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
            result = qa_browser_writes.handle_qa_run_complete(
                request(
                    "qa.run.complete",
                    REQUIREMENT_ID,
                    {"run_id": run_id, "verdict": "pass", "raw_result": "finished"},
                )
            )
        assert result.primary_success, result.error
        row = _snapshot(conn, run_id)
        assert row["verdict"] == "pass"
        assert json.loads(row["raw_result"]) == {
            "evidence": "finished",
            "verification_tree": {"head_sha": "a" * 40},
        }
