"""Tests for db_error_hook.py — DB error detection hook.

Covers: stray DB detection, DB query failure detection, row-count collapse
detection, and the unified analyze_bash_output entry point.
"""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest
from yoke_core.domain.db_error_hook import (
    CollapseEntry,
    CollapseResult,
    StrayDbResult,
    analyze_bash_output,
    check_row_count_collapse,
    detect_db_query_failure,
    detect_stray_db,
)


# ---------------------------------------------------------------------------
# detect_stray_db
# ---------------------------------------------------------------------------


class TestDetectStrayDb:
    def test_no_stray(self, tmp_path):
        result = detect_stray_db(str(tmp_path))
        assert not result.detected
        assert result.message == ""

    def test_zero_byte_stray_autoremoved(self, tmp_path):
        stray = tmp_path / "yoke.db"
        stray.touch()
        (tmp_path / "runtime" / "ouroboros").mkdir(parents=True)

        result = detect_stray_db(str(tmp_path), "some command")
        assert result.detected
        assert result.status == "zero-byte"
        assert "HARD STOP" in result.message
        assert not stray.exists()  # auto-removed

    def test_nonempty_stray_not_deleted(self, tmp_path):
        stray = tmp_path / "yoke.db"
        stray.write_text("data")
        (tmp_path / "runtime" / "ouroboros").mkdir(parents=True)

        result = detect_stray_db(str(tmp_path), "some command")
        assert result.detected
        assert result.status == "non-empty"
        assert "HARD STOP" in result.message
        assert stray.exists()  # NOT auto-removed


# ---------------------------------------------------------------------------
# detect_db_query_failure
# ---------------------------------------------------------------------------


