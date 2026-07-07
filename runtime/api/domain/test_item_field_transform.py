"""Tests for yoke_core.domain.item_field_transform."""

from __future__ import annotations

import json
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from yoke_core.domain import (
    backlog_queries,
    backlog_rendering,
    backlog_structured_write_op,
    db_backend,
    item_field_transform,
    sections,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain._item_field_transform_test_helpers import (
    _FakeDB,
    _patched_db,
)


class TestParseItemId(unittest.TestCase):
    def test_bare_integer(self) -> None:
        self.assertEqual(item_field_transform.parse_item_id("42"), 42)

    def test_sun_prefix_padded(self) -> None:
        self.assertEqual(item_field_transform.parse_item_id("007"), 7)

    def test_lowercase_prefix(self) -> None:
        self.assertEqual(item_field_transform.parse_item_id("9"), 9)

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            item_field_transform.parse_item_id("")

    def test_garbage_raises(self) -> None:
        with self.assertRaises(ValueError):
            item_field_transform.parse_item_id("YOK-abc")


class TestAppendAddendum(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)

    def test_appends_to_empty_field(self) -> None:
        self.db.insert_item(101, spec=None)
        result = item_field_transform.append_addendum(
            item_id=101, field="spec", heading="Refinement Addendum",
            content="line one\nline two", source="refine",
        )
        self.assertTrue(result.success)
        self.assertTrue(result.changed)
        self.assertEqual(result.verification, "ok")
        spec = self.db.fetch_item_field(101, "spec")
        self.assertIn("## Refinement Addendum", spec)
        self.assertIn("line one", spec)

    def test_appends_after_existing_content(self) -> None:
        self.db.insert_item(102, spec="# Spec\n\nintro paragraph\n")
        result = item_field_transform.append_addendum(
            item_id=102, field="spec", heading="Refinement Addendum",
            content="more detail", source="refine",
        )
        self.assertTrue(result.success)
        self.assertGreater(result.new_line_count, result.old_line_count)
        spec = self.db.fetch_item_field(102, "spec")
        self.assertIn("intro paragraph", spec)
        self.assertIn("## Refinement Addendum", spec)
        self.assertNotIn("intro paragraph## Refinement Addendum", spec)

    def test_idempotent_when_heading_present(self) -> None:
        existing = "# Spec\n\n## Refinement Addendum\nfirst pass\n"
        self.db.insert_item(103, spec=existing)
        result = item_field_transform.append_addendum(
            item_id=103, field="spec", heading="Refinement Addendum",
            content="duplicate try", source="refine",
        )
        self.assertTrue(result.success)
        self.assertFalse(result.changed)
        self.assertEqual(result.verification, "heading-already-present")
        self.assertEqual(self.db.fetch_item_field(103, "spec"), existing)

    def test_empty_content_rejected(self) -> None:
        self.db.insert_item(104, spec="existing")
        result = item_field_transform.append_addendum(
            item_id=104, field="spec", heading="Heading", content="   \n\n",
        )
        self.assertFalse(result.success)
        self.assertIn("empty content", result.error)
        self.assertEqual(self.db.fetch_item_field(104, "spec"), "existing")

    def test_invalid_field_rejected(self) -> None:
        result = item_field_transform.append_addendum(
            item_id=1, field="not_a_field", heading="X", content="y",
        )
        self.assertFalse(result.success)
        self.assertIn("invalid structured field", result.error)

    def test_missing_heading_rejected(self) -> None:
        result = item_field_transform.append_addendum(
            item_id=1, field="spec", heading="   ", content="y",
        )
        self.assertFalse(result.success)
        self.assertIn("heading is required", result.error)

    def test_shrinkage_guard_propagates(self) -> None:
        big = "\n".join(f"line-{i}" for i in range(40)) + "\n"
        self.db.insert_item(105, spec=big)
        with mock.patch.object(
            item_field_transform, "execute_structured_write",
            return_value={
                "success": False,
                "error": (
                    "refusing spec write for YOK-105: new content (3 lines)"
                    " is less than 50% of existing spec (41 lines)."
                ),
            },
        ):
            result = item_field_transform.append_addendum(
                item_id=105, field="spec", heading="Tiny", content="tiny",
            )
        self.assertFalse(result.success)
        self.assertIn("less than 50%", result.error)

    def test_post_write_verification_failure(self) -> None:
        self.db.insert_item(106, spec="")
        with mock.patch.object(
            item_field_transform, "_read_field",
            side_effect=["", "## Mismatch\nbody\n"],
        ):
            result = item_field_transform.append_addendum(
                item_id=106, field="spec",
                heading="Refinement Addendum", content="body",
            )
        self.assertFalse(result.success)
        self.assertEqual(result.verification, "missing")
        self.assertIn("verification failed", result.error)

    def test_sync_warning_surfaces_in_evidence(self) -> None:
        self.db.insert_item(107, spec="")
        with mock.patch.object(
            item_field_transform, "execute_structured_write",
            return_value={"success": True, "sync_warning": "sync_body failed"},
        ), mock.patch.object(
            item_field_transform,
            "_read_field",
            side_effect=["", "## Refinement Addendum\nbody\n"],
        ):
            result = item_field_transform.append_addendum(
                item_id=107, field="spec", heading="Refinement Addendum",
                content="body",
            )
        self.assertTrue(result.success)
        self.assertEqual(result.warning, "sync_body failed")


class TestSectionUpsert(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(201)

    def test_upserts_new_section(self) -> None:
        result = item_field_transform.section_upsert(
            item_id=201, section="Progress Log", content="entry one",
            ordering=200, source="refine",
        )
        self.assertTrue(result.success)
        self.assertEqual(
            self.db.fetch_section(201, "Progress Log"), "entry one",
        )

    def test_section_upsert_reports_render_failure(self) -> None:
        with mock.patch.object(sections, "_render_fn", return_value=1):
            result = item_field_transform.section_upsert(
                item_id=201, section="Progress Log", content="entry one",
            )
        self.assertFalse(result.success)
        self.assertEqual(result.verification, "render-failed")
        self.assertIn("body render failed", result.error)
        self.assertEqual(
            self.db.fetch_section(201, "Progress Log"), "entry one",
        )

    def test_empty_section_rejected(self) -> None:
        result = item_field_transform.section_upsert(
            item_id=201, section="", content="x",
        )
        self.assertFalse(result.success)
        self.assertIn("section name is required", result.error)

    def test_empty_content_rejected(self) -> None:
        result = item_field_transform.section_upsert(
            item_id=201, section="Progress Log", content="",
        )
        self.assertFalse(result.success)
        self.assertIn("empty content", result.error)

    def test_structured_field_name_rejected(self) -> None:
        result = item_field_transform.section_upsert(
            item_id=201, section="spec", content="hello",
        )
        self.assertFalse(result.success)
        self.assertIn("structured field, not a section", result.error)


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)

    def test_append_addendum_via_cli(self) -> None:
        self.db.insert_item(301, spec="initial")
        with mock.patch("sys.stdin", StringIO("body content")), \
             mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "append-addendum", "--item", "301",
                "--field", "spec", "--heading", "Refinement Addendum",
                "--source", "refine", "--stdin",
            ])
        self.assertEqual(rc, 0)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertTrue(evidence["success"])
        self.assertEqual(evidence["item_id"], 301)
        self.assertEqual(evidence["field"], "spec")
        self.assertEqual(evidence["operation"], "append-addendum")
        self.assertTrue(evidence["changed"])
        self.assertEqual(evidence["verification"], "ok")

    def test_invalid_item_id_returns_nonzero(self) -> None:
        with mock.patch("sys.stdin", StringIO("body content")), \
             mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "append-addendum", "--item", "not-an-id",
                "--field", "spec", "--heading", "X", "--stdin",
            ])
        self.assertEqual(rc, 1)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertFalse(evidence["success"])

    def test_section_upsert_via_cli(self) -> None:
        self.db.insert_item(302)
        with mock.patch("sys.stdin", StringIO("first entry")), \
             mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "section-upsert", "--item", "302",
                "--section", "Progress Log", "--ordering", "200",
                "--source", "refine", "--stdin",
            ])
        self.assertEqual(rc, 0)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertTrue(evidence["success"])
        self.assertEqual(evidence["section"], "Progress Log")
