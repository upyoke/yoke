"""Registered path-claim writes preserve their handler contracts."""

from unittest.mock import MagicMock, patch

from runtime.api.test_api_claims_functions import _ClaimsHandlerSuite, _envelope
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain.yoke_function_dispatch import dispatch


class TestClaimsPath(_ClaimsHandlerSuite):
    def _hold_item_claim(self):
        return patch.object(
            claims_module,
            "who_claims_for_item",
            return_value={"id": 1, "session_id": "s-1"},
        )

    def test_register_routes_to_register_for_item(self):
        """Register accepts paths/target ids/integration target."""
        with (
            self._hold_item_claim(),
            patch(
                "yoke_core.domain.path_claims_register.register_for_item",
                return_value=555,
            ),
        ):
            resp = dispatch(
                _envelope(
                    "claims.path.register",
                    target={"kind": "item", "item_id": 1665},
                    payload={
                        "item_id": 1665,
                        "integration_target": "main",
                        "paths": ["runtime/api/x.py", "runtime/api/y.py"],
                        "allow_planned": True,
                    },
                )
            )
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["claim_id"], 555)

    def test_register_overlap_returns_denial_body(self):
        from yoke_core.domain.path_claims import IncompatibleOverlap

        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        denial = (
            "BLOCKED: path-claim register overlap on item YOK-1665.\n"
            "  conflicting claims:\n"
            "    claim 300: .yoke/docs/reference/db-reference/functions.md"
        )
        with (
            self._hold_item_claim(),
            patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=mock_conn,
            ),
            patch(
                "yoke_core.domain.path_claims_register_validate_integration_target."
                "resolve_and_validate_integration_target",
                return_value="main",
            ),
            patch(
                "yoke_core.domain.path_claims_register.register_for_item",
                side_effect=IncompatibleOverlap("raw overlap"),
            ),
            patch(
                "yoke_core.domain.handlers.claims_path."
                "render_overlap_denial_for_register",
                return_value=denial,
            ) as render_denial,
        ):
            resp = dispatch(
                _envelope(
                    "claims.path.register",
                    target={"kind": "item", "item_id": 1665},
                    payload={
                        "item_id": 1665,
                        "integration_target": "main",
                        "paths": [".yoke/docs/reference/db-reference/functions.md"],
                        "allow_planned": True,
                    },
                    actor_id=None,
                )
            )
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "register_failed")
        self.assertIn("BLOCKED: path-claim register overlap", resp.error.message)
        self.assertIn("claim 300", resp.error.message)
        self.assertIn(
            ".yoke/docs/reference/db-reference/functions.md", resp.error.message
        )
        render_denial.assert_called_once()

    def test_release_routes_to_path_claims_release(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = {
            "state": "released",
            "released_at": "2026-05-13T07:00:00Z",
        }
        with (
            self._hold_item_claim(),
            patch(
                "yoke_core.domain.db_helpers.connect",
                return_value=mock_conn,
            ),
            patch("yoke_core.domain.path_claims.release"),
        ):
            resp = dispatch(
                _envelope(
                    "claims.path.release",
                    target={"kind": "item", "item_id": 1665},
                    payload={"claim_id": 116, "reason": "done"},
                )
            )
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["claim_id"], 116)
        self.assertEqual(resp.result["state"], "released")

    def test_override_rejected_for_non_operator(self):
        """Non-operator session => operator_override_required."""
        with patch.object(claims_module, "is_operator_session", return_value=False):
            resp = dispatch(
                _envelope(
                    "claims.path.override",
                    target={"kind": "item", "item_id": 1665},
                    payload={
                        "path_claim_id": 116,
                        "integration_target": "main",
                        "actor_id": 2,
                        "actor_reason": "operator forced override",
                    },
                )
            )
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "operator_override_required")

    def test_override_allowed_for_operator(self):
        with (
            patch.object(claims_module, "is_operator_session", return_value=True),
            patch(
                "yoke_core.domain.path_claims_override.invoke_override",
                return_value="evt-1",
            ),
        ):
            resp = dispatch(
                _envelope(
                    "claims.path.override",
                    target={"kind": "item", "item_id": 1665},
                    payload={
                        "path_claim_id": 116,
                        "integration_target": "main",
                        "actor_id": 2,
                        "actor_reason": "operator forced override",
                    },
                )
            )
        self.assertTrue(resp.success, msg=resp.error)
        self.assertEqual(resp.result["override_event_id"], "evt-1")
