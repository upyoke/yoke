"""CLI entry-point tests + parse/full-pipeline performance budgets."""

from __future__ import annotations

import json
import time
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain.observe import (
    build_envelope,
    detect_anomalies,
    insert_event,
    parse_hook_event,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.observe_full_test_helpers import (
    _PROJECTS_DDL,
    _seed_projects,
    _EVENTS_DDL,
    SAMPLE_BASH_SUCCESS,
    make_events_db_conn,
)


@pytest.fixture
def events_db():
    conn = make_events_db_conn()
    yield conn
    conn.close()


@pytest.fixture
def events_db_file(tmp_path):
    from yoke_core.domain import db_backend

    def _apply_schema() -> None:
        conn = db_backend.connect()
        try:
            apply_fixture_ddl(conn, _PROJECTS_DDL)
            _seed_projects(conn)
            apply_fixture_ddl(conn, _EVENTS_DDL)
        finally:
            conn.close()

    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        yield db_path


def _count_events(db_path: str) -> int:
    conn = connect_test_db(db_path)
    try:
        return conn.execute("SELECT count(*) FROM events").fetchone()[0]
    finally:
        conn.close()


def _fetch_one(db_path: str, sql: str):
    conn = connect_test_db(db_path)
    try:
        return conn.execute(sql).fetchone()
    finally:
        conn.close()


class TestCLI:
    """CLI entry point tests using main() directly with mocked stdin."""

    def test_cli_with_valid_json(self, events_db_file):
        """CLI processes JSON from stdin and inserts to DB."""
        from yoke_core.domain.observe import main as observe_main

        data = json.dumps(SAMPLE_BASH_SUCCESS)
        with mock.patch("sys.stdin", StringIO(data)):
            with mock.patch("sys.argv", [
                "observe",
                "--db", events_db_file,
                "--session-id", "cli-test",
                "--hook-event", "PostToolUse",
            ]):
                observe_main()

        assert _count_events(events_db_file) == 1

    def test_cli_empty_stdin(self, events_db_file):
        """CLI handles empty stdin gracefully."""
        from yoke_core.domain.observe import main as observe_main

        with mock.patch("sys.stdin", StringIO("")):
            with mock.patch("sys.argv", [
                "observe",
                "--db", events_db_file,
                "--session-id", "empty-test",
                "--hook-event", "PostToolUse",
            ]):
                observe_main()  # should not raise

    def test_cli_invalid_json(self, events_db_file):
        """CLI handles invalid JSON gracefully."""
        from yoke_core.domain.observe import main as observe_main

        with mock.patch("sys.stdin", StringIO("not-json{")):
            with mock.patch("sys.argv", [
                "observe",
                "--db", events_db_file,
                "--session-id", "bad-json",
                "--hook-event", "PostToolUse",
            ]):
                observe_main()  # should not raise

    def test_cli_without_db_arg_falls_back_to_canonical(self, events_db_file):
        """AC-3: CLI without ``--db`` must fall back to the
        canonical yoke.db via ``db_helpers.resolve_db_path``.

        Prior to the tracked-launcher fix the Claude PostToolUse hook launcher
        injected ``YOKE_DB=... --db .../data/yoke.db`` pointing at
        the worktree-local path (``.worktrees/<branch>/data/yoke.db``),
        bypassing the worktree-aware resolver and splitting telemetry off
        the canonical ledger. The launcher now passes only
        ``--project-dir`` + ``--hook-event``; ``observe.main()`` resolves
        the DB path via the shared Python resolver so the event still
        lands in the canonical DB. The resolver is stubbed here to point
        at a per-test temp DB so the test does not depend on the repo
        layout.
        """
        from yoke_core.domain import observe as observe_mod

        data = json.dumps(SAMPLE_BASH_SUCCESS)
        with mock.patch.object(
            observe_mod, "_resolve_db_fallback", return_value=events_db_file
        ):
            with mock.patch("sys.stdin", StringIO(data)):
                with mock.patch(
                    "sys.argv",
                    [
                        "observe",
                        "--session-id",
                        "fallback-test",
                        "--hook-event",
                        "PostToolUse",
                    ],
                ):
                    observe_mod.main()

        assert _count_events(events_db_file) == 1, (
            "observe.main() without --db must fall back to the canonical DB "
            "path from db_helpers.resolve_db_path"
        )

    def test_cli_explicit_db_wins_over_fallback(self, events_db_file, tmp_path):
        """AC-3: explicit ``--db`` must still take precedence over
        the fallback so tests, Codex, and programmatic callers stay
        deterministic even when the main-repo DB exists on disk.
        """
        from yoke_core.domain import observe as observe_mod

        bogus_fallback = str(tmp_path / "should-not-be-used.db")
        data = json.dumps(SAMPLE_BASH_SUCCESS)
        with mock.patch.object(
            observe_mod, "_resolve_db_fallback", return_value=bogus_fallback
        ):
            with mock.patch("sys.stdin", StringIO(data)):
                with mock.patch(
                    "sys.argv",
                    [
                        "observe",
                        "--db",
                        events_db_file,
                        "--session-id",
                        "explicit-wins",
                        "--hook-event",
                        "PostToolUse",
                    ],
                ):
                    observe_mod.main()

        assert _count_events(events_db_file) == 1

        assert not Path(bogus_fallback).exists()

    def test_cli_no_db_fallback_failure_is_silent(self):
        """Resolver failures must degrade silently — the hook path must
        never surface an exception to the caller."""
        from yoke_core.domain import observe as observe_mod

        data = json.dumps(SAMPLE_BASH_SUCCESS)
        with mock.patch.object(
            observe_mod, "_resolve_db_fallback", return_value=None
        ):
            with mock.patch("sys.stdin", StringIO(data)):
                with mock.patch(
                    "sys.argv",
                    [
                        "observe",
                        "--session-id",
                        "no-db-test",
                        "--hook-event",
                        "PostToolUse",
                    ],
                ):
                    observe_mod.main()  # should not raise

    def test_cli_with_item_id_and_task_num(self, events_db_file):
        """CLI passes item_id and task_num through."""
        from yoke_core.domain.observe import main as observe_main

        data = json.dumps(SAMPLE_BASH_SUCCESS)
        with mock.patch("sys.stdin", StringIO(data)):
            with mock.patch("sys.argv", [
                "observe",
                "--db", events_db_file,
                "--session-id", "enriched",
                "--hook-event", "PostToolUse",
                "--item-id", "42",
                "--task-num", "5",
                "--agent-type", "engineer",
            ]):
                observe_main()

        row = _fetch_one(events_db_file, "SELECT item_id, task_num, agent FROM events")
        assert row[0] == "42"
        assert row[1] == 5
        assert row[2] == "engineer"

    def test_cli_uses_payload_session_id_when_arg_absent(self, events_db_file):
        from yoke_core.domain.observe import main as observe_main

        data = dict(SAMPLE_BASH_SUCCESS)
        data["session_id"] = "payload-session"
        with mock.patch("sys.stdin", StringIO(json.dumps(data))):
            with mock.patch(
                "sys.argv",
                [
                    "observe",
                    "--db",
                    events_db_file,
                    "--hook-event",
                    "PostToolUse",
                ],
            ):
                observe_main()

        row = _fetch_one(events_db_file, "SELECT session_id FROM events")
        assert row[0] == "payload-session"


class TestPerformance:
    def test_parse_under_200ms(self):
        """Module import + parse_hook_event must complete in <200ms."""
        start = time.monotonic()
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS,
            session_id="perf-test",
            hook_event="PostToolUse",
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        assert rec is not None
        assert elapsed_ms < 200, f"parse_hook_event took {elapsed_ms:.1f}ms"

    def test_full_pipeline_under_500ms(self, events_db):
        """Full parse -> detect -> envelope -> insert pipeline under 500ms."""
        start = time.monotonic()
        rec = parse_hook_event(
            SAMPLE_BASH_SUCCESS,
            session_id="perf-pipeline",
            hook_event="PostToolUse",
        )
        assert rec is not None
        detect_anomalies(rec)
        env = build_envelope(rec)
        insert_event(events_db, env)
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 500, f"Full pipeline took {elapsed_ms:.1f}ms"
