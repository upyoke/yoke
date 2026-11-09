"""Architecture declarations are validated at the structured-write boundary."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.api.domain.backlog_structured_write_api_test_support import (
    _FakeDB,
    _patched_db,
)
from runtime.api.domain.test_backlog_structured_write_api import _request
from yoke_core.domain.architecture_impact import ALLOWED_VALUES
from yoke_core.domain.backlog_structured_write_op import execute_structured_write
from yoke_core.domain.handlers import items_structured_field


class TestArchitectureImpactStructuredWrite(unittest.TestCase):
    def setUp(self):
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(101, architecture_impact="none")

    def test_invalid_declarations_refuse_without_changing_stored_value(self):
        for content in ("none: rationale", '{"classification":"none"}', "guess"):
            with self.subTest(content=content):
                outcome = items_structured_field.handle_replace(_request(
                    "items.structured_field.replace",
                    {"field": "architecture_impact", "content": content},
                ))
                self.assertFalse(outcome.primary_success)
                self.assertEqual(outcome.error.code, "validation_failed")
                for value in ALLOWED_VALUES:
                    self.assertIn(value, outcome.error.message)
                self.assertIn("put the reasoning in the spec", outcome.error.message)
                self.assertEqual(self.db.fetch_field(101, "architecture_impact"), "none")

    def test_normalized_values_persist_and_verify(self):
        for value in sorted(ALLOWED_VALUES):
            with self.subTest(value=value):
                content = f"  {value.upper()}\n"
                outcome = items_structured_field.handle_replace(_request(
                    "items.structured_field.replace",
                    {"field": "architecture_impact", "content": content},
                ))
                self.assertTrue(outcome.primary_success)
                self.assertEqual(self.db.fetch_field(101, "architecture_impact"), value)
                self.assertEqual(outcome.result_payload["verification"], "ok")
                self.assertEqual(outcome.result_payload["payload_byte_count"], len(content))

    def test_normalized_comparison_still_detects_drift(self):
        with mock.patch.object(items_structured_field, "_read_field", side_effect=[
            "none", "uncertain",
        ]):
            outcome = items_structured_field.handle_replace(_request(
                "items.structured_field.replace",
                {"field": "architecture_impact", "content": "path_context_only\n"},
            ))
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["verification"], "drift")

    def test_file_input_normalizes_and_repeated_write_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "impact.txt"
            path.write_text("none\n")
            result = execute_structured_write(
                101, "architecture_impact", file_path=str(path), out=io.StringIO(),
            )
        self.assertTrue(result["success"])
        self.assertFalse(result["changed"])
        self.assertEqual(self.db.fetch_field(101, "architecture_impact"), "none")

    def test_direct_empty_write_refuses_even_when_empty_is_allowed_by_handler(self):
        result = execute_structured_write(101, "architecture_impact", content="\n")
        self.assertFalse(result["success"])
        self.assertIn("expected one of", result["error"])
        self.assertEqual(self.db.fetch_field(101, "architecture_impact"), "none")
