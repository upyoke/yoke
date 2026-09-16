"""Which claim the dispatcher demands before a QA requirement write.

The dispatcher applies claim checks from registry metadata rather than
from each handler, so the gating is asserted against the registry itself.
Sibling of :mod:`runtime.api.test_api_qa_requirement_create_function`,
which covers what the handlers do once a call is past the gate.
"""

from __future__ import annotations

import unittest


class TestRegistryClaimGating(unittest.TestCase):
    """The dispatcher applies claim checks from registry metadata.

    Both CRUD writes are claim-gated and the reads are not. ``add`` serves
    two subjects through one id, so it carries the ``qa_subject`` policy the
    rest of QA writes under — an item case still needs the session's live
    item claim, while a run case is authorized by the run's project scope.
    ``add_batch`` stays item-attached, so it stays on the item claim.
    """

    def test_writes_claim_gated_reads_open(self):
        from yoke_core.domain import yoke_function_registry
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )

        register_all_handlers()
        entries = {
            e.function_id: e for e in yoke_function_registry.list_entries()
        }
        self.assertEqual(
            entries["qa.requirement.add"].claim_required_kind, "qa_subject",
        )
        self.assertEqual(
            tuple(entries["qa.requirement.add"].target_kinds),
            ("item", "deployment_run"),
        )
        self.assertEqual(
            entries["qa.requirement.add_batch"].claim_required_kind, "item",
        )
        for fid in ("qa.requirement.add", "qa.requirement.add_batch"):
            self.assertIn("claim_required", entries[fid].guardrails, fid)
            self.assertEqual(
                entries[fid].side_effects, ("qa_requirements_insert",), fid,
            )
        for fid in (
            "qa.requirement.list", "qa.requirement.get", "qa.run.list",
            "qa.gate_summary.run",
        ):
            self.assertIsNone(entries[fid].claim_required_kind, fid)
            self.assertEqual(entries[fid].side_effects, (), fid)


if __name__ == "__main__":
    unittest.main()
