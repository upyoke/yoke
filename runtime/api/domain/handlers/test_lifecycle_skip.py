"""Handler tests for lifecycle.skip.record_recoverable_substrate.

Covers the AC-2 surface: positive dispatch through the function-call
registry produces the expected ``chain_skip_memory`` entry shape,
invalid envelopes are rejected with structured errors, and the helper
side-effects (claim release + event emission) execute through the
sanctioned wrapper rather than via direct ``python3 -c`` import.

The persistence and event-emission side effects themselves are
exercised by :mod:`runtime.api.domain.test_sessions_handler_outcome`
against the underlying helper. These tests focus on the handler /
dispatch surface — the new layer this slice adds.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import lifecycle_skip
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


_SESSION_ID = "sess-skip-handler-test"
_ITEM_ID = 4242


def _request(
    *,
    target: TargetRef,
    payload: dict,
    actor_session: str = _SESSION_ID,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="lifecycle.skip.record_recoverable_substrate",
        actor=ActorContext(session_id=actor_session),
        target=target,
        payload=payload,
    )


class _StubConn:
    """Stand-in for the DB connection ``db_helpers.connect`` returns.

    The handler only needs ``__enter__`` / ``__exit__`` to be callable; the
    real persistence path is patched at the helper boundary, so the conn
    object itself is never inspected by the test.
    """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


_DEFAULT_PAYLOAD = {
    "chain_step": 3,
    "project": "yoke",
    "routed_action": "advance",
    "failure_class": "cwd_drift",
    "remediation_owner": "YOK-1862",
    "current_status": "implementing",
    "useful_work_began": False,
}


def _connect_returns_stub():
    return patch(
        "yoke_core.domain.db_helpers.connect",
        return_value=_StubConn(),
    )


def _helper_returns_entry(entry):
    return patch(
        "yoke_core.domain.handlers.lifecycle_skip.record_recoverable_substrate_skip",
        return_value=entry,
    )


class TestTargetValidation(unittest.TestCase):
    """Target.kind/item_id must name a real item; everything else fails."""

    def test_rejects_non_item_target(self):
        outcome = lifecycle_skip.handle_record_recoverable_substrate_skip(
            _request(
                target=TargetRef(kind="global"),
                payload=_DEFAULT_PAYLOAD,
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_payload")
        self.assertIn("kind='item'", outcome.error.message)

    def test_rejects_missing_item_id(self):
        outcome = lifecycle_skip.handle_record_recoverable_substrate_skip(
            _request(
                target=TargetRef(kind="item"),
                payload=_DEFAULT_PAYLOAD,
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_payload")


class TestPayloadValidation(unittest.TestCase):
    """Pydantic surfaces structured errors via the invalid_payload code."""

    def test_rejects_missing_required_field(self):
        bad_payload = dict(_DEFAULT_PAYLOAD)
        bad_payload.pop("failure_class")
        outcome = lifecycle_skip.handle_record_recoverable_substrate_skip(
            _request(
                target=TargetRef(kind="item", item_id=_ITEM_ID),
                payload=bad_payload,
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_payload")
        self.assertIn("payload invalid", outcome.error.message)

    def test_rejects_non_integer_chain_step(self):
        bad_payload = dict(_DEFAULT_PAYLOAD)
        bad_payload["chain_step"] = "three"
        outcome = lifecycle_skip.handle_record_recoverable_substrate_skip(
            _request(
                target=TargetRef(kind="item", item_id=_ITEM_ID),
                payload=bad_payload,
            ),
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_payload")


class TestSuccessfulDispatch(unittest.TestCase):
    """Positive path forwards to the helper and echoes the entry back."""

    def _stub_entry(self, **overrides):
        entry = {
            "skip_reason": "recoverable_substrate",
            "chain_step": 3,
            "routed_action": "advance",
            "failure_class": "cwd_drift",
            "remediation_owner": "YOK-1862",
            "useful_work_began": False,
            "item_id": str(_ITEM_ID),
            "current_status": "implementing",
        }
        entry.update(overrides)
        return entry

    def test_forwards_helper_call_with_canonicalized_item_id(self):
        stub_entry = self._stub_entry()
        with _connect_returns_stub(), _helper_returns_entry(stub_entry) as helper:
            outcome = lifecycle_skip.handle_record_recoverable_substrate_skip(
                _request(
                    target=TargetRef(kind="item", item_id=_ITEM_ID),
                    payload=_DEFAULT_PAYLOAD,
                ),
            )
        self.assertTrue(outcome.primary_success)
        self.assertIsNone(outcome.error)
        helper.assert_called_once()
        _, kwargs = helper.call_args
        self.assertEqual(kwargs["session_id"], _SESSION_ID)
        self.assertEqual(kwargs["item_id"], f"YOK-{_ITEM_ID}")
        self.assertEqual(kwargs["chain_step"], 3)
        self.assertEqual(kwargs["project"], "yoke")
        self.assertEqual(kwargs["failure_class"], "cwd_drift")
        self.assertEqual(kwargs["remediation_owner"], "YOK-1862")
        self.assertEqual(kwargs["useful_work_began"], False)

    def test_response_mirrors_persisted_entry(self):
        stub_entry = self._stub_entry()
        with _connect_returns_stub(), _helper_returns_entry(stub_entry):
            outcome = lifecycle_skip.handle_record_recoverable_substrate_skip(
                _request(
                    target=TargetRef(kind="item", item_id=_ITEM_ID),
                    payload=_DEFAULT_PAYLOAD,
                ),
            )
        self.assertTrue(outcome.primary_success)
        payload = outcome.result_payload
        self.assertEqual(payload["skip_reason"], "recoverable_substrate")
        self.assertEqual(payload["chain_step"], 3)
        self.assertEqual(payload["failure_class"], "cwd_drift")
        self.assertEqual(payload["remediation_owner"], "YOK-1862")
        self.assertEqual(payload["item_id"], str(_ITEM_ID))
        self.assertEqual(payload["current_status"], "implementing")
        self.assertFalse(payload["useful_work_began"])


class TestRegistrationDescriptor(unittest.TestCase):
    """REGISTRATIONS row carries the contract every dispatcher reads."""

    def test_registers_canonical_function_id(self):
        ids = [reg["function_id"] for reg in lifecycle_skip.REGISTRATIONS]
        self.assertIn(
            "lifecycle.skip.record_recoverable_substrate", ids,
        )

    def test_advertised_event_names_include_offer_skipped(self):
        reg = lifecycle_skip.REGISTRATIONS[0]
        self.assertIn("SchedulerOfferSkipped", reg["emitted_event_names"])
        self.assertIn("YokeFunctionCalled", reg["emitted_event_names"])

    def test_requires_item_work_claim(self):
        reg = lifecycle_skip.REGISTRATIONS[0]
        self.assertEqual(reg["claim_required_kind"], "item")
        self.assertIn("claim_required", reg["guardrails"])


class TestDispatchIntegration(unittest.TestCase):
    """End-to-end through the function-call registry.

    The dispatcher's claim verification and event emission paths are
    patched out so the test exercises registry lookup + handler routing
    in isolation. The handler-level side effects (helper call shape,
    response payload) are already covered above; this case verifies the
    function id is reachable through the canonical entrypoint.
    """

    def test_dispatch_routes_to_handler(self):
        from yoke_core.domain import yoke_function_dispatch

        stub_entry = {
            "skip_reason": "recoverable_substrate",
            "chain_step": 7,
            "routed_action": "advance",
            "failure_class": "path-claim-overlap-incompatible",
            "remediation_owner": "YOK-1862",
            "useful_work_began": False,
            "item_id": str(_ITEM_ID),
        }
        envelope = {
            "function": "lifecycle.skip.record_recoverable_substrate",
            "actor": {"session_id": _SESSION_ID},
            "target": {"kind": "item", "item_id": _ITEM_ID},
            "payload": {
                **_DEFAULT_PAYLOAD,
                "chain_step": 7,
                "failure_class": "path-claim-overlap-incompatible",
            },
        }
        with patch(
            "yoke_core.domain.yoke_function_dispatch.bind_actor_identity",
        ) as bind, patch(
            "yoke_core.domain.yoke_function_dispatch.verify_claim",
            return_value=None,
        ), patch(
            "yoke_core.domain.yoke_function_dispatch.emit_called",
        ), patch(
            "yoke_core.domain.yoke_function_dispatch.emit_downstream_degraded",
        ), _connect_returns_stub(), _helper_returns_entry(stub_entry):
            # bind_actor_identity is invoked by dispatch and returns a bound
            # request envelope; stub it to passthrough the typed request.
            def _passthrough(entry, request, ambient_session_id=None):
                from yoke_core.domain.yoke_function_actor_identity import (
                    BoundIdentity,
                )
                return BoundIdentity(
                    bound_request=request,
                    payload_session_id=request.actor.session_id,
                    ambient_session_id=request.actor.session_id,
                    error=None,
                )

            bind.side_effect = _passthrough
            response = yoke_function_dispatch.dispatch(envelope)

        self.assertTrue(response.success)
        self.assertEqual(
            response.function, "lifecycle.skip.record_recoverable_substrate",
        )
        self.assertEqual(response.result["chain_step"], 7)
        self.assertEqual(
            response.result["failure_class"],
            "path-claim-overlap-incompatible",
        )


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
