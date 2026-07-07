"""Tests for writer-time severity normalization.

Covers AC-1, AC-2, AC-3, AC-7 (partial — non-migration ACs):

- ``normalize_severity`` maps known non-canonical casings to canonical.
- ``normalize_severity`` raises ``EventSeverityCasingError`` for unknown values.
- Native ``emit_event`` (``events.build_envelope``) normalizes severity before
  envelope construction; an unknown value returns ``EmitResult(ok=False)``.
- Legacy ``cmd_insert`` normalizes severity before INSERT; an unknown value
  raises ``EventSeverityCasingError`` (non-fatal at the producer level).
- The five updated registry seed rows and producer literals carry the
  canonical ``WARN`` value.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yoke_core.domain.events_crud import (
    EventSeverityCasingError,
    VALID_SEVERITIES,
    normalize_severity,
)
from yoke_core.domain.events_schema import cmd_init as _events_cmd_init
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_minimal_events_schema() -> None:
    from yoke_core.domain import db_backend
    from yoke_core.domain.events_schema import _create_events_table

    conn = db_backend.connect()
    try:
        _create_events_table(conn)
        conn.commit()
    finally:
        conn.close()


class NormalizeSeverityHelperTest(unittest.TestCase):
    def test_canonical_uppercase_passthrough(self):
        for canonical in VALID_SEVERITIES:
            self.assertEqual(normalize_severity(canonical), canonical)

    def test_lowercase_maps_to_canonical(self):
        self.assertEqual(normalize_severity("info"), "INFO")
        self.assertEqual(normalize_severity("debug"), "DEBUG")
        self.assertEqual(normalize_severity("status"), "STATUS")
        self.assertEqual(normalize_severity("warn"), "WARN")
        self.assertEqual(normalize_severity("error"), "ERROR")
        self.assertEqual(normalize_severity("fatal"), "FATAL")

    def test_mixed_case_maps_to_canonical(self):
        self.assertEqual(normalize_severity("Info"), "INFO")
        self.assertEqual(normalize_severity("Debug"), "DEBUG")
        self.assertEqual(normalize_severity("Warn"), "WARN")
        self.assertEqual(normalize_severity("Error"), "ERROR")

    def test_warning_alias_maps_to_warn(self):
        # The historical non-canonical alias the audit surfaced — must
        # normalize so producers that lived with `severity="WARNING"` are
        # absorbed by the writer without inserting drifted rows.
        self.assertEqual(normalize_severity("WARNING"), "WARN")
        self.assertEqual(normalize_severity("warning"), "WARN")
        self.assertEqual(normalize_severity("Warning"), "WARN")

    def test_whitespace_padding_tolerated(self):
        self.assertEqual(normalize_severity("  WARN  "), "WARN")
        self.assertEqual(normalize_severity("\tinfo\n"), "INFO")

    def test_unknown_severity_raises(self):
        for bad in ("VERBOSE", "trace", "NOTICE", "panic", "loud", "high"):
            with self.assertRaises(EventSeverityCasingError):
                normalize_severity(bad)

    def test_empty_or_non_string_raises(self):
        for bad in ("", "   ", None, 0, [], {}):
            with self.assertRaises(EventSeverityCasingError):
                normalize_severity(bad)  # type: ignore[arg-type]


class EmitEventNormalizationTest(unittest.TestCase):
    """End-to-end: ``emit_event`` writes the canonical severity to the row."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_ctx = init_test_db(
            Path(self._tmp.name), apply_schema=_apply_minimal_events_schema
        )
        self.db_path = self._db_ctx.__enter__()

    def tearDown(self):
        self._db_ctx.__exit__(None, None, None)
        self._tmp.cleanup()

    def _row_severity(self, event_id):
        conn = connect_test_db(self.db_path)
        try:
            cur = conn.execute(
                "SELECT severity FROM events WHERE event_id=%s", (event_id,)
            )
            row = cur.fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def test_warning_alias_persisted_as_warn(self):
        from yoke_core.domain.events import emit_event

        result = emit_event(
            "PathClaimBashGuardDenied",
            event_kind="lifecycle",
            event_type="path_claim",
            source_type="system",
            severity="WARNING",
            db_path=self.db_path,
        )
        self.assertTrue(result.ok, msg=f"emit failed: {result.reason}")
        self.assertEqual(self._row_severity(result.event_id), "WARN")

    def test_lowercase_info_persisted_as_canonical(self):
        from yoke_core.domain.events import emit_event

        result = emit_event(
            "TestEvent",
            event_kind="lifecycle",
            event_type="test",
            source_type="system",
            severity="info",
            db_path=self.db_path,
        )
        self.assertTrue(result.ok, msg=f"emit failed: {result.reason}")
        self.assertEqual(self._row_severity(result.event_id), "INFO")

    def test_unknown_severity_no_row_inserted(self):
        from yoke_core.domain.events import emit_event

        result = emit_event(
            "TestEvent",
            event_kind="lifecycle",
            event_type="test",
            source_type="system",
            severity="VERBOSE",
            db_path=self.db_path,
        )
        # emit_event swallows the error per the non-fatal contract.
        self.assertFalse(result.ok)
        self.assertIn(result.reason, ("exception", "events_table_missing"))
        # Verify no row landed for this attempted event.
        conn = connect_test_db(self.db_path)
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_name='TestEvent'"
            )
            count = cur.fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)


