"""Authoring one executable case straight against a deployment run.

A release's own checks were authorable only by the pipeline that
materializes them from a frozen plan snapshot, so recording one more check
against a run in flight had no product surface — the identical act was one
command away on an item. These cover the run half of ``qa.requirement.add``:
the row it writes, and every refusal that keeps a hand-authored case honest
about the run it names.
"""

from __future__ import annotations

import unittest

from yoke_core.domain.handlers import qa_requirement_create
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
)
from runtime.api.fixtures.pg_testdb import test_database


BROWSER_CASE = {
    "method_id": "browser-check",
    "qa_phase": "post_deploy",
    "instructions": "Open the released home route.",
    "expected_outcome": "The home page renders the new build.",
    "method_config": {
        "steps": [
            {"action": "navigate", "route": "/"},
            {"action": "assert", "target": "main", "check": "visible"},
        ],
    },
}

STAGES = '[{"name": "stage-smoke"}, {"name": "complete"}]'


def _request(run_id, payload) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.add",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="deployment_run", deployment_run_id=run_id),
        payload=payload,
    )


def _run_with_member(conn, run_id="run-20260916-950", status="executing"):
    insert_item(conn, id=6110, title="Carried", status="implementing")
    insert_deployment_run(conn, id=run_id, status=status)
    conn.execute(
        "UPDATE deployment_flows SET stages=%s "
        "WHERE id=(SELECT flow FROM deployment_runs WHERE id=%s)",
        (STAGES, run_id),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id, item_id, added_at) "
        "VALUES (%s, %s, %s)",
        (run_id, 6110, "2026-09-16T00:00:00Z"),
    )
    conn.commit()
    return run_id


class TestRunAttachedRequirementAdd(unittest.TestCase):
    def test_inserts_run_attached_case(self):
        with test_database() as conn:
            run_id = _run_with_member(conn)
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(run_id, dict(BROWSER_CASE)),
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            self.assertEqual(outcome.result_payload["deployment_run_id"], run_id)
            row = conn.execute(
                "SELECT item_id, deployment_run_id, deployment_stage, "
                "deployment_member_item_id, qa_kind, method_id, "
                "workflow_transition_id, execution_target_digest "
                "FROM qa_requirements WHERE id=%s",
                (outcome.result_payload["requirement_id"],),
            ).fetchone()
        self.assertIsNone(row["item_id"])
        self.assertEqual(row["deployment_run_id"], run_id)
        self.assertIsNone(row["deployment_stage"])
        self.assertEqual(row["qa_kind"], "method_case")
        self.assertEqual(row["method_id"], "browser-check")
        self.assertIsNone(row["workflow_transition_id"])
        # A hand-authored case never carries the execution target the stage
        # gate matches on, so it is evidence rather than a silent gate.
        self.assertIsNone(row["execution_target_digest"])

    def test_scopes_a_case_to_a_stage_and_member_by_public_ref(self):
        with test_database() as conn:
            run_id = _run_with_member(conn)
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(run_id, {
                    **BROWSER_CASE,
                    "deployment_stage": "stage-smoke",
                    "deployment_member_item": "YOK-6110",
                }),
            )
            self.assertTrue(outcome.primary_success, outcome.error)
            self.assertEqual(
                outcome.result_payload["deployment_member_item_id"], 6110,
            )
            row = conn.execute(
                "SELECT deployment_stage, deployment_member_item_id "
                "FROM qa_requirements WHERE id=%s",
                (outcome.result_payload["requirement_id"],),
            ).fetchone()
        self.assertEqual(row["deployment_stage"], "stage-smoke")
        self.assertEqual(int(row["deployment_member_item_id"]), 6110)

    def test_finished_run_refuses_with_its_status(self):
        with test_database() as conn:
            run_id = _run_with_member(
                conn, run_id="run-20260916-951", status="succeeded"
            )
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(run_id, dict(BROWSER_CASE)),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "precondition_failed")
        self.assertIn("succeeded", outcome.error.message)

    def test_unknown_stage_names_the_stages_the_run_declares(self):
        with test_database() as conn:
            run_id = _run_with_member(conn, run_id="run-20260916-952")
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(run_id, {
                    **BROWSER_CASE, "deployment_stage": "not-a-stage",
                }),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("stage-smoke", outcome.error.message)

    def test_member_the_run_does_not_carry_names_what_it_does(self):
        with test_database() as conn:
            run_id = _run_with_member(conn, run_id="run-20260916-953")
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(run_id, {
                    **BROWSER_CASE,
                    "deployment_stage": "stage-smoke",
                    "deployment_member_item": "YOK-9999",
                }),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("YOK-6110", outcome.error.message)

    def test_member_without_a_stage_is_refused(self):
        with test_database() as conn:
            run_id = _run_with_member(conn, run_id="run-20260916-954")
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(run_id, {
                    **BROWSER_CASE, "deployment_member_item": "YOK-6110",
                }),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.jsonpath, "$.payload.deployment_stage")

    def test_case_without_a_method_is_refused(self):
        with test_database() as conn:
            run_id = _run_with_member(conn, run_id="run-20260916-955")
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(run_id, {
                    "qa_kind": "smoke", "qa_phase": "post_deploy",
                }),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.jsonpath, "$.payload.method_id")

    def test_workflow_transition_is_refused_on_a_run(self):
        with test_database() as conn:
            run_id = _run_with_member(conn, run_id="run-20260916-956")
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request(run_id, {
                    **BROWSER_CASE,
                    "workflow_transition_id": "reviewed-implementation",
                }),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(
            outcome.error.jsonpath, "$.payload.workflow_transition_id",
        )

    def test_unknown_run_is_not_found(self):
        with test_database() as conn:
            outcome = qa_requirement_create.handle_qa_requirement_add(
                _request("run-20260916-999", dict(BROWSER_CASE)),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")


class TestItemTargetRejectsRunFields(unittest.TestCase):
    def test_deployment_stage_on_an_item_names_the_right_target(self):
        with test_database() as conn:
            insert_item(conn, id=6120, title="T", status="implementing")
            conn.commit()
            outcome = qa_requirement_create.handle_qa_requirement_add(
                FunctionCallRequest(
                    function="qa.requirement.add",
                    actor=ActorContext(actor_id="op", session_id="s-1"),
                    target=TargetRef(kind="item", item_id=6120),
                    payload={
                        **BROWSER_CASE,
                        "qa_phase": "verification",
                        "deployment_stage": "stage-smoke",
                    },
                ),
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.jsonpath, "$.payload.deployment_stage")


if __name__ == "__main__":
    unittest.main()
