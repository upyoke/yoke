"""Tests for the coordination-claim service-client surface."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import coordination_claims, db_backend
from runtime.api.domain.coordination_claim_test_support import (
    seed_session,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.api import service_client_coordination_claims
from yoke_core.api.service_client_coordination_claims import (
    COORDINATION_CLAIM_COMMANDS,
    cmd_coordination_claim_acquire,
    cmd_coordination_claim_heartbeat,
    cmd_coordination_claim_list,
    cmd_coordination_claim_release,
)
from yoke_core.domain.coordination_claim_keys import target_for_key


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
            # reads an empty SQLite file (-> "no such table: work_claims").
            # init_test_db created the table in the repointed per-test Postgres
            # DB, so route the CLI's connection factory through the backend-aware
            # seam for the body's lifetime; SQLite is unaffected (the raw path is
            # already correct there).
            monkeypatch.setattr(
                service_client_coordination_claims,
                "_get_db_readwrite",
                lambda: connect_test_db(path),
            )
        yield path


def _seed_claim(db_path: str, **kwargs):
    conn = connect_test_db(db_path)
    try:
        project_id = kwargs.get("project_id", "yoke")
        numeric_project = 1
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
            numeric_project = 99
        session_id = kwargs.get("session_id", "sess-1")
        _ensure_session(conn, session_id, numeric_project)
        return coordination_claims.acquire(
            conn,
            target_for_key(
                kwargs.get("key", "LIVE_DB_MIGRATION:primary"),
                project_id=numeric_project,
                item_id=kwargs.get("item_id", 7),
            ),
            session_id,
        )
    finally:
        conn.close()


def _ensure_session(conn, session_id: str, project_id: int) -> None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT 1 FROM harness_sessions WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        seed_session(conn, session_id, project_id)


def _capture(monkeypatch, capsys) -> tuple:
    """Return (stdout_lines, stderr_lines) after a CLI call."""
    captured = capsys.readouterr()
    return (
        [line for line in captured.out.splitlines() if line],
        [line for line in captured.err.splitlines() if line],
    )


class TestCommandRegistration:
    def test_command_map_wires_all_four_subcommands(self) -> None:
        assert set(COORDINATION_CLAIM_COMMANDS) == {
            "coordination-claim-release",
            "coordination-claim-acquire",
            "coordination-claim-heartbeat",
            "coordination-claim-list",
        }
        assert COORDINATION_CLAIM_COMMANDS["coordination-claim-release"] is (
            cmd_coordination_claim_release
        )


class TestAcquire:
    def test_acquire_returns_claim_envelope(
        self, db_path: str, capsys
    ) -> None:
        conn = connect_test_db(db_path)
        try:
            _ensure_session(conn, "sess-cli", 1)
        finally:
            conn.close()
        rc = cmd_coordination_claim_acquire([
            "--project", "yoke",
            "--key", "QA_HOST:mac-mini-lab",
            "--session-id", "sess-cli",
        ])
        out, err = _capture(None, capsys)
        assert rc == 0, err
        envelope = json.loads(out[-1])
        assert envelope["success"] is True
        assert envelope["claim"]["key"] == "QA_HOST:mac-mini-lab"
        assert envelope["claim"]["target_kind"] == "qa_admission"
        assert envelope["claim"]["session_id"] == "sess-cli"
        assert envelope["claim"]["sticky"] is True
        assert envelope["claim"]["claimed_at"] is not None
        assert envelope["claim"]["last_heartbeat"] is not None

    def test_acquire_records_the_owning_item(
        self, db_path: str, capsys
    ) -> None:
        conn = connect_test_db(db_path)
        try:
            _ensure_session(conn, "sess-cli", 1)
        finally:
            conn.close()
        rc = cmd_coordination_claim_acquire([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--session-id", "sess-cli",
            "--item", "42",
        ])
        out, err = _capture(None, capsys)
        assert rc == 0, err
        envelope = json.loads(out[-1])
        assert envelope["claim"]["owner_item_id"] == 42

    def test_acquire_held_exits_one(self, db_path: str, capsys) -> None:
        _seed_claim(db_path)
        conn = connect_test_db(db_path)
        try:
            _ensure_session(conn, "sess-other", 1)
        finally:
            conn.close()
        rc = cmd_coordination_claim_acquire([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--session-id", "sess-other",
            "--item", "8",
        ])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "HELD"

    def test_acquire_rejects_an_unregistered_key(
        self, db_path: str, capsys
    ) -> None:
        rc = cmd_coordination_claim_acquire([
            "--project", "yoke",
            "--key", "EXAMPLE_OP:x",
            "--session-id", "sess-cli",
        ])
        _, err = _capture(None, capsys)
        assert rc == 1
        assert json.loads(err[-1])["code"] == "USAGE"

    def test_acquire_usage_error_exits_two(self, capsys) -> None:
        rc = cmd_coordination_claim_acquire(["--project", "yoke"])
        _, err = _capture(None, capsys)
        assert rc == 2
        assert any("Usage:" in line for line in err)


class TestHeartbeat:
    def test_heartbeat_refreshes_a_live_claim(
        self, db_path: str, capsys
    ) -> None:
        claim = _seed_claim(db_path)
        rc = cmd_coordination_claim_heartbeat(["--claim-id", str(claim.id)])
        out, _ = _capture(None, capsys)
        assert rc == 0
        envelope = json.loads(out[-1])
        assert envelope["success"] is True
        assert envelope["claim"]["id"] == claim.id

    def test_heartbeat_released_exits_one(
        self, db_path: str, capsys
    ) -> None:
        claim = _seed_claim(db_path)
        conn = connect_test_db(db_path)
        try:
            coordination_claims.release(conn, claim.id, "completed")
        finally:
            conn.close()
        rc = cmd_coordination_claim_heartbeat(["--claim-id", str(claim.id)])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "RELEASED"

    def test_heartbeat_missing_exits_one(
        self, db_path: str, capsys
    ) -> None:
        rc = cmd_coordination_claim_heartbeat(["--claim-id", "999"])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "NOT_FOUND"


class TestList:
    def test_list_filters_by_project(self, db_path: str, capsys) -> None:
        _seed_claim(db_path, key="LIVE_DB_MIGRATION:primary")
        _seed_claim(
            db_path, project_id="other", session_id="sess-other",
            key="LIVE_DB_MIGRATION:secondary",
        )
        rc = cmd_coordination_claim_list(["--project", "yoke"])
        out, _ = _capture(None, capsys)
        assert rc == 0
        envelope = json.loads(out[-1])
        keys = {claim["key"] for claim in envelope["claims"]}
        assert keys == {"LIVE_DB_MIGRATION:primary"}

    def test_list_active_only_excludes_released(
        self, db_path: str, capsys
    ) -> None:
        claim = _seed_claim(db_path)
        conn = connect_test_db(db_path)
        try:
            coordination_claims.release(conn, claim.id, "completed")
        finally:
            conn.close()
        _seed_claim(db_path, session_id="sess-2")
        rc = cmd_coordination_claim_list(["--active-only"])
        out, _ = _capture(None, capsys)
        envelope = json.loads(out[-1])
        assert len(envelope["claims"]) == 1
        assert envelope["claims"][0]["session_id"] == "sess-2"


class TestRelease:
    def test_release_emits_envelope(self, db_path: str, capsys) -> None:
        _seed_claim(db_path)
        rc = cmd_coordination_claim_release([
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
        _seed_claim(db_path)
        monkeypatch.setenv("YOKE_HOOK_EVENT", "SessionEnd")
        rc = cmd_coordination_claim_release([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--reason", "should fail",
        ])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "HOOK_CONTEXT"

    def test_release_missing_claim_exits_one(
        self, db_path: str, capsys
    ) -> None:
        rc = cmd_coordination_claim_release([
            "--project", "yoke",
            "--key", "LIVE_DB_MIGRATION:primary",
            "--reason", "no-op recovery",
        ])
        _, err = _capture(None, capsys)
        assert rc == 1
        envelope = json.loads(err[-1])
        assert envelope["code"] == "NOT_FOUND"