class CmdInsertNormalizationTest(unittest.TestCase):
    """Legacy ``cmd_insert`` path normalizes severity in lockstep with native.

    Both ``cmd_insert`` and ``emit_event`` route through the backend factory on
    Postgres, so explicit SQLite-style ``db_path`` tokens still land in the
    DSN-pointed disposable database. ``init_test_db`` keeps the writer and
    ``connect_test_db`` readback on the same DB for both engines.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_ctx = init_test_db(
            Path(self._tmp.name), apply_schema=_events_cmd_init
        )
        self.db_path = self._db_ctx.__enter__()

    def tearDown(self):
        self._db_ctx.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_warning_alias_persisted_as_warn(self):
        from yoke_core.domain.events_writes import cmd_insert

        cmd_insert(
            db_path=self.db_path,
            event_id="evt-warning-alias",
            source_type="system",
            session_id="",
            event_kind="lifecycle",
            event_type="test",
            event_name="LegacyCmdInsertTest",
            severity="WARNING",
            skip_severity=True,
        )
        conn = connect_test_db(self.db_path)
        try:
            cur = conn.execute(
                "SELECT severity FROM events WHERE event_id=%s",
                ("evt-warning-alias",),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "WARN")

    def test_unknown_severity_raises(self):
        from yoke_core.domain.events_writes import cmd_insert

        with self.assertRaises(EventSeverityCasingError):
            cmd_insert(
                db_path=self.db_path,
                event_id="evt-bad",
                source_type="system",
                session_id="",
                event_kind="lifecycle",
                event_type="test",
                event_name="LegacyCmdInsertTest",
                severity="VERBOSE",
                skip_severity=True,
            )
        # Verify no row landed.
        conn = connect_test_db(self.db_path)
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_id=%s", ("evt-bad",)
            )
            count = cur.fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)


class ProducerLiteralCleanupTest(unittest.TestCase):
    """AC-3 sentinel: the five touched producer/seed files carry canonical WARN."""

    def test_path_claim_bash_guard_emits_warn(self):
        from yoke_core.domain import path_claim_bash_guard

        source = Path(path_claim_bash_guard.__file__).read_text(encoding="utf-8")
        self.assertIn('severity="WARN"', source)
        self.assertNotIn('severity="WARNING"', source)

    def test_path_claim_pre_edit_guard_emits_warn(self):
        from yoke_core.domain import path_claim_pre_edit_guard

        source = Path(path_claim_pre_edit_guard.__file__).read_text(encoding="utf-8")
        self.assertIn('severity="WARN"', source)
        self.assertNotIn('severity="WARNING"', source)

    def test_dispatcher_emits_warn(self):
        from yoke_core.domain import yoke_function_dispatch_events

        source = Path(yoke_function_dispatch_events.__file__).read_text(
            encoding="utf-8"
        )
        self.assertIn('severity="WARN"', source)
        self.assertNotIn('severity="WARNING"', source)

    def test_session_cwd_seed_rows_use_canonical_severities(self):
        from yoke_core.domain.event_registry_seed_path_claim_session_cwd import (
            SEED_ROWS,
        )

        # Allow-path rows surface as INFO (no warning when the call
        # passed); deny / fail-open / health-check rows surface as WARN.
        info_names = {"SessionCwdMismatchAllowedReadOnly"}
        for row in SEED_ROWS:
            name, severity = row[0], row[5]
            expected = "INFO" if name in info_names else "WARN"
            self.assertEqual(severity, expected, msg=f"row {name}: {row}")

    def test_function_call_seed_dispatcher_is_warn(self):
        from yoke_core.domain.event_registry_seed_yoke_function_call import (
            SEED_ROWS,
        )

        by_name = {row[0]: row for row in SEED_ROWS}
        self.assertEqual(by_name["DispatcherDownstreamDegraded"][5], "WARN")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
