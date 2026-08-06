"""Scan mechanics for HC-events-app-state-reads (fixture trees only).

The live-repo verdict belongs to doctor runs on the integrated tree; these
tests pin the scanner's contract: read-shape detection, allowlist prefix
matching, test/fixture exclusion, and stale-entry reporting.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from yoke_project_checks.check_events_app_state_reads import (
    ALLOWED_EVENTS_READERS,
    _TRANSIENT_EMPTY_OK,
    scan_events_reads,
)


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class TestScanEventsReads(unittest.TestCase):
    def test_flags_unallowlisted_read(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/domain/new_feature.py",
                'ROWS = "SELECT id FROM events WHERE item_id = %s"\n',
            )
            violations, _ = scan_events_reads(root)
        self.assertEqual(len(violations), 1)
        self.assertIn(
            "packages/yoke-core/src/yoke_core/domain/new_feature.py:1",
            violations[0],
        )

    def test_flags_join_and_aliased_forms(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/domain/joiner.py",
                'Q = "SELECT 1 FROM items i JOIN events e ON e.item_id = i.id"\n'
                'R = "select max(created_at) from events ev"\n',
            )
            violations, _ = scan_events_reads(root)
        self.assertEqual(len(violations), 2)

    def test_allowlist_prefix_covers_directory(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            migrations_prefix = next(iter(_TRANSIENT_EMPTY_OK))
            _write(
                root,
                migrations_prefix + "some_backfill.py",
                'SEED = "SELECT envelope FROM events WHERE event_name = %s"\n',
            )
            violations, _ = scan_events_reads(root)
        self.assertEqual(violations, [])

    def test_allowlisted_file_passes(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            allowlisted_rel = next(
                p for p in ALLOWED_EVENTS_READERS if p.endswith("/events_queries.py")
            )
            _write(
                root,
                allowlisted_rel,
                'BASE = "SELECT * FROM events"\n',
            )
            violations, stale = scan_events_reads(root)
        self.assertEqual(violations, [])
        self.assertNotIn(allowlisted_rel, stale)

    def test_claim_boundary_audit_selector_is_allowlisted_audit_reader(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            allowlisted_rel = next(
                p
                for p in ALLOWED_EVENTS_READERS
                if p.endswith("/check_claim_boundary_audit_select.py")
            )
            _write(
                root,
                allowlisted_rel,
                'SQL = "SELECT id, envelope FROM events WHERE event_name = %s"\n',
            )
            violations, stale = scan_events_reads(root)
        self.assertEqual(violations, [])
        self.assertNotIn(allowlisted_rel, stale)

    def test_current_telemetry_readers_are_allowlisted_by_exact_path(self):
        reader_suffixes = (
            "yoke_contracts/board/widgets_velocity_meter.py",
            "yoke_core/domain/board_momentum_signals.py",
            "yoke_core/domain/last_doctor_run_read.py",
            "yoke_core/domain/source_authority_receipts.py",
            ".yoke/doctor/check_session_identity_provenance.py",
            ".yoke/doctor/check_silent_hooks.py",
        )
        for suffix in reader_suffixes:
            with self.subTest(reader=suffix), TemporaryDirectory() as td:
                root = Path(td)
                allowlisted_rel = next(
                    path for path in ALLOWED_EVENTS_READERS if path.endswith(suffix)
                )
                _write(root, allowlisted_rel, 'SQL = "SELECT 1 FROM events"\n')
                violations, stale = scan_events_reads(root)
            self.assertEqual(violations, [])
            self.assertNotIn(allowlisted_rel, stale)

    def test_package_build_output_is_excluded(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            for rel in (
                "packages/yoke-core/build/lib/yoke_core/domain/copied_reader.py",
                "packages/yoke-contracts/build/lib/yoke_contracts/board/copied_widget.py",
            ):
                _write(root, rel, 'SQL = "SELECT 1 FROM events"\n')
            violations, _ = scan_events_reads(root)
        self.assertEqual(violations, [])

    def test_python_import_from_events_is_not_a_sql_read(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/install_bundle_tree/"
                "packs/structured-events/files/events.py",
                "from events import emit_event\n",
            )
            violations, _ = scan_events_reads(root)
        self.assertEqual(violations, [])

    def test_tests_fixtures_and_self_are_excluded(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            for rel in (
                "packages/yoke-core/src/yoke_core/domain/test_something.py",
                "packages/yoke-core/src/yoke_core/fixtures/inserts.py",
                "packages/yoke-core/src/yoke_core/domain/conftest.py",
                # Self-exclusion is by module identity, not location: a copy in
                # any scanned tree is skipped.
                "packages/yoke-core/src/yoke_core/engines/check_events_app_state_reads.py",
                ".yoke/doctor/check_events_app_state_reads.py",
                "packages/yoke-core/src/yoke_core/domain/_path_claims_test_helpers.py",
                "packages/yoke-core/src/yoke_core/update_status_full_test_schema.py",
            ):
                _write(root, rel, 'Q = "SELECT 1 FROM events"\n')
            violations, _ = scan_events_reads(root)
        self.assertEqual(violations, [])

    def test_stale_allowlist_entries_reported(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "packages").mkdir()
            _, stale = scan_events_reads(root)
        # Empty tree: every entry is stale EXCEPT the transient-empty-OK
        # reader classes (governed backfills, empty between migrations).
        expected = tuple(
            e for e in ALLOWED_EVENTS_READERS if e not in _TRANSIENT_EMPTY_OK
        )
        self.assertEqual(tuple(stale), expected)
        # The migrations backfill class is never reported stale.
        self.assertFalse(_TRANSIENT_EMPTY_OK.intersection(stale))

    def test_event_name_lines_do_not_match(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "packages/yoke-core/src/yoke_core/domain/emitter.py",
                'emit_event(conn, event_name="ItemStatusChanged")\n'
                "# reads come from events_queries, not here\n"
                'TABLE = "events"\n',
            )
            violations, _ = scan_events_reads(root)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
