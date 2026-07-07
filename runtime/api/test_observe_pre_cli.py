"""Tests for yoke_core.domain.observe_pre — CLI subprocess entry point.

CLI tests exec the module as a subprocess to validate the launcher path
and YOKE_DB env-var fallback. Library-level coverage (parse, write,
process_stdin) lives in test_observe_pre.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import (
    apply_sql_script,
    connect_test_db,
    init_test_db,
)
from runtime.api.observe_test_helpers import _PROJECTS_DDL, _PROJECTS_SEED_DDL


# ---------------------------------------------------------------------------
# Fixtures (mirror test_observe_pre.py — kept local so the CLI tests own
# their own DB schema dependency)
# ---------------------------------------------------------------------------


EVENTS_SCHEMA = _PROJECTS_DDL + "\n" + _PROJECTS_SEED_DDL + """
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    source_type TEXT,
    session_id TEXT,
    severity TEXT,
    event_kind TEXT,
    event_type TEXT,
    event_name TEXT,
    event_outcome TEXT,
    service TEXT,
    project_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    agent TEXT,
    tool_name TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    anomaly_flags TEXT,
    tool_use_id TEXT,
    turn_id TEXT,
    hook_event_name TEXT,
    envelope TEXT,
    created_at TEXT
)
"""


@pytest.fixture
def tmp_db(tmp_path: Path):
    """Create a backend-aware DB token with the events table."""
    with init_test_db(tmp_path, apply_schema=_apply_events_schema) as db_path:
        yield str(db_path)


def _apply_events_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_sql_script(conn, EVENTS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _fetch_rows(db_path: str) -> list:
    conn = connect_test_db(db_path)
    try:
        return list(
            conn.execute(
                "SELECT * FROM events WHERE event_name='HarnessToolCallStarted'"
            )
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI entry point — exec module as a subprocess to validate the launcher path
# ---------------------------------------------------------------------------


class TestCliMain:
    def test_cli_inserts_row(self, tmp_db):
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

        payload = json.dumps(
            {
                "tool_use_id": "tu-cli",
                "tool_name": "Bash",
                "session_id": "sess-cli",
                "turn_id": "turn-cli",
            }
        )
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.domain.observe_pre", "--db", tmp_db],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        rows = _fetch_rows(tmp_db)
        assert len(rows) == 1
        row = rows[0]
        assert row["tool_use_id"] == "tu-cli"
        assert row["turn_id"] == "turn-cli"
        assert row["hook_event_name"] == "PreToolUse"

    def test_cli_empty_stdin_exits_zero(self, tmp_db):
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.domain.observe_pre", "--db", tmp_db],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0
        assert _fetch_rows(tmp_db) == []

    def test_cli_malformed_json_exits_zero(self, tmp_db):
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.domain.observe_pre", "--db", tmp_db],
            input="{not valid json",
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0
        assert _fetch_rows(tmp_db) == []

    def test_cli_missing_tool_use_id_exits_zero(self, tmp_db):
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

        payload = json.dumps({"tool_name": "Bash", "session_id": "sess-nope"})
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.domain.observe_pre", "--db", tmp_db],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0
        assert _fetch_rows(tmp_db) == []

    def test_cli_without_db_arg_falls_back_to_yoke_db_env(self, tmp_db):
        """Bare PreToolUse CLI invocation falls back to ``YOKE_DB``.

        ``main()`` must resolve the DB path from ``YOKE_DB`` when no
        ``--db`` argument is passed so ``HarnessToolCallStarted`` emissions
        and ``duration_ms`` telemetry stay alive for hook callers.
        """
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
        env["YOKE_DB"] = tmp_db

        payload = json.dumps(
            {
                "tool_use_id": "tu-env-fallback",
                "tool_name": "Bash",
                "session_id": "sess-env",
            }
        )
        result = subprocess.run(
            [sys.executable, "-m", "yoke_core.domain.observe_pre"],  # no --db
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        rows = _fetch_rows(tmp_db)
        assert len(rows) == 1
        assert rows[0]["tool_use_id"] == "tu-env-fallback"
        assert rows[0]["session_id"] == "sess-env"
