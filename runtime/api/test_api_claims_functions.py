"""Tests for the ``claims.work.*`` + ``claims.path.*`` + claims.coordination_claim.* handlers.

Exercises every registered function id via the dispatcher with the
handler modules mocked at the domain layer so we do not touch a live
DB. Claim verification is mocked on the dispatcher's claim helpers per
the patterns established by ``test_yoke_function_dispatch_claims``.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
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


# ---------------------------------------------------------------------------
# Suite scaffolding
# ---------------------------------------------------------------------------


class _ClaimsHandlerSuite(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()
        register_all_handlers()
        self._patchers = [
            patch(
                "yoke_core.domain.function_response_refs.render_item_refs",
                return_value={42: "ITEM-81", 1665: "EXT-19"},
            ),
            patch.object(events_module, "emit_event"),
            patch.object(
                dispatch_module,
                "_idempotency_lookup",
                lambda *_a, **_k: None,
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


def _envelope(
    function: str,
    *,
    target: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
    session_id: str = "s-1",
    actor_id: Optional[str] = "op",
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=actor_id, session_id=session_id),
        target=TargetRef(**target),
        payload=payload or {},
    )


# ---------------------------------------------------------------------------
# Registration assertions
# ---------------------------------------------------------------------------


class TestClaimsHandlersRegistration(_ClaimsHandlerSuite):
    """Every function id declares its ``claim_required_kind``."""

    def test_claim_required_kind_matrix(self):
        expected = {
            "claims.work.acquire": None,
            "claims.work.release": "self_only",
            "claims.path.register": "item",
            "claims.path.widen": "item",
            "claims.path.release": "item",
            "claims.path.amend": "item",
            "claims.path.override": "steering",
            "claims.coordination_claim.operator_release": None,
            "db_claim.amend": "item",
        }
        for fid, kind in expected.items():
            entry = lookup(fid)
            self.assertIsNotNone(entry, f"{fid} not registered")
            self.assertEqual(
                entry.claim_required_kind,
                kind,
                f"{fid}: expected {kind!r}, got {entry.claim_required_kind!r}",
            )

    def test_claim_coordination_function_coverage_present(self):
        """Extra claim-adjacent surfaces are also registered."""
        extras = [
            "claims.work.holder_get",
            "claims.work.holder_list",
            "claims.path.activation_run",
            "claims.path.coordination_decision_build",
            "claims.coordination_claim.acquire",
            "claims.coordination_claim.heartbeat",
            "claims.coordination_claim.release",
            "claims.coordination_claim.operator_release",
            "claims.coordination_claim.list",
        ]
        for fid in extras:
            entry = lookup(fid)
            self.assertIsNotNone(entry, f"{fid} not registered")
            self.assertIn(entry.adapter_status, ("live", "deprecated", "retired"))


# ---------------------------------------------------------------------------
# claims.work.* handler tests
# ---------------------------------------------------------------------------


class TestClaimsWork(_ClaimsHandlerSuite):
    def test_acquire_records_row_and_returns_claim_id(self):
        fake_row = {
            "id": 1234,
            "session_id": "s-1",
            "target_kind": "item",
            "scope": {"item_id": 42},
        }
        with patch(
            "yoke_core.domain.sessions_lifecycle_claim.claim_work",
            return_value=fake_row,
        ):
            resp = dispatch(
                _envelope(
                    "claims.work.acquire",
                    target={"kind": "item", "item_id": 42},
                    payload={"target": {"kind": "item", "item_id": 42}},
                )
            )
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["claim_id"], 1234)
        self.assertEqual(resp.result["session_id"], "s-1")
        self.assertEqual(resp.result["scope"], {"public_ref": "ITEM-81"})

    def test_release_requires_self_only(self):
        """Release rejects when caller isn't the holder."""
        with patch.object(
            claims_module,
            "_claim_row_for_id",
            return_value={"id": 99, "session_id": "OTHER"},
        ):
            resp = dispatch(
                _envelope(
                    "claims.work.release",
                    target={"kind": "claim", "claim_id": 99},
                    payload={"claim_id": 99, "reason": "handoff"},
                )
            )
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")

    def test_release_succeeds_when_caller_is_holder(self):
        fake_row = {
            "id": 99,
            "released_at": "2026-05-13T07:00:00Z",
            "release_reason": "handoff",
        }
        with (
            patch.object(
                claims_module,
                "_claim_row_for_id",
                return_value={"id": 99, "session_id": "s-1"},
            ),
            patch(
                "yoke_core.domain.sessions_lifecycle_claim.release_claim",
                return_value=fake_row,
            ),
        ):
            resp = dispatch(
                _envelope(
                    "claims.work.release",
                    target={"kind": "claim", "claim_id": 99},
                    payload={"claim_id": 99, "reason": "handoff"},
                )
            )
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["claim_id"], 99)

    def test_holder_get_returns_row(self):
        fake_row = {
            "id": 1,
            "session_id": "s-1",
            "target_kind": "item",
            "scope": {"item_id": 42},
        }
        with (
            patch(
                "yoke_core.domain.sessions_queries_lookup.get_claim_for_work_unit",
                return_value=fake_row,
            ),
            patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=MagicMock(
                    __enter__=lambda s: s, __exit__=lambda s, *a: None
                ),
            ),
        ):
            resp = dispatch(
                _envelope(
                    "claims.work.holder_get",
                    target={"kind": "item", "item_id": 42},
                    payload={"item_id": 42},
                )
            )
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["holder"]["claim_id"], 1)
        self.assertEqual(resp.result["holder"]["scope"], {"public_ref": "ITEM-81"})


# ---------------------------------------------------------------------------
# claims.path.* handler tests
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
