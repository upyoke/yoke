"""Tests for yoke_core.domain.events — Python event emitter with correlation columns."""

import json
import unittest
from unittest.mock import patch

from yoke_core.domain.events import build_envelope, emit_event
from runtime.api.fixtures.pg_testdb import test_database


class TestBuildEnvelope(unittest.TestCase):
    """Unit tests for build_envelope()."""

    def test_new_kwargs_present_in_envelope(self):
        """TC-envelope-new-kwargs: session_id stays canonical with top-level correlation fields."""
        env = build_envelope(
            "TestEvent",
            event_kind="test",
            event_type="unit_test",
            session_id="HS456",
            exit_code=7,
            user_id="user-1",
            org_id="org-1",
            environment="stage",
            request_id="req-1",
            tool_use_id="TUI123",
            turn_id="TURN789",
            hook_event_name="PostToolUse",
        )
        self.assertEqual(env["session_id"], "HS456")
        self.assertEqual(env["user_id"], "user-1")
        self.assertEqual(env["org_id"], "org-1")
        self.assertEqual(env["environment"], "stage")
        self.assertEqual(env["request_id"], "req-1")
        self.assertEqual(env["exit_code"], 7)
        self.assertEqual(env["tool_use_id"], "TUI123")
        self.assertEqual(env["turn_id"], "TURN789")
        self.assertEqual(env["hook_event_name"], "PostToolUse")

    def test_new_kwargs_default_none(self):
        """TC-envelope-defaults-none: omitted new kwargs default to None."""
        env = build_envelope(
            "TestEvent",
            event_kind="test",
            event_type="unit_test",
        )
        self.assertIsNone(env["tool_use_id"])
        self.assertIsNone(env["turn_id"])
        self.assertIsNone(env["hook_event_name"])
        self.assertIsNone(env["user_id"])
        self.assertIsNone(env["org_id"])
        self.assertIsNone(env["environment"])
        self.assertIsNone(env["request_id"])
        self.assertIsNone(env["exit_code"])

    def test_item_id_passthrough_in_envelope(self):
        """TC-item-id-envelope-passthrough: build_envelope stores numeric item_id."""
        env = build_envelope(
            "TestEvent",
            event_kind="test",
            event_type="unit_test",
            item_id="42",
        )
        self.assertEqual(env["item_id"], "42")

    def test_trace_context_is_copied_when_available(self):
        with patch(
            "yoke_core.api.observability.trace_context",
            return_value={"trace_id": "trace-1", "span_id": "span-1"},
        ):
            env = build_envelope(
                "TraceEvent",
                event_kind="test",
                event_type="unit_test",
            )

        self.assertEqual(env["trace_id"], "trace-1")
        self.assertEqual(env["span_id"], "span-1")


