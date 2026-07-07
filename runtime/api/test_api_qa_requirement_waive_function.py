from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import qa_requirement_waive
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(function_id: str, target: TargetRef, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload or {},
    )


class TestQaRequirementWaive(unittest.TestCase):
    def test_rejects_missing_target(self):
        req = _request(
            "qa.requirement.waive",
            TargetRef(kind="global"),
            payload={"rationale": "not needed"},
        )
        outcome = qa_requirement_waive.handle_qa_requirement_waive(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_happy_path_calls_domain_helper(self):
        class _Conn:
            def close(self):
                pass

        with patch(
            "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
        ), patch(
            "yoke_core.domain.qa_requirement_ops.waive_requirement",
        ) as waive:
            req = _request(
                "qa.requirement.waive",
                TargetRef(kind="qa_requirement", qa_requirement_id=10),
                payload={
                    "rationale": "operator accepted risk",
                    "source": "operator",
                    "force": True,
                },
            )
            outcome = qa_requirement_waive.handle_qa_requirement_waive(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["requirement_id"], 10)
        waive.assert_called_once()
        self.assertEqual(waive.call_args.args[1], 10)
        self.assertEqual(waive.call_args.args[2], "operator accepted risk")
        self.assertEqual(waive.call_args.kwargs["source"], "operator")
        self.assertTrue(waive.call_args.kwargs["force"])

    def test_force_required_maps_to_structured_error(self):
        class _Conn:
            def close(self):
                pass

        with patch(
            "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
        ), patch(
            "yoke_core.domain.qa_requirement_ops.waive_requirement",
            side_effect=PermissionError("force required"),
        ):
            req = _request(
                "qa.requirement.waive",
                TargetRef(kind="qa_requirement", qa_requirement_id=10),
                payload={"rationale": "skip"},
            )
            outcome = qa_requirement_waive.handle_qa_requirement_waive(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "force_required")


if __name__ == "__main__":
    unittest.main()
