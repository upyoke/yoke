"""Tests for the hooks-expected-but-silent health check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_silent_hooks as mod


_SESSIONS_DDL = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    ended_at TEXT,
    last_tool_call_at TEXT,
    tool_call_count INTEGER NOT NULL DEFAULT 0
);
"""

_EVENTS_DDL = """
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    event_name TEXT,
    created_at TEXT
);
"""


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    connection = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    apply_fixture_ddl(connection, _SESSIONS_DDL)
    apply_fixture_ddl(connection, _EVENTS_DDL)
    yield connection
    connection.close()


def _manifest_root(root: Path) -> None:
    manifest_dir = root / "runtime" / "harness" / "claude"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps(
            {
                "harness_id": "claude-code",
                "supports": {
                    "optional_local_affordances": ["session_start_hook"],
                },
                "worktree_hook_enablement": {
                    "config_path": ".claude/settings.json",
                    "operations": ["verify_hook_config"],
                    "environment": {
                        "root_variable": "YOKE_ROOT",
                        "root_expression": "${PWD}",
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _cursor_manifest_root(root: Path) -> None:
    _manifest_root(root)
    manifest_dir = root / "runtime" / "harness" / "cursor"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps(
            {
                "harness_id": "cursor",
                "worktree_hook_enablement": {
                    "config_path": ".cursor/hooks.json",
                    "operations": ["verify_hook_config"],
                    "environment": {
                        "root_variable": "YOKE_ROOT",
                        "root_expression": "${CURSOR_PROJECT_DIR:-$PWD}",
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _run(conn, monkeypatch, root: Path):
    _manifest_root(root)
    monkeypatch.setattr(mod._base, "_resolve_repo_root", lambda: str(root))
    records = RecordCollector()
    mod.hc_hooks_expected_but_silent(conn, DoctorArgs(), records)
    assert len(records.results) == 1
    return records.results[0]


def test_declares_the_discovered_project_check() -> None:
    assert [check.slug for check in mod.PROJECT_HEALTH_CHECKS] == [
        "hooks-expected-but-silent",
    ]
    assert mod.PROJECT_HEALTH_CHECKS[0].fn is mod.hc_hooks_expected_but_silent


def test_warns_per_manifest_harness_when_tool_activity_has_no_hook_telemetry(
    conn,
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, last_tool_call_at, tool_call_count) "
        "VALUES (%s, %s, %s, %s)",
        ("claude-session", "claude-code", "2026-08-02T12:00:00Z", 1),
    )

    result = _run(conn, monkeypatch, tmp_path)

    assert result.check_id == mod.HC_SLUG
    assert result.result == "WARN"
    assert "hooks-expected-but-silent" in result.detail
    assert "claude-code" in result.detail
    assert "session_start_hook" in result.detail


def test_passes_when_hook_dispatch_telemetry_exists(
    conn,
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, last_tool_call_at, tool_call_count) "
        "VALUES (%s, %s, %s, %s)",
        ("claude-session", "claude-code", "2026-08-02T12:00:00Z", 1),
    )
    conn.execute(
        "INSERT INTO events (session_id, event_name, created_at) "
        "VALUES (%s, %s, %s)",
        ("claude-session", "HookDispatchTelemetry", "2026-08-02T12:00:00Z"),
    )

    assert _run(conn, monkeypatch, tmp_path).result == "PASS"


def test_skips_when_session_telemetry_schema_is_absent(monkeypatch, tmp_path: Path) -> None:
    name = pg_testdb.create_test_database()
    connection = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    try:
        assert _run(connection, monkeypatch, tmp_path).result == "SKIP"
    finally:
        connection.close()


def test_warns_when_cursor_config_is_present_but_symlinked(
    conn,
    monkeypatch,
    tmp_path: Path,
) -> None:
    _cursor_manifest_root(tmp_path)
    canonical = tmp_path / "runtime" / "harness" / "cursor" / "hooks.json"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text('{"version": 1, "hooks": {}}\n', encoding="utf-8")
    native = tmp_path / ".cursor"
    native.mkdir()
    (native / "hooks.json").symlink_to(
        "../runtime/harness/cursor/hooks.json"
    )
    monkeypatch.setattr(mod._base, "_resolve_repo_root", lambda: str(tmp_path))

    records = RecordCollector()
    mod.hc_hooks_expected_but_silent(conn, DoctorArgs(), records)

    assert records.results[0].result == "WARN"
    assert "cursor" in records.results[0].detail
    assert "contains symlink component" in records.results[0].detail
