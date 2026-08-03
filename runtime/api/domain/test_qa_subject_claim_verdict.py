"""Dispatcher authority for QA recording legs.

A ``qa_subject`` operation is admitted by the calling session's live item
claim, or — once the live claim is gone — by the claim the run bound when
it started. The second path is what lets an hour-long gate record the
verdict it earned after the stale-session sweep reclaimed the first.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain import qa_start_bound_authority as authority
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain import yoke_function_dispatch_qa_claims as qa_claims_module
from yoke_core.domain.qa_start_bound_authority import PAYLOAD_KEY
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import (
    register,
    reset_registry_for_tests,
)

_FUNCTION = "qatest.run.add"
_SESSION = "s-1"
_ITEM = 1981
_CLAIM = 7695
_REQUIREMENT = 9168


class _Req(BaseModel):
    execution_claim_id: int | None = None


class _Resp(BaseModel):
    pass


def _handler(_request):
    return HandlerOutcome(result_payload={"status": "ok"}, primary_success=True)


def _request(payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=_FUNCTION,
        actor=ActorContext(actor_id="op", session_id=_SESSION),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=_REQUIREMENT),
        payload=payload or {},
    )


class TestQaSubjectAuthority(unittest.TestCase):
    def setUp(self) -> None:
        reset_registry_for_tests()
        self._patchers = [
            patch.object(events_module, "emit_event"),
            patch.object(
                dispatch_module, "_idempotency_lookup", lambda *_a, **_k: None
            ),
            patch.dict("os.environ", {"YOKE_SESSION_ID": _SESSION}, clear=False),
            patch.object(
                qa_claims_module,
                "resolve_qa_requirement_subject",
                return_value=(_ITEM, None, None, None),
            ),
        ]
        for p in self._patchers:
            p.start()
        register(
            _FUNCTION,
            _handler,
            _Req,
            _Resp,
            stability="stable",
            owner_module="yoke_core.domain.test_qa_subject_claim_verdict",
            target_kinds=["qa_requirement"],
            side_effects=[],
            emitted_event_names=["FakeEvent"],
            guardrails=[],
            adapter_status="live",
            claim_required_kind="qa_subject",
        )

    def tearDown(self) -> None:
        for p in reversed(self._patchers):
            p.stop()
        reset_registry_for_tests()

    def test_live_claim_admits_the_write(self):
        with patch.object(
            claims_module,
            "who_claims_for_item",
            return_value={"id": _CLAIM, "session_id": _SESSION},
        ):
            response = dispatch(_request())
        self.assertTrue(response.success)

    def test_reclaimed_claim_without_start_bound_authority_is_refused(self):
        with patch.object(claims_module, "who_claims_for_item", return_value=None):
            response = dispatch(_request())
        self.assertFalse(response.success)
        assert response.error is not None
        self.assertEqual(response.error.code, "claim_required")

    def test_reclaimed_claim_with_start_bound_authority_still_records(self):
        # The regression: the sweep released the claim mid-run, and the
        # finished run records its verdict without reacquiring anything.
        released = (_SESSION, _ITEM, "2026-06-01T11:20:00Z")
        with (
            patch.object(claims_module, "who_claims_for_item", return_value=None),
            patch.object(authority, "_claim_row", return_value=released),
            patch.object(authority, "start_bound_claim_grants", return_value=True),
        ):
            response = dispatch(_request({PAYLOAD_KEY: _CLAIM}))
        self.assertTrue(response.success)

    def test_handoff_to_another_session_still_lets_the_run_record(self):
        with (
            patch.object(
                claims_module,
                "who_claims_for_item",
                return_value={"id": 1, "session_id": "s-other"},
            ),
            patch.object(authority, "start_bound_claim_grants", return_value=True),
        ):
            response = dispatch(_request({PAYLOAD_KEY: _CLAIM}))
        self.assertTrue(response.success)

    def test_a_claim_the_session_never_held_is_refused(self):
        with (
            patch.object(claims_module, "who_claims_for_item", return_value=None),
            patch.object(authority, "_claim_row", return_value=("s-other", _ITEM, None)),
        ):
            response = dispatch(_request({PAYLOAD_KEY: _CLAIM}))
        self.assertFalse(response.success)
        assert response.error is not None
        self.assertEqual(response.error.code, "claim_required")


if __name__ == "__main__":  # pragma: no cover - direct module run
    unittest.main()
