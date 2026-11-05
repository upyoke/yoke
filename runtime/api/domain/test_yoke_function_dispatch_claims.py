"""Claim-verification matrix for the dispatcher.

Split out of :mod:`test_yoke_function_dispatch` so the dispatcher test
module stays under the file-line budget. Exercises every
``claim_required_kind`` value against a synthetic session/claim row
factory (no live DB).
"""

from __future__ import annotations

from runtime.api.domain.yoke_function_dispatch_claims_test_support import (_ClaimMatrixSuite as _ClaimMatrixSuite, _Req as _Req, _Resp as _Resp, _make_request as _make_request, _stable_kwargs as _stable_kwargs)
from runtime.api.domain.yoke_function_dispatch_test_support import (_ok_handler as _ok_handler)


import unittest
from unittest.mock import patch


from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import (
    register,
)


class TestClaimRequiredPaths(_ClaimMatrixSuite):
    """Exercise every claim_required_kind value."""

    def test_none_kind_runs_handler_regardless(self):
        register(
            "noclaim.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(),
            claim_required_kind=None,
        )
        with patch.object(claims_module, "who_claims_for_item", return_value=None):
            resp = dispatch(_make_request("noclaim.family.op"))
        self.assertTrue(resp.success)

    def test_item_kind_passes_when_session_matches(self):
        register(
            "itemclaim.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(),
            claim_required_kind="item",
        )
        with patch.object(
            claims_module,
            "who_claims_for_item",
            return_value={"id": 1, "session_id": "s-1"},
        ):
            resp = dispatch(_make_request("itemclaim.family.op"))
        self.assertTrue(resp.success)

    def test_item_kind_fails_on_mismatch(self):
        register(
            "itemclaim2.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(),
            claim_required_kind="item",
        )
        with patch.object(
            claims_module,
            "who_claims_for_item",
            return_value={"id": 1, "session_id": "OTHER"},
        ):
            resp = dispatch(_make_request("itemclaim2.family.op"))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")
        self.assertIn("yoke claims work acquire", resp.error.message)
        self.assertNotIn("service_client", resp.error.message)

    def test_item_kind_fails_when_no_claim(self):
        register(
            "itemclaim3.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(),
            claim_required_kind="item",
        )
        with patch.object(
            claims_module,
            "who_claims_for_item",
            return_value=None,
        ):
            resp = dispatch(_make_request("itemclaim3.family.op"))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")
        self.assertIn("yoke claims work acquire", resp.error.message)
        self.assertNotIn("service_client", resp.error.message)

    def test_item_claim_recovery_uses_the_public_project_ref(self):
        register(
            "itemclaimpublic.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(),
            claim_required_kind="item",
        )
        public_ref = "BUZZ-7"
        with (
            patch.object(claims_module, "who_claims_for_item", return_value=None),
            patch.object(
                claims_module,
                "_claim_recovery_item_ref",
                return_value=public_ref,
            ),
        ):
            resp = dispatch(_make_request("itemclaimpublic.family.op"))

        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertIn(f"item {public_ref}", resp.error.message)
        self.assertIn(f"--item {public_ref}", resp.error.message)
        self.assertNotIn("--item YOK-42", resp.error.message)

    def test_claim_recovery_ref_uses_the_canonical_renderer(self):
        public_ref = "BUZZ-7"
        with (
            patch("yoke_core.domain.db_helpers.connect") as connect,
            patch(
                "yoke_core.domain.project_identity.render_item_ref",
                return_value=public_ref,
            ) as render_item_ref,
        ):
            result = claims_module._claim_recovery_item_ref(42)

        self.assertEqual(result, public_ref)
        render_item_ref.assert_called_once_with(
            connect.return_value.__enter__.return_value,
            42,
        )

    def test_epic_kind_resolves_epic_id(self):
        register(
            "epicclaim.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(target_kinds=["epic_task"]),
            claim_required_kind="epic",
        )
        with patch.object(
            claims_module,
            "who_claims_for_item",
            return_value={"id": 7, "session_id": "s-1"},
        ):
            resp = dispatch(
                _make_request(
                    "epicclaim.family.op",
                    kind="epic_task",
                    item_id=0,
                    epic_id=1665,
                    task_num=1,
                )
            )
        self.assertTrue(resp.success)

    def test_self_only_kind_passes_when_owner_matches(self):
        register(
            "selfclaim.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(target_kinds=["claim"]),
            claim_required_kind="self_only",
        )
        with patch.object(
            claims_module,
            "_claim_row_for_id",
            return_value={"id": 99, "session_id": "s-1"},
        ):
            req = _make_request(
                "selfclaim.family.op",
                kind="claim",
                item_id=0,
                claim_id=99,
            )
            resp = dispatch(req)
        self.assertTrue(resp.success)

    def test_self_only_kind_fails_on_mismatch(self):
        register(
            "selfclaim2.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(target_kinds=["claim"]),
            claim_required_kind="self_only",
        )
        with patch.object(
            claims_module,
            "_claim_row_for_id",
            return_value={"id": 99, "session_id": "OTHER"},
        ):
            req = _make_request(
                "selfclaim2.family.op",
                kind="claim",
                item_id=0,
                claim_id=99,
            )
            resp = dispatch(req)
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")
        self.assertIn("yoke claims work release --claim-id 99", resp.error.message)
        self.assertNotIn("terminate", resp.error.message)
        self.assertNotIn("service_client", resp.error.message)

    def test_operator_override_passes_for_operator(self):
        register(
            "opclaim.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(target_kinds=["global"]),
            claim_required_kind="steering",
        )
        with patch.object(
            claims_module,
            "steering_seat_for_request",
            return_value=({"claim_id": 5}, "alpha"),
        ):
            req = _make_request("opclaim.family.op", kind="global", item_id=0)
            resp = dispatch(req)
        self.assertTrue(resp.success)

    def test_operator_override_fails_for_non_operator(self):
        register(
            "opclaim2.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(target_kinds=["global"]),
            claim_required_kind="steering",
        )
        with patch.object(
            claims_module, "steering_seat_for_request", return_value=(None, "alpha")
        ):
            req = _make_request("opclaim2.family.op", kind="global", item_id=0)
            resp = dispatch(req)
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "steering_seat_required")
        self.assertIn("yoke say --steering", resp.error.recovery_hint or "")
        self.assertIn("live steering seat", resp.error.message)


if __name__ == "__main__":
    unittest.main()
