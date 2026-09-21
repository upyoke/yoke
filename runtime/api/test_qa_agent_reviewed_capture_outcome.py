"""An agent-reviewed capture records the outcome its release gate looks for.

A Browser inspection is captured undecided on purpose: the substrate records
what it saw and a reviewer supplies the verdict afterwards. The release proof
gate pairs the two by matching a capture that is ``captured`` and
``needs_review`` against its own linked review verdict — but nothing wrote
that outcome, so the pairing could never be made and a fully reviewed Browser
case was refused as having no linked substrate-and-verdict proof.

These tests drive the real ``qa.run.complete`` handler and then the real
gate, so producer and gate are exercised against each other rather than
against a restatement of either. The linkage between them is written here
directly, because the subject is what the producer records and what the
gate then accepts. That real submission preserves this shape is the
subject of ``test_qa_capture_settlement``'s
``test_review_submission_settles_the_capture_run_in_place``, which drives
``begin_plan_review`` and a passing submission and asserts the same two
columns survive it.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_browser_writes, qa_run
from yoke_core.domain.qa_browser_evidence_check import (
    check_browser_evidence_present,
)

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database

ITEM_ID = 8301
NOW = "2026-09-17T00:00:00Z"


def _request(function_id: str, requirement_id: int, payload: dict):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload=payload,
    )


def _seed_case(conn, *, requirement_id: int, method_id: str, verdict_path: str):
    insert_item(conn, id=ITEM_ID, title="Reviewed by an agent")
    insert_qa_requirement(
        conn,
        id=requirement_id,
        item_id=ITEM_ID,
        qa_kind="method_case",
        qa_phase="verification",
        blocking_mode="blocking",
        method_id=method_id,
        method_name="Browser inspection",
        runner_id="browser_substrate",
        verdict_path=verdict_path,
        success_policy="",
    )
    conn.commit()


def _capture(conn, requirement_id: int) -> int:
    """Record a capture exactly as the browser substrate does."""
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        added = qa_browser_writes.handle_qa_run_add(
            _request(
                "qa.run.add", requirement_id, {"performed_by": "browser_substrate"}
            )
        )
        assert added.primary_success, added.error
        run_id = int(added.result_payload["qa_run_id"])
        conn.execute(
            "INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, "
            "artifact_handle, created_at) VALUES (%s, 'browser_screenshot', "
            "'image/png', %s, %s)",
            (
                run_id,
                json.dumps({"backend": "local", "path": "/tmp/shot.png"}),
                NOW,
            ),
        )
        conn.commit()
        completed = qa_browser_writes.handle_qa_run_complete(
            _request(
                "qa.run.complete",
                requirement_id,
                {"run_id": run_id, "execution_status": "captured"},
            )
        )
        assert completed.primary_success, completed.error
    return run_id


def _outcome(conn, run_id: int):
    row = conn.execute(
        "SELECT execution_status, case_outcome, verdict FROM qa_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    return row["execution_status"], row["case_outcome"], row["verdict"]


def _link_passing_review(conn, *, requirement_id: int, capture_run_id: int):
    """Record the reviewer's verdict the way the review submission does."""
    review_run_id = conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, verdict, "
        "case_outcome, started_at, completed_at, created_at) VALUES "
        "(%s, 'agent', 'method_case', 'pass', 'passed', %s, %s, %s) RETURNING id",
        (requirement_id, NOW, NOW, NOW),
    ).fetchone()["id"]
    execution_id = "11111111-2222-3333-4444-555555555555"
    conn.execute(
        "INSERT INTO qa_plan_executions (id, item_id, transition_id, actor_id, "
        "session_id, state, roster_json, roster_digest, cursor_ordinal, "
        "created_at, heartbeat_at) VALUES (%s, %s, 'implemented', 'op', 's-1', "
        "'completed', '[]', 'd', 0, %s, %s)",
        (execution_id, ITEM_ID, NOW, NOW),
    )
    bundle_id = "66666666-7777-8888-9999-000000000000"
    conn.execute(
        "INSERT INTO qa_plan_review_bundles (id, execution_id, roster_digest, "
        "bundle_digest, bundle_json, state, created_at) "
        "VALUES (%s, %s, 'd', 'digest', '{}', 'completed', %s)",
        (bundle_id, execution_id, NOW),
    )
    conn.execute(
        "INSERT INTO qa_plan_review_verdicts (bundle_id, requirement_id, "
        "capture_run_id, review_run_id, verdict, rationale, created_at) "
        "VALUES (%s, %s, %s, %s, 'pass', 'read the capture', %s)",
        (bundle_id, requirement_id, capture_run_id, int(review_run_id), NOW),
    )
    conn.commit()