class TestEmitEvent(unittest.TestCase):
    """Integration tests for emit_event() writing to an in-memory DB."""

    def setUp(self):
        self._db_cm = test_database()
        self.conn = self._db_cm.__enter__()

    def tearDown(self):
        self._db_cm.__exit__(None, None, None)

    def _install_severity_config(self, min_severity="INFO"):
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS severity_config ("
            "id INTEGER PRIMARY KEY, event_name TEXT NOT NULL DEFAULT '*', "
            "source_type TEXT NOT NULL DEFAULT '*', "
            "min_severity TEXT NOT NULL DEFAULT 'INFO', "
            "created_at TEXT NOT NULL, UNIQUE(event_name, source_type))"
        )
        self.conn.execute(
            "INSERT INTO severity_config "
            "(event_name, source_type, min_severity, created_at) "
            "VALUES ('*', '*', %s, 'now') "
            "ON CONFLICT(event_name, source_type) DO UPDATE SET "
            "min_severity=excluded.min_severity, "
            "created_at=excluded.created_at",
            (min_severity,),
        )
        self.conn.commit()

    def test_emit_with_new_kwargs(self):
        """TC-emit-new-kwargs: new columns populated in DB row."""
        result = emit_event(
            "TestEmit",
            event_kind="test",
            event_type="unit_test",
            session_id="HS456",
            exit_code=7,
            tool_use_id="TUI123",
            turn_id="TURN789",
            hook_event_name="PostToolUse",
            conn=self.conn,
        )
        self.assertIsNotNone(result)

        row = self.conn.execute(
            "SELECT session_id, exit_code, tool_use_id, turn_id, hook_event_name "
            "FROM events WHERE event_id = %s",
            (result["event_id"],),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["session_id"], "HS456")
        self.assertEqual(row["exit_code"], 7)
        self.assertEqual(row["tool_use_id"], "TUI123")
        self.assertEqual(row["turn_id"], "TURN789")
        self.assertEqual(row["hook_event_name"], "PostToolUse")

    def test_emit_without_new_kwargs_produces_null(self):
        """TC-emit-null-defaults: omitting new kwargs stores NULL."""
        result = emit_event(
            "TestEmitNull",
            event_kind="test",
            event_type="unit_test",
            conn=self.conn,
        )
        self.assertIsNotNone(result)

        row = self.conn.execute(
            "SELECT tool_use_id, turn_id, hook_event_name "
            "FROM events WHERE event_id = %s",
            (result["event_id"],),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row["tool_use_id"])
        self.assertIsNone(row["turn_id"])
        self.assertIsNone(row["hook_event_name"])

    def test_item_id_persists_as_numeric_format(self):
        """TC-item-id-db: item_id persists in canonical numeric form."""
        result = emit_event(
            "TestItemId",
            event_kind="test",
            event_type="unit_test",
            item_id="99",
            conn=self.conn,
        )
        self.assertIsNotNone(result)

        row = self.conn.execute(
            "SELECT item_id FROM events WHERE event_id = %s",
            (result["event_id"],),
        ).fetchone()
        self.assertEqual(row["item_id"], "99")

    def test_new_columns_in_envelope_json(self):
        """TC-envelope-json-columns: new columns present in serialized envelope."""
        result = emit_event(
            "TestEnvelope",
            event_kind="test",
            event_type="unit_test",
            session_id="HS-ENV",
            tool_use_id="TUI-ENV",
            conn=self.conn,
        )
        self.assertIsNotNone(result)

        row = self.conn.execute(
            "SELECT envelope FROM events WHERE event_id = %s",
            (result["event_id"],),
        ).fetchone()
        envelope = json.loads(row["envelope"])
        self.assertEqual(envelope["session_id"], "HS-ENV")
        self.assertEqual(envelope["tool_use_id"], "TUI-ENV")
        self.assertIsNone(envelope["turn_id"])
        self.assertIsNone(envelope["hook_event_name"])

    def test_debug_hook_guardrail_filtered_at_info_floor(self):
        """TC-emit-severity-filter: DEBUG hook rows drop at the INFO floor."""
        self._install_severity_config("INFO")

        result = emit_event(
            "HookGuardrailEvaluated",
            event_kind="system",
            event_type="hook_guardrail_evaluated",
            source_type="hook",
            severity="DEBUG",
            conn=self.conn,
        )

        self.assertEqual(result.reason, "severity_filtered")
        count = self.conn.execute(
            "SELECT count(*) FROM events WHERE event_name='HookGuardrailEvaluated'"
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_debug_hook_guardrail_kept_when_override_allows(self):
        """TC-emit-severity-override: exact DEBUG override persists the row."""
        self._install_severity_config("INFO")
        self.conn.execute(
            "INSERT INTO severity_config "
            "(event_name, source_type, min_severity, created_at) "
            "VALUES ('HookGuardrailEvaluated', 'hook', 'DEBUG', 'now')"
        )
        self.conn.commit()

        result = emit_event(
            "HookGuardrailEvaluated",
            event_kind="system",
            event_type="hook_guardrail_evaluated",
            source_type="hook",
            severity="DEBUG",
            conn=self.conn,
        )

        self.assertTrue(result.ok)
        count = self.conn.execute(
            "SELECT count(*) FROM events WHERE event_name='HookGuardrailEvaluated'"
        ).fetchone()[0]
        self.assertEqual(count, 1)


class TestInsertSqlColumnCount(unittest.TestCase):
    """Verify _INSERT_SQL has correct column/placeholder counts."""

    def test_column_placeholder_parity(self):
        """TC-sql-parity: column count matches placeholder count."""
        from yoke_core.domain.events import _INSERT_SQL

        # Extract column names
        col_section = _INSERT_SQL.split("(")[1].split(")")[0]
        columns = [c.strip() for c in col_section.split(",") if c.strip()]

        # Extract placeholders
        val_section = _INSERT_SQL.split("VALUES")[1]
        placeholders = val_section.count("%s")

        self.assertEqual(len(columns), placeholders)
        self.assertEqual(len(columns), 28)

        # Verify new columns are present
        self.assertIn("user_id", columns)
        self.assertIn("org_id", columns)
        self.assertIn("environment", columns)
        self.assertIn("actor_id", columns)
        self.assertIn("exit_code", columns)
        self.assertIn("tool_use_id", columns)
        self.assertIn("turn_id", columns)
        self.assertIn("hook_event_name", columns)


class TestEmitEventArgvCompat(unittest.TestCase):
    """Verify command-like legacy argv delegates carry canonical context."""

    def test_forwards_canonical_context_flags(self):
        from yoke_core.domain import events_argv_compat

        sentinel = object()
        with patch.object(events_argv_compat, "emit_event", return_value=sentinel) as fake_emit:
            result = events_argv_compat.emit_event_argv(
                [
                    "--name",
                    "ArgvEvent",
                    "--kind",
                    "system",
                    "--type",
                    "test",
                    "--source-type",
                    "backend",
                    "--session-id",
                    "sess-1",
                    "--user-id",
                    "user-1",
                    "--org-id",
                    "org-1",
                    "--environment",
                    "stage",
                    "--request-id",
                    "req-1",
                ]
            )

        self.assertIs(result, sentinel)
        self.assertEqual(fake_emit.call_args.args, ("ArgvEvent",))
        self.assertEqual(fake_emit.call_args.kwargs["session_id"], "sess-1")
        self.assertEqual(fake_emit.call_args.kwargs["user_id"], "user-1")
        self.assertEqual(fake_emit.call_args.kwargs["org_id"], "org-1")
        self.assertEqual(fake_emit.call_args.kwargs["environment"], "stage")
        self.assertEqual(fake_emit.call_args.kwargs["request_id"], "req-1")


if __name__ == "__main__":
    unittest.main()
