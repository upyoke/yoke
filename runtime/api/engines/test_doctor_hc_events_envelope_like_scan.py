"""Scan mechanics for HC-events-envelope-like-scan (fixture trees only).

The live-repo verdict belongs to doctor runs on the integrated tree; these
tests pin the scanner's contract: LIKE-shape detection over the envelope
column, prose exclusion, allowlist matching, and stale-entry reporting.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from yoke_project_checks.check_events_envelope_like_scan import (
    ALLOWED_ENVELOPE_LIKE_READERS,
    scan_envelope_like_reads,
)


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class TestScanEnvelopeLikeReads(unittest.TestCase):
    def test_flags_envelope_substring_match(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/domain/correlator.py",
                'Q = "SELECT id FROM events WHERE envelope LIKE %s"\n',
            )
            violations, _ = scan_envelope_like_reads(root)
        self.assertEqual(len(violations), 1)
        self.assertEqual(
            violations[0].relpath,
            "packages/yoke-core/src/yoke_core/domain/correlator.py",
        )
        self.assertEqual(violations[0].line, 1)

    def test_flags_cast_and_ilike_forms(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/domain/casts.py",
                'A = "WHERE envelope::text ILIKE %s"\n'
                'B = "WHERE envelope NOT LIKE %s"\n',
            )
            violations, _ = scan_envelope_like_reads(root)
        self.assertEqual([f.line for f in violations], [1, 2])

    def test_ignores_prose_that_teaches_the_rule(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/domain/teacher.py",
                '"""Never match a row with envelope LIKE \'%id%\'."""\n'
                "# envelope LIKE is the banned shape\n"
                'Q = "SELECT id FROM events WHERE client_timing_id = %s"\n',
            )
            violations, _ = scan_envelope_like_reads(root)
        self.assertEqual(violations, [])

    def test_ignores_equality_on_the_whole_column(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/domain/exact.py",
                'Q = "SELECT id FROM events WHERE envelope = %s"\n',
            )
            violations, _ = scan_envelope_like_reads(root)
        self.assertEqual(violations, [])

    def test_ignores_tests_and_reports_stale_allowlist_entries(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "runtime/api/test_correlator.py",
                'Q = "SELECT id FROM events WHERE envelope LIKE %s"\n',
            )
            violations, stale = scan_envelope_like_reads(root)
        self.assertEqual(violations, [])
        self.assertEqual(sorted(stale), sorted(ALLOWED_ENVELOPE_LIKE_READERS))

    def test_allowlisted_reader_is_not_a_violation(self):
        allowed = ALLOWED_ENVELOPE_LIKE_READERS[0]
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root, allowed, 'Q = "WHERE envelope LIKE %s"\n')
            violations, stale = scan_envelope_like_reads(root)
        self.assertEqual(violations, [])
        self.assertNotIn(allowed, stale)

    def test_flags_sql_files_outside_comments(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/queries.sql",
                "-- envelope LIKE is banned\n"
                "SELECT id FROM events WHERE envelope LIKE '%x%';\n",
            )
            violations, _ = scan_envelope_like_reads(root)
        self.assertEqual([f.line for f in violations], [2])


if __name__ == "__main__":
    unittest.main()