def _gate(conn):
    return check_browser_evidence_present(
        conn,
        where="r.item_id = %s",
        params=(ITEM_ID,),
        name="browser-evidence",
        transition_name="done",
    )


class TestAgentReviewedCaptureOutcome(unittest.TestCase):
    def test_capture_through_linked_review_satisfies_the_release_gate(self):
        with test_database() as conn:
            _seed_case(
                conn,
                requirement_id=8401,
                method_id="browser-inspection",
                verdict_path="agent",
            )
            capture_run_id = _capture(conn, 8401)

            # The capture states what it is: finished, and awaiting a reader.
            self.assertEqual(
                _outcome(conn, capture_run_id), ("captured", "needs_review", None)
            )
            # Until the review lands, the gate still refuses it.
            self.assertIsNotNone(_gate(conn))

            _link_passing_review(
                conn, requirement_id=8401, capture_run_id=capture_run_id
            )

            self.assertIsNone(_gate(conn))

    def test_an_unreviewed_capture_is_still_refused(self):
        with test_database() as conn:
            _seed_case(
                conn,
                requirement_id=8402,
                method_id="browser-inspection",
                verdict_path="agent",
            )
            _capture(conn, 8402)

            result = _gate(conn)

            self.assertIsNotNone(result)
            self.assertIn(
                "no linked substrate-and-verdict proof", "\n".join(result.errors)
            )
            self.assertIn("yoke qa run record-verdict", "\n".join(result.errors))


    def test_record_verdict_links_a_local_preview_inspection_for_the_gate(self):
        with test_database() as conn:
            _seed_case(
                conn,
                requirement_id=8404,
                method_id="browser-inspection",
                verdict_path="agent",
            )
            _capture(conn, 8404)
            with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
                outcome = qa_run.handle_qa_run_record_verdict(
                    _request(
                        "qa.run.record_verdict",
                        8404,
                        {
                            "performed_by": "agent",
                            "verdict": "pass",
                            "verdict_reason": "local preview matches the capture",
                        },
                    )
                )
            assert outcome.primary_success, outcome.error
            self.assertIsNone(_gate(conn))

    def test_record_verdict_names_capture_recovery_without_a_capture(self):
        with test_database() as conn:
            _seed_case(
                conn,
                requirement_id=8405,
                method_id="browser-inspection",
                verdict_path="agent",
            )
            with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
                outcome = qa_run.handle_qa_run_record_verdict(
                    _request(
                        "qa.run.record_verdict",
                        8405,
                        {
                            "performed_by": "agent",
                            "verdict": "pass",
                            "verdict_reason": "no capture yet",
                        },
                    )
                )
            self.assertFalse(outcome.primary_success)
            self.assertEqual(outcome.error.code, "policy_violation")
            self.assertIn("record-verdict", outcome.error.message)
            self.assertIn("hosts.app", outcome.error.message)


    def test_a_capture_decided_by_its_own_steps_keeps_its_verdict_outcome(self):
        with test_database() as conn:
            _seed_case(
                conn,
                requirement_id=8403,
                method_id="browser-check",
                verdict_path="automatic",
            )
            run_id = _capture(conn, 8403)

            # A Browser check decides itself, so its capture carries no
            # review-pending outcome; the verdict it later records is what
            # names the outcome, exactly as before.
            self.assertEqual(_outcome(conn, run_id), ("captured", None, None))
            with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
                qa_browser_writes.handle_qa_run_complete(
                    _request(
                        "qa.run.complete", 8403, {"run_id": run_id, "verdict": "pass"}
                    )
                )
            self.assertEqual(_outcome(conn, run_id), ("captured", "passed", "pass"))
