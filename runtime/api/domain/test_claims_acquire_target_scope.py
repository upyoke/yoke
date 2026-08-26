"""Dispatcher acquire returns the canonical typed target scope."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


class TestClaimsAcquireTargetScope(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()
        register_all_handlers()
        self._patchers = [
            patch.object(events_module, "emit_event"),
            patch.object(
                dispatch_module,
                "_idempotency_lookup",
                lambda *_a, **_k: None,
            ),
            patch.dict("os.environ", {"YOKE_SESSION_ID": "s-1"}, clear=False),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()

    def test_acquire_result_preserves_item_scope(self) -> None:
        fake_row = {
            "id": 1234,
            "session_id": "s-1",
            "target_kind": "item",
            "scope": {"item_id": 42},
        }
        with patch(
            "yoke_core.domain.sessions_lifecycle_claim.claim_work",
            return_value=fake_row,
        ), patch(
            "yoke_core.domain.result_item_ref_enrichment.enrich_result_item_refs",
            side_effect=lambda result, **_k: dict(result),
        ):
            resp = dispatch(
                FunctionCallRequest(
                    function="claims.work.acquire",
                    actor=ActorContext(actor_id="op", session_id="s-1"),
                    target=TargetRef(kind="item", item_id=42),
                    payload={"target": {"kind": "item", "item_id": 42}},
                )
        )
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["target_kind"], "item")
        self.assertEqual(resp.result["scope"], {"item_id": 42})
        self.assertNotIn("item_id", resp.result)
        self.assertNotIn("item_ref", resp.result)


if __name__ == "__main__":
    unittest.main()
