"""Tests for the ``claims.work.*`` + ``claims.path.*`` + claims.coordination_lease.* handlers.

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
# Registration assertions — AC-6.7 + AC-6.9
# ---------------------------------------------------------------------------


class TestClaimsHandlersRegistration(_ClaimsHandlerSuite):
    """AC-6.7: every function id declares its ``claim_required_kind``."""

    def test_claim_required_kind_matrix(self):
        expected = {
            "claims.work.acquire": None,
            "claims.work.release": "self_only",
            "claims.path.register": "item",
            "claims.path.widen": "item",
            "claims.path.release": "item",
            "claims.path.amend": "item",
            "claims.path.override": "operator_override",
            "db_claim.amend": "item",
        }
        for fid, kind in expected.items():
            entry = lookup(fid)
            self.assertIsNotNone(entry, f"{fid} not registered")
            self.assertEqual(
                entry.claim_required_kind, kind,
                f"{fid}: expected {kind!r}, got {entry.claim_required_kind!r}",
            )

    def test_claim_coordination_function_coverage_present(self):
        """AC-6.9: extra claim-adjacent surfaces are also registered."""
        extras = [
            "claims.work.holder_get",
            "claims.work.holder_list",
            "claims.path.activation_run",
            "claims.path.coordination_decision_build",
            "claims.coordination_lease.acquire",
            "claims.coordination_lease.heartbeat",
            "claims.coordination_lease.release",
            "claims.coordination_lease.list",
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
            "id": 1234, "session_id": "s-1", "target_kind": "item",
            "item_id": 42, "epic_id": None, "task_num": None,
            "process_key": None, "conflict_group": None,
        }
        with patch(
            "yoke_core.domain.sessions_lifecycle_claim.claim_work",
            return_value=fake_row,
        ):
            resp = dispatch(_envelope(
                "claims.work.acquire",
                target={"kind": "item", "item_id": 42},
                payload={"target": {"kind": "item", "item_id": 42}},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["claim_id"], 1234)
        self.assertEqual(resp.result["session_id"], "s-1")

    def test_release_requires_self_only(self):
        """AC-6.2: release rejects when caller isn't the holder."""
        with patch.object(
            claims_module, "_claim_row_for_id",
            return_value={"id": 99, "session_id": "OTHER"},
        ):
            resp = dispatch(_envelope(
                "claims.work.release",
                target={"kind": "claim", "claim_id": 99},
                payload={"claim_id": 99, "reason": "handoff"},
            ))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")

    def test_release_succeeds_when_caller_is_holder(self):
        fake_row = {
            "id": 99, "released_at": "2026-05-13T07:00:00Z",
            "release_reason": "handoff",
        }
        with patch.object(
            claims_module, "_claim_row_for_id",
            return_value={"id": 99, "session_id": "s-1"},
        ), patch(
            "yoke_core.domain.sessions_lifecycle_claim.release_claim",
            return_value=fake_row,
        ):
            resp = dispatch(_envelope(
                "claims.work.release",
                target={"kind": "claim", "claim_id": 99},
                payload={"claim_id": 99, "reason": "handoff"},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["claim_id"], 99)

    def test_holder_get_returns_row(self):
        fake_row = {
            "id": 1, "session_id": "s-1", "target_kind": "item",
            "item_id": 42, "epic_id": None, "task_num": None,
        }
        with patch(
            "yoke_core.domain.sessions_queries_lookup.get_claim_for_work_unit",
            return_value=fake_row,
        ), patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=MagicMock(__enter__=lambda s: s, __exit__=lambda s, *a: None),
        ):
            resp = dispatch(_envelope(
                "claims.work.holder_get",
                target={"kind": "item", "item_id": 42},
                payload={"item_id": 42},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["holder"]["claim_id"], 1)


# ---------------------------------------------------------------------------
# claims.path.* handler tests
# ---------------------------------------------------------------------------


class TestClaimsPath(_ClaimsHandlerSuite):
    def _hold_item_claim(self):
        return patch.object(
            claims_module, "who_claims_for_item",
            return_value={"id": 1, "session_id": "s-1"},
        )

    def test_register_routes_to_register_for_item(self):
        """AC-6.3: register accepts paths/target ids/integration target."""
        with self._hold_item_claim(), patch(
            "yoke_core.domain.path_claims_register.register_for_item",
            return_value=555,
        ):
            resp = dispatch(_envelope(
                "claims.path.register",
                target={"kind": "item", "item_id": 1665},
                payload={
                    "item_id": 1665,
                    "integration_target": "main",
                    "paths": ["runtime/api/x.py", "runtime/api/y.py"],
                    "allow_planned": True,
                },
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["claim_id"], 555)

    def test_register_overlap_returns_denial_body(self):
        from yoke_core.domain.path_claims import IncompatibleOverlap

        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        denial = (
            "BLOCKED: path-claim register overlap on item YOK-1665.\n"
            "  conflicting claims:\n"
            "    claim 300: docs/db-reference/functions.md"
        )
        with self._hold_item_claim(), patch(
            "yoke_core.domain.db_helpers.connect", return_value=mock_conn,
        ), patch(
            "yoke_core.domain.path_claims_register_validate_integration_target."
            "resolve_and_validate_integration_target",
            return_value="main",
        ), patch(
            "yoke_core.domain.path_claims_register.register_for_item",
            side_effect=IncompatibleOverlap("raw overlap"),
        ), patch(
            "yoke_core.domain.handlers.claims_path."
            "render_overlap_denial_for_register",
            return_value=denial,
        ) as render_denial:
            resp = dispatch(_envelope(
                "claims.path.register",
                target={"kind": "item", "item_id": 1665},
                payload={
                    "item_id": 1665,
                    "integration_target": "main",
                    "paths": ["docs/db-reference/functions.md"],
                    "allow_planned": True,
                },
                actor_id=None,
            ))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "register_failed")
        self.assertIn("BLOCKED: path-claim register overlap", resp.error.message)
        self.assertIn("claim 300", resp.error.message)
        self.assertIn("docs/db-reference/functions.md", resp.error.message)
        render_denial.assert_called_once()

    def test_widen_routes_to_amend_widen(self):
        with self._hold_item_claim(), patch(
            "yoke_core.domain.path_claims_amend.widen",
            return_value=400,
        ):
            resp = dispatch(_envelope(
                "claims.path.widen",
                target={"kind": "item", "item_id": 1665},
                payload={
                    "claim_id": 116,
                    "add_target_ids": [2956, 2957],
                    "reason": "split file budget",
                },
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["amendment_id"], 400)

    def test_release_routes_to_path_claims_release(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "state": "released", "released_at": "2026-05-13T07:00:00Z",
        }
        with self._hold_item_claim(), patch(
            "yoke_core.domain.db_helpers.connect", return_value=mock_conn,
        ), patch("yoke_core.domain.path_claims.release"):
            resp = dispatch(_envelope(
                "claims.path.release",
                target={"kind": "item", "item_id": 1665},
                payload={"claim_id": 116, "reason": "done"},
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["claim_id"], 116)
        self.assertEqual(resp.result["state"], "released")

    def test_override_rejected_for_non_operator(self):
        """AC-6.4: non-operator session => operator_override_required."""
        with patch.object(claims_module, "is_operator_session", return_value=False):
            resp = dispatch(_envelope(
                "claims.path.override",
                target={"kind": "item", "item_id": 1665},
                payload={
                    "path_claim_id": 116,
                    "integration_target": "main",
                    "actor_id": 2,
                    "actor_reason": "operator forced override",
                },
            ))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "operator_override_required")

    def test_override_allowed_for_operator(self):
        with patch.object(claims_module, "is_operator_session", return_value=True), patch(
            "yoke_core.domain.path_claims_override.invoke_override",
            return_value="evt-1",
        ):
            resp = dispatch(_envelope(
                "claims.path.override",
                target={"kind": "item", "item_id": 1665},
                payload={
                    "path_claim_id": 116,
                    "integration_target": "main",
                    "actor_id": 2,
                    "actor_reason": "operator forced override",
                },
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["override_event_id"], "evt-1")

    def test_amend_aliases_widen(self):
        with self._hold_item_claim(), patch(
            "yoke_core.domain.path_claims_amend.widen",
            return_value=401,
        ):
            resp = dispatch(_envelope(
                "claims.path.amend",
                target={"kind": "item", "item_id": 1665},
                payload={
                    "claim_id": 116,
                    "add_target_ids": [2958],
                    "reason": "external amend verb",
                },
            ))
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["amendment_id"], 401)


if __name__ == "__main__":
    unittest.main()
