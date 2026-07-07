"""Tests for yoke_core.domain.item_field_transform_sections."""

from __future__ import annotations

import subprocess
import sys

import json
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from yoke_core.domain import (
    backlog_queries,
    backlog_rendering,
    backlog_structured_write_op,
    db_backend,
    item_field_transform,
    item_field_transform_sections as ifts,
    sections,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain._item_field_transform_test_helpers import (
    _FakeDB,
    _patched_db,
)

_FROZEN_NOW = datetime(2026, 5, 8, 16, 2, 2, tzinfo=timezone.utc)


def _frozen_now() -> datetime:
    return _FROZEN_NOW


class TestSectionModuleImports(unittest.TestCase):
    def test_sibling_module_is_directly_importable(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from yoke_core.domain import "
                    "item_field_transform_sections as ifts; "
                    "print(ifts.SECTION_APPEND)"
                ),
            ],
            cwd=Path(__file__).resolve().parents[3],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "section-append")


class TestSectionAppendCreates(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(401)

    def test_creates_missing_section_with_entry(self) -> None:
        result = ifts.section_append(
            item_id=401, section="Progress Log",
            headline="kicked off implementation", content="implementation begins",
            ordering=200, source="advance", now_fn=_frozen_now,
        )
        self.assertTrue(result.success)
        self.assertTrue(result.changed)
        self.assertEqual(result.verification, "ok")
        self.assertEqual(result.old_line_count, 0)
        self.assertGreater(result.new_line_count, 0)

        persisted = self.db.fetch_section(401, "Progress Log")
        self.assertIsNotNone(persisted)
        self.assertIn(
            "## 2026-05-08T16:02:02Z entry — kicked off implementation",
            persisted,
        )
        self.assertIn("implementation begins", persisted)
        self.assertEqual(self.db.fetch_section_ordering(401, "Progress Log"), 200)

    def test_appends_after_existing_section(self) -> None:
        first = ifts.section_append(
            item_id=401, section="Progress Log", headline="first",
            content="line one", ordering=200, source="advance",
            now_fn=lambda: datetime(2026, 5, 8, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(first.success)
        first_persisted = self.db.fetch_section(401, "Progress Log")
        self.assertIsNotNone(first_persisted)

        second = ifts.section_append(
            item_id=401, section="Progress Log", headline="second",
            content="line two", source="advance", now_fn=_frozen_now,
        )
        self.assertTrue(second.success)
        self.assertGreater(second.old_line_count, 0)
        self.assertGreater(second.new_line_count, second.old_line_count)

        persisted = self.db.fetch_section(401, "Progress Log")
        self.assertIsNotNone(persisted)
        # Both entries are present, ordered with first → second.
        self.assertIn("## 2026-05-08T00:00:00Z entry — first", persisted)
        self.assertIn("## 2026-05-08T16:02:02Z entry — second", persisted)
        first_idx = persisted.index("## 2026-05-08T00:00:00Z")
        second_idx = persisted.index("## 2026-05-08T16:02:02Z")
        self.assertLess(first_idx, second_idx)
        # Original content survives verbatim (preserved bytes).
        self.assertIn(first_persisted, persisted)
        # Blank-line separator between entries.
        self.assertIn("line one\n\n## 2026-05-08T16:02:02Z", persisted)


class TestSectionAppendRejects(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(402)

    def test_empty_section_rejected(self) -> None:
        result = ifts.section_append(
            item_id=402, section="", headline="x", content="y",
        )
        self.assertFalse(result.success)
        self.assertIn("section name is required", result.error)
        self.assertIsNone(self.db.fetch_section(402, ""))

    def test_empty_headline_rejected(self) -> None:
        result = ifts.section_append(
            item_id=402, section="Progress Log", headline="   ", content="body",
        )
        self.assertFalse(result.success)
        self.assertIn("headline is required", result.error)
        self.assertIsNone(self.db.fetch_section(402, "Progress Log"))

    def test_empty_content_rejected(self) -> None:
        result = ifts.section_append(
            item_id=402, section="Progress Log", headline="hi", content="\n\n",
        )
        self.assertFalse(result.success)
        self.assertIn("empty content", result.error)
        self.assertIsNone(self.db.fetch_section(402, "Progress Log"))

    def test_structured_field_name_rejected(self) -> None:
        result = ifts.section_append(
            item_id=402, section="spec", headline="x", content="y",
        )
        self.assertFalse(result.success)
        self.assertIn("structured field, not a section", result.error)


class TestSectionAppendVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(403)

    def test_render_failure_reports_render_failed(self) -> None:
        with mock.patch.object(sections, "_render_fn", return_value=1):
            result = ifts.section_append(
                item_id=403, section="Progress Log", headline="hi",
                content="body", now_fn=_frozen_now,
            )
        self.assertFalse(result.success)
        self.assertEqual(result.verification, "render-failed")
        self.assertIn("body render failed", result.error)
        # The section row was still written before the render attempt.
        self.assertIsNotNone(self.db.fetch_section(403, "Progress Log"))

    def test_post_write_verification_failure(self) -> None:
        # Stub get_section so the second call (verification) returns
        # content missing the appended headline; the helper must report
        # `verification="missing"` rather than silent success.
        with mock.patch.object(
            sections, "get_section",
            side_effect=["", "## stale\nold body\n"],
        ), mock.patch.object(sections, "upsert_section"):
            result = ifts.section_append(
                item_id=403, section="Progress Log",
                headline="never persisted", content="ghost body",
                now_fn=_frozen_now,
            )
        self.assertFalse(result.success)
        self.assertEqual(result.verification, "missing")
        self.assertIn("verification failed", result.error)


class TestSectionUpsertViaSibling(unittest.TestCase):
    """Existing `section_upsert` semantics preserved through the sibling."""

    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(404)

    def test_upsert_still_creates_section(self) -> None:
        result = ifts.section_upsert(
            item_id=404, section="Progress Log", content="full block",
            ordering=200, source="advance",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.verification, "ok")
        self.assertEqual(self.db.fetch_section(404, "Progress Log"), "full block")

    def test_upsert_re_export_from_parent_module(self) -> None:
        # Callers of `item_field_transform.section_upsert` keep the
        # same surface even though the implementation moved.
        self.assertIs(item_field_transform.section_upsert, ifts.section_upsert)
        self.assertIs(item_field_transform.section_append, ifts.section_append)


class TestSectionAppendCli(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(405)

    def test_section_append_via_cli_emits_evidence(self) -> None:
        with mock.patch("sys.stdin", StringIO("body content")), \
             mock.patch("sys.stdout", new_callable=StringIO) as stdout, \
             mock.patch.object(ifts, "_utc_now", _frozen_now):
            rc = item_field_transform.main([
                "section-append", "--item", "405",
                "--section", "Progress Log", "--headline", "kicked off",
                "--ordering", "200", "--source", "advance", "--stdin",
            ])
        self.assertEqual(rc, 0)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertTrue(evidence["success"])
        self.assertEqual(evidence["item_id"], 405)
        self.assertEqual(evidence["section"], "Progress Log")
        self.assertEqual(evidence["operation"], "section-append")
        self.assertTrue(evidence["changed"])
        self.assertEqual(evidence["verification"], "ok")
        self.assertEqual(evidence["old_line_count"], 0)
        self.assertGreater(evidence["new_line_count"], 0)

    def test_section_append_via_cli_rejects_empty_stdin(self) -> None:
        with mock.patch("sys.stdin", StringIO("")), \
             mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "section-append", "--item", "405",
                "--section", "Progress Log", "--headline", "x", "--stdin",
            ])
        self.assertEqual(rc, 1)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertFalse(evidence["success"])
        self.assertIn("empty content", evidence["error"])


if __name__ == "__main__":
    unittest.main()
