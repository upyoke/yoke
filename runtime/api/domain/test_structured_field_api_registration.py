"""Structured-field API registrations carry their required side effects."""

import unittest

from yoke_core.domain.handlers import items_structured_field_models as _models


class TestRegistrations(unittest.TestCase):
    def test_models_module_composes_four_registrations(self) -> None:
        entries = _models.build_registrations()
        ids = {e["function_id"] for e in entries}
        self.assertEqual(
            ids,
            {
                "items.structured_field.replace",
                "items.structured_field.append_addendum",
                "items.structured_field.section_upsert",
                "items.structured_field.section_append",
            },
        )
        for entry in entries:
            self.assertEqual(entry["claim_required_kind"], "item")
            self.assertIn("render_body", entry["side_effects"])
            self.assertIn("github_sync", entry["side_effects"])
