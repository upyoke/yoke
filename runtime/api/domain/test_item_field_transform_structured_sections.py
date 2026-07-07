"""Regression coverage for ``section_upsert``'s structured-field routing.

Sibling of :mod:`test_item_field_transform_sections`. Focused on the
in-field replacement path added so a ``section-upsert`` whose heading is
already rendered by a structured field replaces in-field rather than
writing a duplicate ``item_sections`` row. Imports the existing test
fixtures (``_FakeDB`` and ``_patched_db``) from the sibling so the
schema setup and module patching stay DRY.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import (
    db_backend,
    item_field_transform_sections as ifts,
    render_body_section,
)
from runtime.api.domain.test_item_field_transform_sections import (
    _FakeDB, _patched_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _set_field(db: _FakeDB, item_id: int, field: str, value: str) -> None:
    with connect_test_db(db.path) as conn:
        p = _placeholder(conn)
        conn.execute(
            f"UPDATE items SET {field} = {p} WHERE id = {p}",
            (value, item_id),
        )


def _fetch_field(db: _FakeDB, item_id: int, field: str) -> str:
    with connect_test_db(db.path) as conn:
        p = _placeholder(conn)
        row = conn.execute(
            f"SELECT {field} FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
    return row[0] if row and row[0] is not None else ""


SPEC_WITH_FILE_BUDGET = (
    "# Spec: example\n\n"
    "## Overview\n\nsome overview\n\n"
    "## File Budget\n\nold budget content\n\n"
    "## Verified surfaces\n\ntail content\n"
)


class TestSectionUpsertRoutesToStructuredField(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(501)
        _set_field(self.db, 501, "spec", SPEC_WITH_FILE_BUDGET)

    def test_single_match_replaces_in_field(self) -> None:
        result = ifts.section_upsert(
            item_id=501, section="File Budget",
            content="brand new budget\n", source="refine",
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.field, "spec")
        self.assertEqual(result.verification, "ok")
        self.assertTrue(result.changed)
        # No item_sections row created on the in-field path.
        self.assertIsNone(self.db.fetch_section(501, "File Budget"))
        # Spec contains the new body and not the old body.
        spec_after = _fetch_field(self.db, 501, "spec")
        self.assertIn("brand new budget", spec_after)
        self.assertNotIn("old budget content", spec_after)
        # Surrounding sections are preserved.
        self.assertIn("## Overview", spec_after)
        self.assertIn("some overview", spec_after)
        self.assertIn("## Verified surfaces", spec_after)
        self.assertIn("tail content", spec_after)

    def test_pre_and_post_bytes_preserved_around_replacement(self) -> None:
        # The bytes before the replaced heading and from the next sibling
        # heading onward must be preserved verbatim.
        before_section = SPEC_WITH_FILE_BUDGET.split("## File Budget", 1)[0]
        after_section = "## Verified surfaces\n\ntail content\n"
        result = ifts.section_upsert(
            item_id=501, section="File Budget", content="new body", source="refine",
        )
        self.assertTrue(result.success, result.error)
        spec_after = _fetch_field(self.db, 501, "spec")
        self.assertTrue(spec_after.startswith(before_section), spec_after)
        self.assertIn(after_section.rstrip("\n"), spec_after)

    def test_fenced_code_block_does_not_match_heading(self) -> None:
        # A "## File Budget" inside a fenced code block must not count
        # as the top-level section. With no top-level heading present,
        # the upsert falls through to the item_sections row.
        fenced_spec = (
            "## Overview\n\nintro\n\n"
            "```\n"
            "## File Budget\nfake heading inside fence\n"
            "```\n\n"
            "## End\n\ntail\n"
        )
        _set_field(self.db, 501, "spec", fenced_spec)
        result = ifts.section_upsert(
            item_id=501, section="File Budget", content="real budget", source="refine",
        )
        self.assertTrue(result.success, result.error)
        # Fell through to item_sections, not in-field.
        self.assertEqual(result.field, "")
        self.assertEqual(
            self.db.fetch_section(501, "File Budget"), "real budget",
        )


class TestSectionUpsertFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(502)
        _set_field(self.db, 502, "spec", "## Overview\n\nintro only\n")

    def test_no_field_match_creates_item_sections_row(self) -> None:
        result = ifts.section_upsert(
            item_id=502, section="Brand New Heading",
            content="fresh content", source="refine",
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.field, "")
        self.assertEqual(result.verification, "ok")
        self.assertEqual(
            self.db.fetch_section(502, "Brand New Heading"), "fresh content",
        )
        spec_after = _fetch_field(self.db, 502, "spec")
        self.assertEqual(spec_after, "## Overview\n\nintro only\n")


class TestSectionUpsertAmbiguousHeading(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(503)
        _set_field(self.db, 503, "spec", "## Shared\n\nin spec\n")
        _set_field(
            self.db, 503, "design_spec", "## Shared\n\nin design_spec\n",
        )

    def test_multiple_matches_refuse_to_write(self) -> None:
        result = ifts.section_upsert(
            item_id=503, section="Shared", content="ambiguous body",
            source="refine",
        )
        self.assertFalse(result.success)
        self.assertIn("multiple", result.error)
        self.assertIn("spec", result.error)
        self.assertIn("design_spec", result.error)
        # No write happened anywhere.
        self.assertIsNone(self.db.fetch_section(503, "Shared"))
        self.assertEqual(
            _fetch_field(self.db, 503, "spec"), "## Shared\n\nin spec\n",
        )
        self.assertEqual(
            _fetch_field(self.db, 503, "design_spec"),
            "## Shared\n\nin design_spec\n",
        )


class TestSectionUpsertWriteFailure(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)
        self.db.insert_item(504)
        _set_field(self.db, 504, "spec", SPEC_WITH_FILE_BUDGET)

    def test_structured_write_failure_surfaces_no_fallback(self) -> None:
        from yoke_core.domain import backlog_structured_write_op as _op
        with mock.patch.object(
            _op, "execute_structured_write",
            return_value={"success": False, "error": "synthetic write error"},
        ):
            result = ifts.section_upsert(
                item_id=504, section="File Budget", content="new body",
                source="refine",
            )
        self.assertFalse(result.success)
        self.assertEqual(result.field, "spec")
        self.assertIn("synthetic write error", result.error)
        # The in-field path must NOT fall back to item_sections after
        # the structured write reports failure.
        self.assertIsNone(self.db.fetch_section(504, "File Budget"))

    def test_post_write_verification_detects_missing_heading(self) -> None:
        # Simulate a write that "succeeded" but the verifying re-read
        # returns content without the heading (e.g., the underlying
        # writer dropped it). The helper must report `missing`.
        original_read = ifts._read_field
        call_count = {"n": 0}

        def stub_read(item_id: int, field: str):
            call_count["n"] += 1
            # First call is the pre-write field read; second is the
            # post-write verification read.
            if call_count["n"] == 1:
                return original_read(item_id, field)
            return "## Other heading\nbody\n"

        with mock.patch.object(ifts, "_read_field", side_effect=stub_read):
            result = ifts.section_upsert(
                item_id=504, section="File Budget", content="new body",
                source="refine",
            )
        self.assertFalse(result.success)
        self.assertEqual(result.verification, "missing")
        self.assertIn("verification failed", result.error)


class TestReplaceSectionHelperBehavior(unittest.TestCase):
    """Direct coverage of the pure helper exposed by render_body_section."""

    def test_replaces_middle_section_preserving_neighbors(self) -> None:
        content = "## A\nfirst\n\n## B\nmiddle\n\n## C\nlast\n"
        out = render_body_section.replace_section(content, "B", "new middle")
        self.assertIsNotNone(out)
        self.assertIn("## A\nfirst", out)
        self.assertIn("## B\n\nnew middle\n", out)
        self.assertIn("## C\nlast", out)
        self.assertNotIn("middle\n", out.replace("new middle\n", ""))

    def test_returns_none_when_heading_absent(self) -> None:
        self.assertIsNone(
            render_body_section.replace_section("## A\nbody\n", "Missing", "x"),
        )

    def test_returns_none_when_only_match_is_inside_fence(self) -> None:
        content = "```\n## File Budget\nfence\n```\n\n## End\ntail\n"
        self.assertIsNone(
            render_body_section.replace_section(
                content, "File Budget", "anything",
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
