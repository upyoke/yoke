"""AC-1.16 claim-verification matrix for the dispatcher.

Split out of :mod:`test_yoke_function_dispatch` so the dispatcher test
module stays under the file-line budget. Exercises every
``claim_required_kind`` value against a synthetic session/claim row
factory (no live DB).
"""

from __future__ import annotations

import unittest
from typing import Optional
from unittest.mock import patch

from pydantic import BaseModel

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)


class _Req(BaseModel):
    pass


class _Resp(BaseModel):
    pass


def _stable_kwargs(**overrides):
    base = {
        "stability": "stable",
        "owner_module": "yoke_core.domain.test_dispatch_claims",
        "target_kinds": ["item"],
        "side_effects": [],
        "emitted_event_names": ["FakeEvent"],
        "guardrails": [],
        "adapter_status": "live",
    }
    base.update(overrides)
    return base


def _ok_handler(_request):
    return HandlerOutcome(result_payload={"status": "ok"}, primary_success=True)


def _make_request(
    function: str,
    *,
    item_id: int = 42,
    session_id: str = "s-1",
    kind: str = "item",
    epic_id: Optional[int] = None,
    task_num: Optional[int] = None,
    claim_id: Optional[int] = None,
) -> FunctionCallRequest:
    target = TargetRef(
        kind=kind,
        item_id=item_id if kind == "item" else None,
        epic_id=epic_id,
        task_num=task_num,
        claim_id=claim_id,
    )
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id=session_id),
        target=target,
    )


class _ClaimMatrixSuite(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()
        self._patchers = [
            patch.object(events_module, "emit_event"),
            patch.object(
                dispatch_module, "_idempotency_lookup",
                lambda *_a, **_k: None,
            ),
            # Bind ambient session to the same id the test envelopes use so the
            # dispatcher's actor-identity gate stays out of the way and the
            # verify_claim matrix below is what actually runs.
            patch.dict(
                "os.environ", {"YOKE_SESSION_ID": "s-1"}, clear=False,
            ),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()


class TestClaimRequiredPaths(_ClaimMatrixSuite):
    """AC-1.16: exercise every claim_required_kind value."""

    def test_none_kind_runs_handler_regardless(self):
        register(
            "noclaim.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(), claim_required_kind=None,
        )
        with patch.object(claims_module, "who_claims_for_item", return_value=None):
            resp = dispatch(_make_request("noclaim.family.op"))
        self.assertTrue(resp.success)

    def test_item_kind_passes_when_session_matches(self):
        register(
            "itemclaim.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(), claim_required_kind="item",
        )
        with patch.object(
            claims_module, "who_claims_for_item",
            return_value={"id": 1, "session_id": "s-1"},
        ):
            resp = dispatch(_make_request("itemclaim.family.op"))
        self.assertTrue(resp.success)

    def test_item_kind_fails_on_mismatch(self):
        register(
            "itemclaim2.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(), claim_required_kind="item",
        )
        with patch.object(
            claims_module, "who_claims_for_item",
            return_value={"id": 1, "session_id": "OTHER"},
        ):
            resp = dispatch(_make_request("itemclaim2.family.op"))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")

    def test_item_kind_fails_when_no_claim(self):
        register(
            "itemclaim3.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(), claim_required_kind="item",
        )
        with patch.object(
            claims_module, "who_claims_for_item", return_value=None,
        ):
            resp = dispatch(_make_request("itemclaim3.family.op"))
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")

    def test_epic_kind_resolves_epic_id(self):
        register(
            "epicclaim.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(target_kinds=["epic_task"]),
            claim_required_kind="epic",
        )
        with patch.object(
            claims_module, "who_claims_for_item",
            return_value={"id": 7, "session_id": "s-1"},
        ):
            resp = dispatch(_make_request(
                "epicclaim.family.op",
                kind="epic_task", item_id=0, epic_id=1665, task_num=1,
            ))
        self.assertTrue(resp.success)

    def test_self_only_kind_passes_when_owner_matches(self):
        register(
            "selfclaim.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(target_kinds=["claim"]),
            claim_required_kind="self_only",
        )
        with patch.object(
            claims_module, "_claim_row_for_id",
            return_value={"id": 99, "session_id": "s-1"},
        ):
            req = _make_request(
                "selfclaim.family.op",
                kind="claim", item_id=0, claim_id=99,
            )
            resp = dispatch(req)
        self.assertTrue(resp.success)

    def test_self_only_kind_fails_on_mismatch(self):
        register(
            "selfclaim2.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(target_kinds=["claim"]),
            claim_required_kind="self_only",
        )
        with patch.object(
            claims_module, "_claim_row_for_id",
            return_value={"id": 99, "session_id": "OTHER"},
        ):
            req = _make_request(
                "selfclaim2.family.op",
                kind="claim", item_id=0, claim_id=99,
            )
            resp = dispatch(req)
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "claim_required")

    def test_operator_override_passes_for_operator(self):
        register(
            "opclaim.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(target_kinds=["global"]),
            claim_required_kind="operator_override",
        )
        with patch.object(claims_module, "is_operator_session", return_value=True):
            req = _make_request("opclaim.family.op", kind="global", item_id=0)
            resp = dispatch(req)
        self.assertTrue(resp.success)

    def test_operator_override_fails_for_non_operator(self):
        register(
            "opclaim2.family.op", _ok_handler, _Req, _Resp,
            **_stable_kwargs(target_kinds=["global"]),
            claim_required_kind="operator_override",
        )
        with patch.object(claims_module, "is_operator_session", return_value=False):
            req = _make_request("opclaim2.family.op", kind="global", item_id=0)
            resp = dispatch(req)
        self.assertFalse(resp.success)
        assert resp.error is not None
        self.assertEqual(resp.error.code, "operator_override_required")


if __name__ == "__main__":
    unittest.main()