class TestDetectDbQueryFailure:
    def test_no_failure(self):
        assert detect_db_query_failure("echo hello", "Success") is None

    def test_nonzero_exit_detected(self):
        _cmd = "sqlite3 test.db 'SELECT 1'"
        result = detect_db_query_failure(
            _cmd,
            "Exit code 1\nError: no such table",
        )
        assert result is not None
        assert "HARD STOP" in result
        assert "exit code 1" in result

    def test_python_traceback_detected(self):
        _cmd = "python3 script.py"
        result = detect_db_query_failure(
            _cmd,
            "Traceback ...\nsqlite3.OperationalError: cannot start a transaction within a transaction",
        )
        # "python" is in command AND output has sqlite3 error pattern -> fires.
        assert result is not None
        assert "DB query FAILED" in result

    def test_python_with_sqlite_traceback(self):
        _cmd = "python3 -c 'import sqlite3; ...'"
        result = detect_db_query_failure(
            _cmd,
            "sqlite3.OperationalError: table not found",
        )
        assert result is not None
        assert "DB query FAILED" in result

    def test_db_router_no_such_column_emits_schema_hint(self):
        """AC-10: db_router query failures naming a stale column point at the packet + who-claims."""
        stale_column = "owner_" "session_id"
        cmd = (
            "python3 -m yoke_core.cli.db_router query "
            f"\"SELECT {stale_column} FROM items WHERE id=1606\""
        )
        result = detect_db_query_failure(
            cmd,
            f"Error: no such column: {stale_column}",
        )
        assert result is not None
        assert stale_column in result
        assert "schema_api_context" in result
        assert "who-claims" in result
        assert "generic target-column guesses" in result

    def test_db_router_no_such_table_emits_schema_hint(self):
        stale_table = "item_" "claims"
        cmd = (
            "python3 -m yoke_core.cli.db_router query "
            f"\"SELECT * FROM {stale_table}\""
        )
        result = detect_db_query_failure(
            cmd,
            f"Error: no such table: {stale_table}",
        )
        assert result is not None
        assert stale_table in result
        assert "schema_api_context" in result
        assert "who-claims" in result

    def test_python_sqlite3_no_such_column_emits_schema_hint(self):
        cmd = "python3 -c 'import sqlite" "3; ...'"
        stale_column = "claim_" "session_id"
        result = detect_db_query_failure(
            cmd,
            f"sqlite" f"3.OperationalError: no such column: {stale_column}",
        )
        assert result is not None
        assert stale_column in result
        assert "schema_api_context" in result
        # When schema hint fires we suppress the generic DB-query failure message
        # so the operator gets one focused remediation, not two overlapping ones.
        assert "DB query FAILED" not in result

    def test_unrelated_no_such_column_phrase_does_not_match(self):
        """The prefix `Error:` / `sqlite3.OperationalError:` is required to avoid false positives."""
        result = detect_db_query_failure(
            "echo hello",
            "(documentation: 'no such column' is the canonical phrase)",
        )
        assert result is None

    def test_structured_field_read_with_historical_error_text_does_not_fire(self):
        """reading a ticket body / spec / docs file via a
        structured ``db_router items get`` command must not emit the
        stale-schema hard-stop just because the rendered content contains
        historical ``Error: no such column`` example text. The hint is
        gated to raw-SQL command shapes (``sqlite3``, ``db_router query``,
        Python sqlite3 invocations) so structured reads of content data
        no longer trip the false-positive class."""

        stale_column = "owner_" "session_id"
        body_text = (
            "## Background\n"
            "Earlier we hit `Error: no such column: " + stale_column + "` "
            "when raw-querying the items table. The fix landed in YOK-XXX.\n"
        )
        for cmd in (
            "python3 -m yoke_core.cli.db_router items get 1618 body",
            "python3 -m yoke_core.cli.db_router items get 1618 spec",
            "python3 -m yoke_core.cli.db_router projects get yoke default_branch",
            "cat /tmp/spec-snippet.md",
        ):
            assert detect_db_query_failure(cmd, body_text) is None, (
                f"command {cmd!r} should not fire the stale-schema hard-stop "
                "when historical error text is embedded in content output"
            )

    def test_db_router_query_against_events_with_stored_envelope_text_does_not_fire(self):
        """A successful raw-SQL ``db_router query`` against the
        ``events`` table whose output rows contain historical envelope
        text matching ``Error: no such column: events.status`` (or the
        ``sqlite3.OperationalError:`` analog) must NOT fire the
        stale-schema hard-stop. The hint is anchored at line-start so
        stored content inside row payloads no longer trips the
        false-positive class. Reproduces the scenario where the
        ``envelope`` column legitimately stores prior failure text."""

        cmd = (
            "python3 -m yoke_core.cli.db_router query "
            "\"SELECT envelope FROM events "
            "WHERE event_name='YokeFunctionCalled' ORDER BY id DESC LIMIT 20\""
        )
        stale_column = "events.status"
        stored_op_error_column = "events.foo"
        output = (
            f"1|{{\"event_name\": \"YokeFunctionCalled\", \"output\": "
            f"\"Error: no such column: {stale_column}\", "
            f"\"ts\": \"2026-05-19\"}}\n"
            f"2|{{\"event_name\": \"YokeFunctionCalled\", \"output\": "
            f"\"sqlite" f"3.OperationalError: no such column: {stored_op_error_column}\", "
            f"\"ts\": \"2026-05-19\"}}\n"
        )
        assert detect_db_query_failure(cmd, output) is None, (
            "stored envelope text inside successful db_router query "
            "results must not fire the schema-hint hard-stop"
        )

    def test_python_sqlite3_read_with_stored_envelope_text_does_not_fire(self):
        """A successful in-process Python sqlite3 read whose output
        contains stored envelope text matching
        ``sqlite3.OperationalError: no such column: events.foo`` from a
        prior session must NOT fire the hard-stop. Same position-aware
        gate as the CLI shape; covers the ``python`` + ``sqlite``
        branch of ``_looks_like_db_query_command``."""

        cmd = (
            "python3 -c 'import sqlite" "3; "
            "rows = sqlite" "3.connect(\"yoke.db\").execute("
            "\"SELECT envelope FROM events\").fetchall(); print(rows)'"
        )
        stored_op_error_column = "events.foo"
        output = (
            f"[(\"{{'event': 'X', 'err': 'sqlite" f"3.OperationalError: "
            f"no such column: {stored_op_error_column}'}}\",), "
            f"(\"{{'event': 'Y', 'err': 'Error: no such column: "
            f"events.status'}}\",)]\n"
        )
        assert detect_db_query_failure(cmd, output) is None, (
            "stored sqlite3.OperationalError text inside successful "
            "Python DB query results must not fire the hard-stop"
        )

    def test_schema_hint_message_names_main_agent_and_subagent_roles(self):
        """the stale-schema hard-stop names the layer-
        explicit packet roles, including ``main_agent`` for the top-level
        Yoke session, plus the five ``*_agent`` subagent roles. The
        message must NOT list only the bare subagent role names."""

        stale_column = "claim_" "session_id"
        cmd = (
            "python3 -m yoke_core.cli.db_router query "
            f"\"SELECT {stale_column} FROM items\""
        )
        result = detect_db_query_failure(
            cmd, f"Error: no such column: {stale_column}"
        )
        assert result is not None
        for role in (
            "main_agent",
            "architect_agent",
            "engineer_agent",
            "tester_agent",
            "simulator_agent",
            "boss_agent",
        ):
            assert role in result, (
                f"stale-schema hint must mention layer-explicit role {role!r}"
            )


