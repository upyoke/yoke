"""Tests for the coordination-lease service-client surface."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import coordination_leases, db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.api import service_client_coordination_leases
from yoke_core.api.service_client_coordination_leases import (
    COORDINATION_LEASE_COMMANDS,
    cmd_coordination_lease_acquire,
    cmd_coordination_lease_heartbeat,
    cmd_coordination_lease_list,
    cmd_coordination_lease_release,
)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    with init_test_db(tmp_path) as path:
        # The CLI commands resolve their own connection from YOKE_DB; keep it
        # pointed at the test DB for the whole body (the seam only sets it for
        # the duration of the schema apply).
        monkeypatch.setenv("YOKE_DB", path)
        if db_backend.is_postgres():
            # The CLI's _get_db_readwrite() opens a raw sqlite3 connection to
            # the YOKE_DB path, which on Postgres bypasses the backend and
            # reads an empty SQLite file (-> "no such table: coordination_leases").
            # init_test_db created the table in the repointed per-test Postgres
            # DB, so route the CLI's connection factory through the backend-aware
            # seam for the body's lifetime; SQLite is unaffected (the raw path is
            # already correct there).
            monkeypatch.setattr(
                service_client_coordination_leases,
                "_get_db_readwrite",
                lambda: connect_test_db(path),
            )
        yield path


def _seed_lease(db_path: str, **kwargs) -> coordination_leases.Lease:
    conn = connect_test_db(db_path)
    try:
        project_id = kwargs.get("project_id", "yoke")
        if isinstance(project_id, str) and project_id not in {"yoke"}:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            conn.execute(
                "INSERT INTO projects "
                "(id, slug, name, public_item_prefix, created_at) "
                f"VALUES (99, {p}, {p}, 'YOK', '2026-01-01T00:00:00Z') "
                "ON CONFLICT (id) DO NOTHING",
                (project_id, project_id),
            )
            conn.commit()
        return coordination_leases.acquire_lease(
            conn,
            project_id,
            kwargs.get("lease_key", "LIVE_DB_MIGRATION:primary"),
            kwargs.get("session_id", "sess-1"),
            actor_id=kwargs.get("actor_id"),
        )
    finally:
        conn.close()


def _capture(monkeypatch, capsys) -> tuple:
    """Return (stdout_lines, stderr_lines) after a CLI call."""
    captured = capsys.readouterr()
    return (
        [line for line in captured.out.splitlines() if line],
        [line for line in captured.err.splitlines() if line],
    )


class TestCommandRegistration:
    def test_command_map_wires_all_four_subcommands(self) -> None:
        assert set(COORDINATION_LEASE_COMMANDS) == {
            "coordination-lease-release",
            "coordination-lease-acquire",
            "coordination-lease-heartbeat",
            "coordination-lease-list",
        }
        assert COORDINATION_LEASE_COMMANDS["coordination-lease-release"] is (
            cmd_coordination_lease_release
        )


class TestAcquire:
    def test_acquire_returns_lease_envelope(
        self, db_path: str, capsys
    ) -> None:
        rc = cmd_coordination_lease_acquire([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--session-id", "sess-cli",
        ])
        out, err = _capture(None, capsys)
        assert rc == 0, err
        envelope = json.loads(out[-1])
        assert envelope["success"] is True
        assert envelope["lease"]["project_id"] == 1
        assert envelope["lease"]["lease_key"] == "LIVE_DB_MIGRATION:primary"
        assert envelope["lease"]["session_id"] == "sess-cli"
        assert envelope["lease"]["actor_id"] is None
        assert envelope["lease"]["acquired_at"] is not None
        assert envelope["lease"]["heartbeat_at"] is not None

    def test_acquire_with_actor_id(self, db_path: str, capsys) -> None:
        rc = cmd_coordination_lease_acquire([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--session-id", "sess-cli",
            "--actor-id", "ben",
        ])
        out, _ = _capture(None, capsys)
        assert rc == 0
        envelope = json.loads(out[-1])
        assert envelope["lease"]["actor_id"] == "ben"

    def test_acquire_held_exits_one(self, db_path: str, capsys) -> None:
        _seed_lease(db_path)
        rc = cmd_coordination_lease_acquire([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--session-id", "sess-other",
        ])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "HELD"

    def test_acquire_usage_error_exits_two(self, capsys) -> None:
        rc = cmd_coordination_lease_acquire(["--project", "yoke"])
        _, err = _capture(None, capsys)
        assert rc == 2
        assert any("Usage:" in line for line in err)


class TestHeartbeat:
    def test_heartbeat_refreshes_live_lease(
        self, db_path: str, capsys
    ) -> None:
        lease = _seed_lease(db_path)
        rc = cmd_coordination_lease_heartbeat([
            "--lease-id", str(lease.id),
        ])
        out, _ = _capture(None, capsys)
        assert rc == 0
        envelope = json.loads(out[-1])
        assert envelope["success"] is True
        assert envelope["lease"]["id"] == lease.id

    def test_heartbeat_released_exits_one(
        self, db_path: str, capsys
    ) -> None:
        lease = _seed_lease(db_path)
        conn = connect_test_db(db_path)
        try:
            coordination_leases.release_lease(conn, lease.id, "completed")
        finally:
            conn.close()
        rc = cmd_coordination_lease_heartbeat([
            "--lease-id", str(lease.id),
        ])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "RELEASED"

    def test_heartbeat_missing_exits_one(
        self, db_path: str, capsys
    ) -> None:
        rc = cmd_coordination_lease_heartbeat(["--lease-id", "999"])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "NOT_FOUND"


class TestList:
    def test_list_filters_by_project(self, db_path: str, capsys) -> None:
        _seed_lease(db_path, lease_key="LIVE_DB_MIGRATION:primary")
        _seed_lease(
            db_path, project_id="other", session_id="sess-other",
            lease_key="EXAMPLE_OP:x",
        )
        rc = cmd_coordination_lease_list(["--project", "yoke"])
        out, _ = _capture(None, capsys)
        assert rc == 0
        envelope = json.loads(out[-1])
        keys = {lease["lease_key"] for lease in envelope["leases"]}
        assert keys == {"LIVE_DB_MIGRATION:primary"}

    def test_list_active_only_excludes_released(
        self, db_path: str, capsys
    ) -> None:
        lease = _seed_lease(db_path)
        conn = connect_test_db(db_path)
        try:
            coordination_leases.release_lease(conn, lease.id, "completed")
        finally:
            conn.close()
        _seed_lease(db_path, session_id="sess-2")
        rc = cmd_coordination_lease_list(["--active-only"])
        out, _ = _capture(None, capsys)
        envelope = json.loads(out[-1])
        assert len(envelope["leases"]) == 1
        assert envelope["leases"][0]["session_id"] == "sess-2"


class TestRelease:
    def test_release_emits_envelope(self, db_path: str, capsys) -> None:
        _seed_lease(db_path)
        rc = cmd_coordination_lease_release([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--reason", "operator recovery in cli test",
        ])
        out, _ = _capture(None, capsys)
        assert rc == 0
        envelope = json.loads(out[-1])
        assert envelope["success"] is True
        assert envelope["prior_session_id"] == "sess-1"
        assert envelope["operator_reason"] == "operator recovery in cli test"

    def test_release_rejects_hook_context(
        self, db_path: str, capsys, monkeypatch
    ) -> None:
        _seed_lease(db_path)
        monkeypatch.setenv("YOKE_HOOK_EVENT", "SessionEnd")
        rc = cmd_coordination_lease_release([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--reason", "should fail",
        ])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "HOOK_CONTEXT"

    def test_release_missing_lease_exits_one(
        self, db_path: str, capsys
    ) -> None:
        rc = cmd_coordination_lease_release([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--reason", "no-op recovery",
        ])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "NOT_FOUND"
