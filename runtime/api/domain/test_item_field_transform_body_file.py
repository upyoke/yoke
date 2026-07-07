"""Tests for the ``--body-file`` flag on item_field_transform subcommands."""

from __future__ import annotations

import json
import tempfile
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
    structured_field_input,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain._item_field_transform_test_helpers import (
    _FakeDB,
    _patched_db,
)


class _BodyFileTransformCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)

    def _write_temp(self, body: str) -> str:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        tmp.write(body)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return tmp.name


class TestStructuredFieldInputHelper(unittest.TestCase):
    """Direct tests for the shared helper module."""

    def test_stdin_only_reads_from_stdin(self) -> None:
        with mock.patch("sys.stdin", StringIO("payload")):
            ci = structured_field_input.resolve_content_input(
                stdin_flag=True, body_file=None,
            )
        self.assertEqual(ci.mode, "stdin")
        self.assertEqual(ci.content, "payload")
        self.assertIsNone(ci.file_path)

    def test_body_file_only_returns_path_unread(self) -> None:
        with mock.patch("sys.stdin", StringIO("WRONG_SOURCE")):
            ci = structured_field_input.resolve_content_input(
                stdin_flag=False, body_file="/tmp/some-file",
            )
        self.assertEqual(ci.mode, "body-file")
        self.assertEqual(ci.file_path, "/tmp/some-file")
        self.assertIsNone(ci.content)

    def test_invalid_mode_combinations_raise_canonical_errors(self) -> None:
        cases = [
            (
                True, "/tmp/x",
                structured_field_input.MUTUAL_EXCLUSION_ERROR, 2,
            ),
            (
                False, None,
                structured_field_input.MISSING_INPUT_ERROR, 1,
            ),
        ]
        for stdin_flag, body_file, message, exit_code in cases:
            with self.subTest(message=message):
                with self.assertRaises(
                    structured_field_input.ContentInputError,
                ) as ctx:
                    structured_field_input.resolve_content_input(
                        stdin_flag=stdin_flag,
                        body_file=body_file,
                    )
                self.assertEqual(ctx.exception.message, message)
                self.assertEqual(ctx.exception.exit_code, exit_code)

    def test_read_body_file_returns_content(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False,
        ) as fp:
            fp.write("hello body file\n")
            path = fp.name
        try:
            content = structured_field_input.read_body_file_or_raise(path)
            self.assertEqual(content, "hello body file\n")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_read_body_file_missing_path_raises_clean_error(self) -> None:
        missing = "/tmp/yoke-bodyfile-does-not-exist-XYZ.md"
        with self.assertRaises(structured_field_input.ContentInputError) as ctx:
            structured_field_input.read_body_file_or_raise(missing)
        self.assertIn("not found", ctx.exception.message)
        self.assertIn(missing, ctx.exception.message)
        self.assertEqual(ctx.exception.exit_code, 1)


class TestAppendAddendumBodyFile(_BodyFileTransformCase):
    """AC-1: append-addendum --body-file applies the additive write."""

    def test_body_file_applies_addendum(self) -> None:
        self.db.insert_item(401, spec="# Spec\n\nbase\n")
        body_path = self._write_temp("addendum body line\n")
        with mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "append-addendum", "--item", "401",
                "--field", "spec", "--heading", "Refinement Addendum",
                "--source", "refine", "--body-file", body_path,
            ])
        self.assertEqual(rc, 0)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertTrue(evidence["success"])
        self.assertTrue(evidence["changed"])
        self.assertEqual(evidence["verification"], "ok")
        spec = self.db.fetch_item_field(401, "spec")
        self.assertIn("## Refinement Addendum", spec)
        self.assertIn("addendum body line", spec)


class TestSectionUpsertBodyFile(_BodyFileTransformCase):
    """AC-2: section-upsert --body-file applies identically to --stdin."""

    def test_body_file_upserts_section(self) -> None:
        self.db.insert_item(402)
        body_path = self._write_temp("first entry contents\n")
        with mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "section-upsert", "--item", "402",
                "--section", "Progress Log", "--ordering", "200",
                "--source", "refine", "--body-file", body_path,
            ])
        self.assertEqual(rc, 0)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertTrue(evidence["success"])
        self.assertEqual(evidence["section"], "Progress Log")
        section = self.db.fetch_section(402, "Progress Log")
        self.assertIn("first entry contents", section)


class TestSectionAppendBodyFile(_BodyFileTransformCase):
    """AC-2: section-append --body-file applies identically to --stdin."""

    def test_body_file_appends_entry(self) -> None:
        self.db.insert_item(403)
        body_path = self._write_temp("appended entry body\n")
        with mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "section-append", "--item", "403",
                "--section", "Progress Log", "--headline", "first headline",
                "--ordering", "200", "--source", "refine",
                "--body-file", body_path,
            ])
        self.assertEqual(rc, 0)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertTrue(evidence["success"])
        self.assertEqual(evidence["section"], "Progress Log")
        section = self.db.fetch_section(403, "Progress Log")
        self.assertIn("first headline", section)
        self.assertIn("appended entry body", section)


class TestBodyFileErrors(_BodyFileTransformCase):
    """AC-3, AC-4, AC-5: error paths through the CLI surface."""

    def setUp(self) -> None:
        super().setUp()
        self.db.insert_item(501)

    def test_both_stdin_and_body_file_rejected(self) -> None:
        with mock.patch("sys.stdin", StringIO("ignored")), \
             mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "append-addendum", "--item", "501",
                "--field", "spec", "--heading", "X",
                "--stdin", "--body-file", "/tmp/fake-path",
            ])
        self.assertEqual(rc, 2)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertFalse(evidence["success"])
        self.assertEqual(
            evidence["error"],
            "cannot use both --stdin and --body-file; pick one",
        )

    def test_neither_stdin_nor_body_file_rejected(self) -> None:
        with mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "append-addendum", "--item", "501",
                "--field", "spec", "--heading", "X",
            ])
        self.assertEqual(rc, 1)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertFalse(evidence["success"])
        self.assertEqual(
            evidence["error"],
            "content input missing (--stdin or --body-file required)",
        )

    def test_missing_body_file_path_clean_error(self) -> None:
        missing = "/tmp/yoke-bodyfile-missing-ZZZ.md"
        with mock.patch("sys.stdout", new_callable=StringIO) as stdout:
            rc = item_field_transform.main([
                "append-addendum", "--item", "501",
                "--field", "spec", "--heading", "X",
                "--body-file", missing,
            ])
        self.assertEqual(rc, 1)
        evidence = json.loads(stdout.getvalue().strip())
        self.assertFalse(evidence["success"])
        self.assertIn("not found", evidence["error"])
        self.assertIn(missing, evidence["error"])
        # Verify no traceback leaked into the JSON evidence.
        self.assertNotIn("Traceback", evidence["error"])
        self.assertNotIn("FileNotFoundError", evidence["error"])


if __name__ == "__main__":  # pragma: no cover - test runner shim
    unittest.main()