# ---------------------------------------------------------------------------
# check_row_count_collapse
# ---------------------------------------------------------------------------


class TestRowCountCollapse:
    def test_no_ddl_no_check(self, tmp_path):
        db_path = str(tmp_path / "yoke.db")
        result = check_row_count_collapse(db_path, "SELECT * FROM items")
        assert not result.collapsed
        assert result.message == ""

    def test_first_invocation_snapshots_baseline(self, tmp_path):
        from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

        # Disposable per-test DB isolates the inline seed across backends.
        with init_test_db(tmp_path, apply_schema=lambda: None) as db_path:
            conn = connect_test_db(db_path)
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
            for i in range(20):
                conn.execute("INSERT INTO items (id) VALUES (%s)", (i,))
            conn.commit()
            conn.close()

            result = check_row_count_collapse(
                db_path,
                "ALTER TABLE items ADD COLUMN foo TEXT",
                session_id="test-session-baseline",
            )
            assert not result.collapsed  # first invocation just snapshots

    def test_collapse_detected(self, tmp_path):
        from yoke_core.domain import project_scratch_dir
        from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

        # Disposable per-test DB isolates the 20-row seed across backends.
        with init_test_db(tmp_path, apply_schema=lambda: None) as db_path:
            conn = connect_test_db(db_path)
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
            for i in range(20):
                conn.execute("INSERT INTO items (id) VALUES (%s)", (i,))
            conn.commit()

            # Write a fake baseline at the helper-resolved storage path.
            import json as _json

            sid = "test-collapse-detect"
            baseline_file = project_scratch_dir.storage_path(
                "db_error_hook", "collapse-state", f"baseline-{sid}.json"
            )
            with open(baseline_file, "w") as f:
                _json.dump({"items": 100}, f)

            conn.close()

            result = check_row_count_collapse(
                db_path,
                "ALTER TABLE items ADD COLUMN bar TEXT",
                session_id=sid,
            )
            assert len(result.collapsed) == 1
            assert result.collapsed[0].table == "items"
            assert "DATA LOSS" in result.message
            assert "migration_audit" in result.message and "backup latest" not in result.message

            # Cleanup
            baseline_file.unlink()


# ---------------------------------------------------------------------------
# analyze_bash_output (unified)
# ---------------------------------------------------------------------------


class TestAnalyzeBashOutput:
    def test_no_issues(self):
        result = analyze_bash_output("echo hello", "hello")
        assert result is None

    def test_stray_db_detected(self, tmp_path):
        stray = tmp_path / "yoke.db"
        stray.touch()
        (tmp_path / "runtime" / "ouroboros").mkdir(parents=True)

        result = analyze_bash_output(
            "some command",
            "ok",
            repo_root=str(tmp_path),
        )
        assert result is not None
        assert "HARD STOP" in result
