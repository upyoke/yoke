"""Handler coverage for claims.work.release_session_scoped."""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain.handlers import claims_work_release_session_scoped as handler
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(*, session_id: str = "sess-1", payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="claims.work.release_session_scoped",
        request_id="req-1",
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="global"),
        payload={} if payload is None else payload,
    )


class TestReleaseSessionScopedHandler(unittest.TestCase):
    def test_calls_domain_with_actor_session(self) -> None:
        with mock.patch(
            "yoke_core.domain.claims_work_release_session_scoped."
            "release_all_claims_for_session",
            return_value={"released_count": 1, "released_claims": []},
        ) as release:
            outcome = handler.handle_release_session_scoped(_request())

        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["released_count"], 1)
        release.assert_called_once_with("sess-1")

    def test_rejects_missing_session(self) -> None:
        outcome = handler.handle_release_session_scoped(
            _request(session_id="", payload={})
        )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("actor.session_id is required", outcome.error.message)

    def test_rejects_unexpected_payload_fields(self) -> None:
        outcome = handler.handle_release_session_scoped(
            _request(payload={"claim_id": 123})
        )

        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("Extra inputs are not permitted", outcome.error.message)


if __name__ == "__main__":
    unittest.main()
