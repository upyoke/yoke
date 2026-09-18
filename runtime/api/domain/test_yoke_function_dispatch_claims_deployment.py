"""Claim verification for deployment-scoped dispatch targets.

Sibling of :mod:`test_yoke_function_dispatch_claims`, which is at its
authored-file limit. Shares that module's registry scaffolding rather than
rebuilding it, because these cases differ only in the target they dispatch
against.
"""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.test_yoke_function_dispatch_claims import (
    _ClaimMatrixSuite,
    _make_request,
    _ok_handler,
    _Req,
    _Resp,
    _stable_kwargs,
    claims_module,
    dispatch,
    register,
)


class DeploymentTargetClaimSuite(_ClaimMatrixSuite):
    def test_item_kind_resolves_the_member_of_a_deployment_target(self):
        """An item-scoped deployment stage names its member in the payload.

        Without this the item claim check has no id to look up, so every
        deployment-form call is refused however the caller is claimed --
        which made the deployment subject unreachable in practice.
        """
        register(
            "deployclaim.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(),
            claim_required_kind="item",
        )
        with patch.object(
            claims_module,
            "_resolve_deployment_member_item_id",
            return_value=(77, None, None),
        ), patch.object(
            claims_module,
            "who_claims_for_item",
            return_value={"id": 1, "session_id": "s-1"},
        ) as holder:
            resp = dispatch(
                _make_request(
                    "deployclaim.family.op",
                    kind="deployment_run",
                    deployment_run_id="run-20260918-008",
                    payload={"deployment_member": "YOK-1927"},
                )
            )
        self.assertTrue(resp.success, resp.error)
        holder.assert_called_once_with(77)

    def test_deployment_target_without_a_member_still_refuses(self):
        register(
            "deployclaim2.family.op",
            _ok_handler,
            _Req,
            _Resp,
            **_stable_kwargs(),
            claim_required_kind="item",
        )
        resp = dispatch(
            _make_request(
                "deployclaim2.family.op",
                kind="deployment_run",
                deployment_run_id="run-20260918-008",
            )
        )
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")
