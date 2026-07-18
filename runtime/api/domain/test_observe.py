"""Tests for observe.py — column shape, item_id normalization, duration lookup.

Original module covered every flavor of observe behavior. It is now split
across sibling files so each authored file stays under the 350-line limit:
this file covers column population, item_id prefix, and duration lookup.
The enriched-context coverage lives in ``test_observe_context`` and the
DB-backed session-attribution coverage lives in ``test_observe_attribution``.
Heavy fixture/helper code lives in ``observe_test_helpers``.
"""

from __future__ import annotations

import unittest

from yoke_core.domain import db_backend
from yoke_core.domain.observe import (
    build_envelope,
    detect_anomalies,
    insert_event,
    parse_hook_event,
)
from yoke_core.domain.observe_normalization import (
    TOOL_KIND_APPLY_PATCH,
    TOOL_KIND_BASH,
    TOOL_KIND_EDIT,
    TOOL_KIND_WRITE,
    ToolEventRecord,
)
from yoke_core.domain.observe_test_helpers import observe_events_db
from runtime.api.fixtures.file_test_db import connect_test_db


class TestNewColumns(unittest.TestCase):
    """AC-1: HarnessToolCallCompleted rows keep session_id canonical and add correlation fields."""

    def test_TC_new_columns_populated(self):
        with observe_events_db() as db_path:
            data = {
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello"},
                "tool_response": {"content": "hello"},
                "tool_use_id": "tu_abc123",
                "turn_id": "turn_xyz",
            }
            rec = parse_hook_event(
                data,
                session_id="sess_001",
                hook_event="PostToolUse",
                tool_use_id="tu_abc123",
                agent_type="engineer",
            )
            self.assertIsNotNone(rec)
            detect_anomalies(rec)
            envelope = build_envelope(rec)

            conn = connect_test_db(db_path)
            insert_event(conn, envelope)

            row = conn.execute(
                "SELECT session_id, tool_use_id, hook_event_name, turn_id "
                "FROM events LIMIT 1"
            ).fetchone()
            conn.close()

            self.assertEqual(row[0], "sess_001")
            self.assertEqual(row[1], "tu_abc123")
            self.assertEqual(row[2], "PostToolUse")
            self.assertEqual(row[3], "turn_xyz")

    def test_TC_failed_event_has_columns(self):
        with observe_events_db() as db_path:
            data = {
                "tool_name": "Bash",
                "tool_input": {"command": "false"},
                "tool_response": {"content": "Exit code 1"},
                "error": "Command failed",
                "tool_use_id": "tu_fail",
            }
            rec = parse_hook_event(
                data,
                session_id="sess_002",
                hook_event="PostToolUseFailure",
                tool_use_id="tu_fail",
                agent_type="tester",
            )
            self.assertIsNotNone(rec)
            detect_anomalies(rec)
            envelope = build_envelope(rec)

            conn = connect_test_db(db_path)
            insert_event(conn, envelope)

            row = conn.execute(
                "SELECT session_id, tool_use_id, hook_event_name "
                "FROM events LIMIT 1"
            ).fetchone()
            conn.close()

            self.assertEqual(row[0], "sess_002")
            self.assertEqual(row[1], "tu_fail")
            self.assertEqual(row[2], "PostToolUseFailure")

    def test_TC_tool_call_project_follows_session_project(self):
        with observe_events_db() as db_path:
            conn = connect_test_db(db_path)
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            conn.execute(
                "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}) ON CONFLICT (id) DO NOTHING",
                (2, "externalwebapp", "ExternalWebapp", "EXT", "2026-01-01T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO harness_sessions "
                "(session_id, executor, provider, model, workspace, project_id, "
                "offered_at, last_heartbeat) "
                f"VALUES ({p}, 'test', 'test', 'test', '/tmp/externalwebapp', {p}, {p}, {p})",
                (
                    "sess_externalwebapp",
                    2,
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )
            conn.commit()

            data = {
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello"},
                "tool_response": {"content": "hello"},
                "tool_use_id": "tu_externalwebapp",
            }
            rec = parse_hook_event(
                data,
                session_id="sess_externalwebapp",
                hook_event="PostToolUse",
                tool_use_id="tu_externalwebapp",
            )
            self.assertIsNotNone(rec)
            detect_anomalies(rec)
            insert_event(conn, build_envelope(rec))

            project = conn.execute(
                "SELECT p.slug FROM events e JOIN projects p ON p.id = e.project_id "
                f"WHERE e.tool_use_id = {p}",
                ("tu_externalwebapp",),
            ).fetchone()[0]
            conn.close()

            self.assertEqual(project, "externalwebapp")


class TestItemIdPrefix(unittest.TestCase):
    """AC-2: item_id stays canonical as bare numeric across attribution paths."""

    def test_TC_item_id_keeps_numeric_form(self):
        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/test.py"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(
            data,
            item_id="42",
            hook_event="PostToolUse",
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_id, "42")

    def test_TC_bare_numeric_item_id_preserved(self):
        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/test.py"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(
            data,
            item_id="42",
            hook_event="PostToolUse",
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_id, "42")

    def test_TC_item_id_in_db_row(self):
        with observe_events_db() as db_path:
            data = {
                "tool_name": "Read",
                "tool_input": {"file_path": "/tmp/test.py"},
                "tool_response": {"content": "ok"},
            }
            rec = parse_hook_event(
                data,
                session_id="sess_003",
                item_id="42",
                hook_event="PostToolUse",
            )
            detect_anomalies(rec)
            envelope = build_envelope(rec)

            conn = connect_test_db(db_path)
            insert_event(conn, envelope)
            row = conn.execute("SELECT item_id FROM events LIMIT 1").fetchone()
            conn.close()

            self.assertEqual(row[0], "42")


class TestDurationLookup(unittest.TestCase):
    """Verify duration lookup uses tool_use_id column, not json_extract."""

    def test_TC_duration_uses_column_lookup(self):
        import inspect
        from yoke_core.domain.observe import _compute_duration

        source = inspect.getsource(_compute_duration)
        self.assertNotIn("json_extract", source)
        self.assertIn("tool_use_id =", source)


class TestToolEventRecordApplyPatch(unittest.TestCase):
    """AC-2: ToolEventRecord covers apply_patch with changed_paths."""

    def test_TC_tool_event_record_apply_patch_kind_round_trips(self):
        rec = ToolEventRecord(
            tool_kind=TOOL_KIND_APPLY_PATCH,
            changed_paths=["a/added.py", "b/changed.py"],
            patch_body="*** Begin Patch\n*** Add File: a/added.py\n+x\n",
            tool_name="apply_patch",
        )
        self.assertEqual(rec.tool_kind, TOOL_KIND_APPLY_PATCH)
        self.assertEqual(rec.changed_paths, ["a/added.py", "b/changed.py"])
        self.assertTrue(rec.patch_body)

    def test_TC_tool_event_record_default_changed_paths_is_empty_list(self):
        rec = ToolEventRecord(tool_kind=TOOL_KIND_BASH)
        self.assertEqual(rec.changed_paths, [])

    def test_TC_tool_event_record_kinds_are_distinct(self):
        kinds = {
            TOOL_KIND_BASH,
            TOOL_KIND_WRITE,
            TOOL_KIND_EDIT,
            TOOL_KIND_APPLY_PATCH,
        }
        self.assertEqual(len(kinds), 4)


if __name__ == "__main__":
    unittest.main()
