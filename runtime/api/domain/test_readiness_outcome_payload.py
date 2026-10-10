"""Readiness repair outcomes omit empty optional payload fields."""

import unittest

from yoke_core.domain import idea_readiness_repair


class TestRepairOutcomePayload(unittest.TestCase):
    def test_payload_omits_empty_optional_fields(self):
        outcome = idea_readiness_repair.RepairOutcome(
            success=True,
            classification=idea_readiness_repair.CLASS_PURE_STALE_COUNT,
            item_id=42,
            repaired_paths=[idea_readiness_repair.RepairedPath("a.py", 10, 12)],
            field_written="spec",
            rerun_verdict="pass",
            audit_emitted=True,
        )
        payload = outcome.to_payload()
        self.assertTrue(payload["success"])
        for k in ("repaired_paths", "field_written", "rerun_verdict", "audit_emitted"):
            self.assertIn(k, payload)
        for k in ("error", "refused_paths", "rerun_issues"):
            self.assertNotIn(k, payload)
