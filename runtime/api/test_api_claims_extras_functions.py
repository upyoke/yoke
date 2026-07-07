"""Tests for the claim-adjacent extras: ``coordination_lease.*`` +
``activation_run`` + ``coordination_decision_build``.

Sibling of :mod:`test_api_claims_functions` to keep each test module
under the 350-line file-line budget. See that module for the canonical
suite scaffolding and registration assertions.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional
from unittest.mock import patch

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
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


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


class _ExtrasSuite(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()
        register_all_handlers()
        self._patchers = [
            patch.object(events_module, "emit_event"),
            patch.object(
                dispatch_module, "_idempotency_lookup",
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


# ---------------------------------------------------------------------------
# claims.coordination_lease.* — read/mutate over the lease primitive.
# ---------------------------------------------------------------------------


class _FakeLease:
    def __init__(self, **kwargs: Any) -> None:
        self.id = kwargs.get("id", 1)
        self.project_id = kwargs.get("project_id", "yoke")
        self.lease_key = kwargs.get("lease_key", "LIVE_DB_MIGRATION:foo")
        self.session_id = kwargs.get("session_id", "s-1")
        self.actor_id = kwargs.get("actor_id")
        self.acquired_at = kwargs.get("acquired_at", "2026-05-13T07:00:00Z")
        self.heartbeat_at = kwargs.get("heartbeat_at", "2026-05-13T07:00:00Z")
        self.released_at = kwargs.get("released_at")
        self.release_reason = kwargs.get("release_reason")


class TestCoordinationLease(_ExtrasSuite):
    def test_acquire_returns_lease(self):
        with patch(
            "yoke_core.domain.coordination_leases.acquire_lease",
            return_value=_FakeLease(id=10),
        ):
            resp = dispatch(_envelope(
                "claims.coordination_lease.acquire",
                target={"kind": "global"},
                payload={
                    "project_id": "yoke",
                    "lease_key": "LIVE_DB_MIGRATION:foo",
                },
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["lease"]["id"], 10)

    def test_heartbeat_returns_refreshed_lease(self):
        with patch(
            "yoke_core.domain.coordination_leases.heartbeat_lease",
            return_value=_FakeLease(id=10, heartbeat_at="2026-05-13T07:01:00Z"),
        ):
            resp = dispatch(_envelope(
                "claims.coordination_lease.heartbeat",
                target={"kind": "global"},
                payload={"lease_id": 10},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["lease"]["heartbeat_at"], "2026-05-13T07:01:00Z")

    def test_release_returns_released_lease(self):
        with patch(
            "yoke_core.domain.coordination_leases.release_lease",
            return_value=_FakeLease(
                id=10, released_at="2026-05-13T07:02:00Z",
                release_reason="done",
            ),
        ):
            resp = dispatch(_envelope(
                "claims.coordination_lease.release",
                target={"kind": "global"},
                payload={"lease_id": 10, "reason": "done"},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["lease"]["release_reason"], "done")

    def test_list_returns_leases(self):
        with patch(
            "yoke_core.domain.coordination_leases.list_leases",
            return_value=[_FakeLease(id=10), _FakeLease(id=11)],
        ):
            resp = dispatch(_envelope(
                "claims.coordination_lease.list",
                target={"kind": "global"},
                payload={"project_id": "yoke"},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(len(resp.result["leases"]), 2)


# ---------------------------------------------------------------------------
# claims.path.activation_run + claims.path.coordination_decision_build.
# ---------------------------------------------------------------------------


class _FakeActivationResult:
    def __init__(self) -> None:
        self.item_id = 1665
        self.actor_id = 2
        self.outcomes = []
        self.blocked_errors = []
        self.diverged_error = None


class TestClaimsPathActivation(_ExtrasSuite):
    def _hold_item_claim(self):
        return patch.object(
            claims_module, "who_claims_for_item",
            return_value={"id": 1, "session_id": "s-1"},
        )

    def test_activation_run_returns_outcomes(self):
        with self._hold_item_claim(), patch(
            "yoke_core.domain.advance_path_claim_activation.run_activation_phase",
            return_value=_FakeActivationResult(),
        ):
            resp = dispatch(_envelope(
                "claims.path.activation_run",
                target={"kind": "item", "item_id": 1665},
                payload={"item_id": 1665, "actor_id": 2},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["item_id"], 1665)
        self.assertEqual(resp.result["outcomes"], [])

    def test_coordination_decision_build_returns_context(self):
        ctx = {
            "candidate_item_id": 1665,
            "conflicting_claim_id": 200,
            "shared_paths": ["runtime/x.py"],
        }
        with patch(
            "yoke_core.domain.path_claim_coordination_decision.build_coordination_context",
            return_value=ctx,
        ):
            resp = dispatch(_envelope(
                "claims.path.coordination_decision_build",
                target={"kind": "item", "item_id": 1665},
                payload={
                    "candidate_item_id": 1665,
                    "conflicting_claim_id": 200,
                    "shared_paths": ["runtime/x.py"],
                },
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["context"], ctx)

    def test_coordination_decision_build_uses_resolved_item_target(self):
        ctx = {
            "candidate_item_id": 1665,
            "conflicting_claim_id": 200,
            "shared_paths": ["runtime/x.py"],
        }
        with patch(
            "yoke_core.domain.path_claim_coordination_decision.build_coordination_context",
            return_value=ctx,
        ) as build:
            resp = dispatch(_envelope(
                "claims.path.coordination_decision_build",
                target={"kind": "item", "item_id": 1665},
                payload={
                    "conflicting_claim_id": 200,
                    "shared_paths": ["runtime/x.py"],
                },
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["context"], ctx)
        self.assertEqual(build.call_args.kwargs["candidate_item_id"], 1665)


if __name__ == "__main__":
    unittest.main()
