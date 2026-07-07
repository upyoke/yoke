"""Handler coverage for claims.path.list / claims.path.get."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import claims_path_reads
from yoke_core.domain.path_claims import PathClaimError
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


class TestClaimsPathList(unittest.TestCase):
    def test_rejects_non_item_target(self):
        outcome = claims_path_reads.handle_claims_path_list(
            _request("claims.path.list", TargetRef(kind="global"))
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_rejects_unknown_state(self):
        outcome = claims_path_reads.handle_claims_path_list(
            _request(
                "claims.path.list",
                TargetRef(kind="item", item_id=42),
                payload={"states": ["active", "wibbly"]},
            )
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")
        self.assertIn("wibbly", outcome.error.message)

    def test_passes_states_to_item_view(self):
        captured = {}

        def fake_item_view(conn, item_id, *, states=None):
            captured["item_id"] = item_id
            captured["states"] = states
            return [{"id": 7, "state": "active"}]

        with patch(
            "yoke_core.domain.path_claims_read.item_view",
            side_effect=fake_item_view,
        ), patch("yoke_core.domain.db_helpers.connect"):
            outcome = claims_path_reads.handle_claims_path_list(
                _request(
                    "claims.path.list",
                    TargetRef(kind="item", item_id=42),
                    payload={"states": ["active", "planned"]},
                )
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(captured["item_id"], 42)
        self.assertEqual(captured["states"], ["active", "planned"])
        self.assertEqual(outcome.result_payload["item_id"], 42)
        self.assertEqual(len(outcome.result_payload["claims"]), 1)

    def test_empty_states_means_all(self):
        captured = {}

        def fake_item_view(conn, item_id, *, states=None):
            captured["states"] = states
            return []

        with patch(
            "yoke_core.domain.path_claims_read.item_view",
            side_effect=fake_item_view,
        ), patch("yoke_core.domain.db_helpers.connect"):
            outcome = claims_path_reads.handle_claims_path_list(
                _request(
                    "claims.path.list", TargetRef(kind="item", item_id=42),
                )
            )
        self.assertTrue(outcome.primary_success)
        self.assertIsNone(captured["states"])


class TestClaimsPathGet(unittest.TestCase):
    def test_rejects_missing_path_claim_target(self):
        outcome = claims_path_reads.handle_claims_path_get(
            _request("claims.path.get", TargetRef(kind="global"))
        )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_returns_projection(self):
        with patch(
            "yoke_core.domain.path_claims_read.claim_projection",
            return_value={"id": 9, "state": "active", "declared_paths": []},
        ), patch("yoke_core.domain.db_helpers.connect"):
            outcome = claims_path_reads.handle_claims_path_get(
                _request(
                    "claims.path.get",
                    TargetRef(kind="path_claim", path_claim_id=9),
                )
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["claim"]["id"], 9)

    def test_not_found_maps_path_claim_error(self):
        with patch(
            "yoke_core.domain.path_claims_read.claim_projection",
            side_effect=PathClaimError("claim 999 not found"),
        ), patch("yoke_core.domain.db_helpers.connect"):
            outcome = claims_path_reads.handle_claims_path_get(
                _request(
                    "claims.path.get",
                    TargetRef(kind="path_claim", path_claim_id=999),
                )
            )
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "not_found")


if __name__ == "__main__":
    unittest.main()
