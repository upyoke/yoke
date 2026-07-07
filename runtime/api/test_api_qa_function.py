"""Unit tests for QA-family handlers — qa.requirement.update + qa.run.record_verdict."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import patch

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers import qa, qa_run
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database


def _request(function_id: str, target: TargetRef, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload or {},
    )


class TestQaRequirementUpdate(unittest.TestCase):
    def test_rejects_missing_target(self):
        req = _request(
            "qa.requirement.update", TargetRef(kind="global"),
            payload={"field": "blocking_mode", "value": "blocking"},
        )
        outcome = qa.handle_qa_requirement_update(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_rejects_unupdatable_field(self):
        req = _request(
            "qa.requirement.update",
            TargetRef(kind="qa_requirement", qa_requirement_id=10),
            payload={"field": "qa_kind", "value": "ac_verification"},
        )
        outcome = qa.handle_qa_requirement_update(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "field_not_updatable")

    def test_rejects_invalid_blocking_mode(self):
        req = _request(
            "qa.requirement.update",
            TargetRef(kind="qa_requirement", qa_requirement_id=10),
            payload={"field": "blocking_mode", "value": "wat"},
        )
        outcome = qa.handle_qa_requirement_update(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_updates_blocking_mode_emits_event(self):
        captured: dict = {}

        class _Row(dict):
            def __getitem__(self, k):
                return super().__getitem__(k)

        existing = _Row(
            qa_kind="ac_verification", qa_phase="verification",
            item_id="42", epic_id=None, task_num=None, deployment_run_id=None,
        )

        executed_sql: list = []

        class _Conn:
            def execute(self, sql, params):
                executed_sql.append((sql, params))

                class _R:
                    def fetchone(self_inner):
                        return existing

                return _R()

            def commit(self):
                captured["committed"] = True

            def close(self):
                captured["closed"] = True

        with patch(
            "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
        ):
            with patch(
                "yoke_core.domain.db_helpers.query_one",
                return_value=existing,
            ):
                with patch(
                    "yoke_core.domain.qa_events.emit_qa_requirement_event",
                ) as emit:
                    req = _request(
                        "qa.requirement.update",
                        TargetRef(kind="qa_requirement", qa_requirement_id=10),
                        payload={"field": "blocking_mode", "value": "blocking"},
                    )
                    outcome = qa.handle_qa_requirement_update(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["new_value"], "blocking")
        emit.assert_called_once()


class TestQaRunRecordVerdict(unittest.TestCase):
    def test_rejects_invalid_verdict(self):
        req = _request(
            "qa.run.record_verdict",
            TargetRef(kind="qa_requirement", qa_requirement_id=7),
            payload={"executor_type": "agent", "verdict": "maybe"},
        )
        outcome = qa_run.handle_qa_run_record_verdict(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_rejects_agent_for_browser_kind(self):
        existing = {"qa_kind": "browser_smoke"}

        class _Conn:
            def close(self):
                pass

        with patch(
            "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
        ):
            with patch(
                "yoke_core.domain.db_helpers.query_one",
                return_value=existing,
            ):
                req = _request(
                    "qa.run.record_verdict",
                    TargetRef(kind="qa_requirement", qa_requirement_id=7),
                    payload={"executor_type": "agent", "verdict": "pass"},
                )
                outcome = qa_run.handle_qa_run_record_verdict(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "policy_violation")

    def test_happy_path_inserts_row(self):
        existing = {"qa_kind": "ac_verification"}

        class _Cursor:
            # record_verdict reads the inserted id via ``RETURNING id`` +
            # ``cur.fetchone()[0]`` (handlers/qa_run.py); no lastrowid path.
            def fetchone(self):
                return (99,)

        class _Conn:
            def execute(self, sql, params):
                return _Cursor()

            def commit(self):
                pass

            def close(self):
                pass

        with patch(
            "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
        ):
            with patch(
                "yoke_core.domain.db_helpers.query_one",
                return_value=existing,
            ):
                with patch(
                    "yoke_core.domain.qa_events.emit_qa_run_event",
                ) as emit:
                    req = _request(
                        "qa.run.record_verdict",
                        TargetRef(kind="qa_requirement", qa_requirement_id=7),
                        payload={
                            "executor_type": "agent",
                            "verdict": "pass",
                            "raw_result": "all good",
                        },
                    )
                    outcome = qa_run.handle_qa_run_record_verdict(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["qa_run_id"], 99)
        self.assertEqual(outcome.result_payload["verdict"], "pass")
        emit.assert_called_once()


class TestQaRequirementClaimDispatch(unittest.TestCase):
    """Real-dispatch coverage for qa.requirement.update + qa.run.record_verdict
    when the caller passes only ``target.qa_requirement_id``.

    Exercises the full dispatcher path (envelope coerce -> registry lookup ->
    bind_actor_identity -> verify_claim -> handler) against an isolated
    Postgres fixture seeded with a qa_requirement that maps to an item, and a
    work_claim by a known session.
    """

    @contextmanager
    def _build_fixture(self, *, holder_session_id="held-session"):
        with test_database() as conn:
            now = iso8601_now()
            insert_item(conn, id=42, title="T", status="implementing")
            insert_qa_requirement(
                conn,
                id=10,
                item_id=42,
                qa_kind="ac_verification",
                qa_phase="verification",
                blocking_mode="blocking",
                success_policy="",
            )
            conn.execute(
                "INSERT INTO harness_sessions "
                "(session_id, executor, provider, model, workspace, "
                " offered_at, last_heartbeat) "
                "VALUES (%s, 'codex', 'openai', 'gpt-5', '/tmp', %s, %s)",
                (holder_session_id, now, now),
            )
            conn.execute(
                "INSERT INTO work_claims "
                "(id, session_id, item_id, target_kind, claimed_at, "
                " last_heartbeat, released_at) "
                "VALUES (1, %s, 42, 'item', %s, %s, NULL)",
                (holder_session_id, now, now),
            )
            conn.commit()
            yield conn

    def _stub_handler(self, function_id, result_payload):
        from dataclasses import replace
        from yoke_core.domain import yoke_function_registry
        from yoke_core.domain.yoke_function_dispatch import (
            _ensure_handlers_registered,
        )
        from yoke_contracts.api.function_call import HandlerOutcome

        _ensure_handlers_registered()
        entry = yoke_function_registry.lookup(function_id)
        assert entry is not None, f"{function_id} must be registered"
        stubbed = replace(
            entry,
            handler=lambda _req: HandlerOutcome(result_payload=result_payload),
        )
        yoke_function_registry._REGISTRY[function_id] = stubbed
        return function_id, entry  # original entry, restored in finally

    def _dispatch_with_stubs(
        self, request, holder_session_id, *, stub_handler=None
    ):
        from yoke_core.domain import yoke_function_dispatch
        yoke_function_dispatch._ensure_handlers_registered()

        # bind_actor_identity returns BoundIdentity(bound_request,
        # error=None, ambient/payload session ids, override + registration
        # findings). Stub to passthrough so we do not require a
        # harness_sessions row for the actor.
        class _BoundStub:
            def __init__(self, req):
                self.bound_request = req
                self.error = None
                self.ambient_session_id = holder_session_id
                self.payload_session_id = holder_session_id
                self.explicit_override = False
                self.session_registered = True

        restored = None
        if stub_handler:
            restored = self._stub_handler(*stub_handler)
        try:
            with patch(
                "yoke_core.domain.yoke_function_dispatch.bind_actor_identity",
                side_effect=lambda entry, req, **_kw: _BoundStub(req),
            ), patch(
                "yoke_core.domain.yoke_function_dispatch.emit_called",
                return_value=None,
            ):
                return yoke_function_dispatch.dispatch(request)
        finally:
            if restored is not None:
                from yoke_core.domain import yoke_function_registry
                function_id, original_entry = restored
                yoke_function_registry._REGISTRY[function_id] = original_entry

    def test_held_claim_dispatch_succeeds_for_requirement_update(self):
        with self._build_fixture(holder_session_id="held-session"):
            request = FunctionCallRequest(
                function="qa.requirement.update",
                actor=ActorContext(actor_id="op", session_id="held-session"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=10),
                payload={"field": "blocking_mode", "value": "blocking"},
            )
            response = self._dispatch_with_stubs(
                request, "held-session",
                stub_handler=("qa.requirement.update", {"ok": True}),
            )
        self.assertTrue(response.success, response.error)
        self.assertEqual(response.result, {"ok": True})

    def test_held_claim_dispatch_succeeds_for_run_record_verdict(self):
        with self._build_fixture(holder_session_id="held-session"):
            request = FunctionCallRequest(
                function="qa.run.record_verdict",
                actor=ActorContext(actor_id="op", session_id="held-session"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=10),
                payload={"executor_type": "agent", "verdict": "pass"},
            )
            response = self._dispatch_with_stubs(
                request, "held-session",
                stub_handler=("qa.run.record_verdict", {"ok": True}),
            )
        self.assertTrue(response.success, response.error)

    def test_missing_claim_names_resolved_item_id(self):
        # holder is a different session; caller does not hold the claim.
        with self._build_fixture(holder_session_id="other-session"):
            request = FunctionCallRequest(
                function="qa.requirement.update",
                actor=ActorContext(actor_id="op", session_id="caller-session"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=10),
                payload={"field": "blocking_mode", "value": "blocking"},
            )
            response = self._dispatch_with_stubs(
                request, "caller-session",
            )
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "claim_required")
        # Resolved item_id (42), not "target id is missing".
        self.assertIn("42", response.error.message)
        self.assertNotIn("target id is missing", response.error.message)

    def test_unknown_qa_requirement_id_returns_not_found(self):
        with self._build_fixture():
            request = FunctionCallRequest(
                function="qa.run.record_verdict",
                actor=ActorContext(actor_id="op", session_id="held-session"),
                target=TargetRef(kind="qa_requirement", qa_requirement_id=9999),
                payload={"executor_type": "agent", "verdict": "pass"},
            )
            response = self._dispatch_with_stubs(
                request, "held-session",
            )
        self.assertFalse(response.success)
        self.assertEqual(response.error.code, "not_found")
        self.assertIn("9999", response.error.message)


if __name__ == "__main__":
    unittest.main()
