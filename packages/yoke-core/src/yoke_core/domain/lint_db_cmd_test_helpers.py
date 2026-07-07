"""Shared helpers for the DB-command policy pytest suites."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from yoke_core.domain.lint_db_cmd import run_hook


def _payload(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def _decision(output: str) -> dict:
    assert output, "expected hook output"
    return json.loads(output)["hookSpecificOutput"]


def _assert_blocks(command: str, yoke_db: str = "") -> dict:
    output = run_hook(_payload(command), yoke_db=yoke_db)
    decision = _decision(output)
    assert decision["permissionDecision"] == "deny", (
        f"expected DENY for {command!r}, got: {output!r}"
    )
    return decision


def _assert_allows(command: str, yoke_db: str = "") -> None:
    output = run_hook(_payload(command), yoke_db=yoke_db)
    # Allow-path is either empty output (no decision) or an explicit "allow"
    # advisory decision.
    if not output:
        return
    decision = _decision(output)
    assert decision["permissionDecision"] == "allow", (
        f"expected ALLOW for {command!r}, got: {output!r}"
    )


def _fresh_live_db(tmp_path: Path) -> str:
    """Create the on-disk legacy DB file the command-policy guard resolves.

    The SQLite file is the guard's probe subject — commands shaped like
    ``sqlite3 '$YOKE_DB' ...`` are the policed surface — so it stays a real
    SQLite file rather than a Postgres test database.
    """
    db_path = tmp_path / "yoke.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            status TEXT,
            spec TEXT,
            design_spec TEXT,
            technical_plan TEXT,
            worktree_plan TEXT,
            shepherd_log TEXT,
            shepherd_caveats TEXT,
            test_results TEXT,
            deploy_log TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER,
            task_num INTEGER,
            status TEXT
        );
        CREATE TABLE events (
            event_name TEXT,
            event_type TEXT,
            source_type TEXT,
            envelope TEXT,
            created_at TEXT,
            event_outcome TEXT
        );
        CREATE TABLE ouroboros_entries (
            id INTEGER PRIMARY KEY,
            body TEXT,
            created_at TEXT
        );
        CREATE TABLE shepherd_verdicts (
            id INTEGER PRIMARY KEY,
            item TEXT,
            transition TEXT,
            verdict TEXT
        );
        CREATE TABLE deployment_runs (
            id INTEGER PRIMARY KEY,
            current_stage TEXT
        );
        CREATE TABLE deployment_run_items (
            run_id INTEGER,
            item_id INTEGER,
            PRIMARY KEY(run_id, item_id)
        );
        CREATE TABLE qa_runs (
            id INTEGER PRIMARY KEY,
            qa_requirement_id INTEGER,
            verdict TEXT
        );
        CREATE VIEW item_progress_view AS
            SELECT id AS item_id, status FROM items;
        """
    )
    conn.commit()
    conn.close()
    return str(db_path)


__all__ = (
    "_assert_allows",
    "_assert_blocks",
    "_decision",
    "_fresh_live_db",
    "_payload",
)
