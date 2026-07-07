"""Tests for the ``db_claim.amend`` handler.

The unified DB-claim amendment routes through
:func:`yoke_core.domain.db_claim.amend`. These tests verify the
handler wires the envelope payload + target into that domain call and
threads the AmendmentResult back into the response envelope.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional
from unittest.mock import patch

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.db_claim_apply import AmendmentResult
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import (
    lookup,
    reset_registry_for_tests,
)


def _envelope(
    function: str,
    *,
    target: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
    session_id: str = "s-1",
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id=session_id),
        target=TargetRef(**target),
        payload=payload or {},
    )


class _DbClaimSuite(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()
        register_all_handlers()
        self._patchers = [
            patch.object(events_module, "emit_event"),
            patch.object(
                dispatch_module, "_idempotency_lookup",
                lambda *_a, **_k: None,
            ),
            # Item-scoped claim verification: keep the dispatcher happy.
            patch.object(
                claims_module, "who_claims_for_item",
                return_value={"id": 1, "session_id": "s-1"},
            ),
            # Match the envelope's actor session so the actor-identity gate
            # passes and the test exercises the verify_claim matrix.
            patch.dict("os.environ", {"YOKE_SESSION_ID": "s-1"}, clear=False),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()


class TestDbClaimAmendRegistration(_DbClaimSuite):
    """``db_claim.amend`` is registered with ``claim_required_kind='item'``."""

    def test_registered_with_item_claim(self):
        entry = lookup("db_claim.amend")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.claim_required_kind, "item")
        self.assertIn("DbClaimAmended", entry.emitted_event_names)


class TestDbClaimAmendHandler(_DbClaimSuite):
    def test_amend_writes_both_fields_atomically(self):
        """AC-6.5: amend accepts unified payload and writes profile + attestation."""
        unified = {
            "state": "declared",
            "model_name": "events",
            "mutation_intent": "apply",
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "hard_cutover",
            "schema_kinds": ["create_table"],
            "affected_surfaces": ["events"],
            "count_preserving": False,
            "migration_modules": ["m1"],
        }
        fake_result = AmendmentResult(
            item_id=42,
            previous_profile={"state": "none"},
            previous_attestation={},
            new_profile=unified,
            new_attestation={},
            reason="testing",
            event_id="evt-12345",
        )
        with patch(
            "yoke_core.domain.db_claim.amend", return_value=fake_result,
        ) as mocked:
            resp = dispatch(_envelope(
                "db_claim.amend",
                target={"kind": "item", "item_id": 42},
                payload={"claim": unified, "reason": "testing"},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["item_id"], 42)
        self.assertEqual(resp.result["new_profile"]["state"], "declared")
        self.assertEqual(resp.result["event_id"], "evt-12345")
        # The domain call received the unified payload + reason.
        mocked.assert_called_once()
        call_args = mocked.call_args
        self.assertEqual(call_args.args[0], 42)
        self.assertEqual(call_args.args[1], unified)
        self.assertEqual(call_args.kwargs["reason"], "testing")

    def test_amend_requires_item_target(self):
        resp = dispatch(_envelope(
            "db_claim.amend",
            target={"kind": "global"},
            payload={"claim": {"state": "none"}, "reason": "clear"},
        ))
        # Dispatcher's item-claim check fires first when target.item_id is None.
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")

    def test_amend_surfaces_validation_error(self):
        from yoke_core.domain.db_claim import DbClaimAmendmentError

        with patch(
            "yoke_core.domain.db_claim.amend",
            side_effect=DbClaimAmendmentError("invalid payload"),
        ):
            resp = dispatch(_envelope(
                "db_claim.amend",
                target={"kind": "item", "item_id": 42},
                payload={"claim": {"state": "none"}, "reason": "clear"},
            ))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "amend_failed")
        self.assertIn("invalid payload", resp.error.message)

    def test_amend_rejects_empty_reason(self):
        resp = dispatch(_envelope(
            "db_claim.amend",
            target={"kind": "item", "item_id": 42},
            payload={"claim": {"state": "none"}, "reason": ""},
        ))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "payload_invalid")


if __name__ == "__main__":
    unittest.main()
