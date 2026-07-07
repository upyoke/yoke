"""Tests for qa_gates.py — verification entry, done, and epic-simulation gates,
plus bypass flags and target parsing."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from yoke_core.domain import db_backend, qa_artifacts
from yoke_core.domain.qa_gates import (
    GateTarget,
    LatestCodeRef,
    check_done_gate,
    check_epic_simulation_gate,
    check_verification_entry,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


# --- Fixtures ---

QA_SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT, public_item_prefix TEXT DEFAULT 'YOK');
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT,
    type TEXT DEFAULT 'issue',
    status TEXT DEFAULT 'implementing',
    worktree TEXT,
    project_id INTEGER DEFAULT 1, project_sequence INTEGER NOT NULL
);
CREATE TABLE epic_tasks (
    epic_id INTEGER,
    task_num INTEGER,
    status TEXT,
    branch TEXT,
    PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT DEFAULT 'explicit',
    success_policy TEXT,
    waived_at TEXT,
    created_at TEXT
);
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER,
    executor_type TEXT,
    qa_kind TEXT,
    verdict TEXT,
    raw_result TEXT,
    created_at TEXT
);
CREATE TABLE qa_artifacts (
    id INTEGER PRIMARY KEY,
    qa_run_id INTEGER,
    artifact_type TEXT,
    content_type TEXT,
    artifact_handle TEXT,
    metadata TEXT
);
-- No epic_simulations table: simulations use qa_requirements + qa_runs.
"""


def _apply_qa_schema() -> None:
    # Zero-arg apply_schema strategy for init_test_db: builds QA_SCHEMA + seeds
    # item 42 against the backend-resolved test DB so the gate code-under-test
    # (connect(db_path) -> same per-test DB) reads the rows the helpers write.
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, QA_SCHEMA)
        conn.execute("INSERT INTO projects (id, slug, name, public_item_prefix) VALUES (1, 'yoke', 'Yoke', 'YOK')")
        conn.execute("INSERT INTO items (id, title, project_sequence) VALUES (42, 'Test item', 42)")
        conn.commit()
    finally:
        conn.close()


def _apply_items_only() -> None:
    # Graceful-pre-migration path: qa_requirements deliberately absent, so
    # _qa_tables_exist returns False and the gate passes.
    conn = db_backend.connect()
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, project_id INTEGER DEFAULT 1, project_sequence INTEGER)")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def qa_db(tmp_path):
    # The seam owns the per-test DB lifecycle: a file under tmp_path on SQLite,
    # a disposable per-test database on Postgres. The yielded db_path threads
    # through unchanged; on Postgres the target is the repointed DSN the context
    # keeps active, so the insert helpers and the gate code hit the same DB.
    with init_test_db(tmp_path, apply_schema=_apply_qa_schema) as db_path:
        yield db_path


def _add_requirement(db_path, item_id=42, qa_kind="implementation_review", qa_phase="verification", blocking="blocking"):
    conn = connect_test_db(db_path)
    cur = conn.execute(
        "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, blocking_mode, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (item_id, qa_kind, qa_phase, blocking, "2026-04-20T00:00:00Z"),
    )
    req_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return req_id


def _add_run(db_path, req_id, verdict="pass", executor_type="agent", created_at=None, raw_result=None):
    conn = connect_test_db(db_path)
    ts = created_at or "2026-04-20T00:00:00Z"
    cur = conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, verdict, executor_type, raw_result, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (req_id, verdict, executor_type, raw_result, ts),
    )
    run_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return run_id


def _add_artifact(db_path, run_id, handle=None):
    """Insert an artifact row. ``handle`` is a handle dict or a path string
    (wrapped as an explicit local handle); default is a repo-relative local
    handle that exists nowhere (the fabrication case)."""
    from yoke_core.domain.qa_artifact_handle import (
        local_handle,
        serialize_handle,
    )

    if handle is None:
        handle = local_handle("test/screenshot.png")
    elif isinstance(handle, str):
        handle = local_handle(handle)
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO qa_artifacts (qa_run_id, artifact_type, artifact_handle) VALUES (%s, 'screenshot', %s)",
        (run_id, serialize_handle(handle)),
    )
    conn.commit()
    conn.close()


def _add_simulation(db_path, epic_id, phase="integration", verdict="pass", body=""):
    # Insert a simulation record (qa_requirement + qa_run) like the real system.
    conn = connect_test_db(db_path)
    sp = json.dumps({"phase": phase})
    raw_result = json.dumps({"phase": phase, "body": body})
    cur = conn.execute(
        "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, success_policy, created_at) VALUES (%s, 'simulation', 'verification', %s, %s) RETURNING id",
        (epic_id, sp, "2026-04-20T00:00:00Z"),
    )
    req_id = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at) VALUES (%s, 'simulation_engine', 'simulation', %s, %s, %s)",
        (req_id, verdict, raw_result, "2026-04-20T00:00:00Z"),
    )
    conn.commit()
    conn.close()


# --- GateTarget tests ---

class TestGateTarget:
    def test_parse_item(self):
        t = GateTarget.parse("42")
        assert t.item_id == 42
        assert t.epic_id is None

    def test_parse_epic_task(self):
        t = GateTarget.parse("833:5")
        assert t.item_id is None
        assert t.epic_id == 833
        assert t.task_num == 5

    def test_where_clause_item(self):
        t = GateTarget.parse("42")
        sql, params = t.where_clause()
        assert "item_id" in sql
        assert params == (42,)

    def test_where_clause_epic(self):
        t = GateTarget.parse("833:5")
        sql, params = t.where_clause()
        assert "epic_id" in sql
        assert params == (833, 5)

    def test_display_name_item(self):
        assert GateTarget.parse(str(TEST_ITEM_ID)).display_name() == TEST_ITEM_REF

    def test_display_name_epic(self):
        assert GateTarget.parse("833:5").display_name() == "epic 833/task 5"


# --- check_verification_entry ---

class TestCheckVerificationEntry:
    def test_tc_passes_when_requirement_exists(self, qa_db):
        _add_requirement(qa_db)
        target = GateTarget.parse("42")
        result = check_verification_entry(target, qa_db)
        assert result.passed

    def test_tc_fails_when_no_requirements(self, qa_db):
        target = GateTarget.parse("42")
        result = check_verification_entry(target, qa_db)
        assert not result.passed
        assert any("no qa_requirements found" in e for e in result.errors)

    def test_tc_bypass_flag(self, qa_db, monkeypatch):
        monkeypatch.setenv("YOKE_QA_GATE_BYPASS", "1")
        target = GateTarget.parse("42")
        result = check_verification_entry(target, qa_db)
        assert result.passed

    def test_tc_graceful_without_qa_tables(self, tmp_path):
        # Gate passes gracefully if the qa_requirements table doesn't exist.
        with init_test_db(tmp_path, apply_schema=_apply_items_only) as db_path:
            target = GateTarget.parse("42")
            result = check_verification_entry(target, db_path)
            assert result.passed


# Reviewed-implementation gate coverage lives in test_qa_gates_reviewed_impl.py.
# --- check_done_gate ---

class TestCheckDoneGate:
    def test_tc_passes_when_all_satisfied(self, qa_db):
        req_id = _add_requirement(qa_db, qa_phase="verification")
        _add_run(qa_db, req_id, "pass")
        req_id2 = _add_requirement(qa_db, qa_phase="post_deploy")
        _add_run(qa_db, req_id2, "pass")
        target = GateTarget.parse("42")
        result = check_done_gate(target, qa_db)
        assert result.passed

    def test_tc_fails_when_unsatisfied_any_phase(self, qa_db):
        _add_requirement(qa_db, qa_phase="post_deploy")
        target = GateTarget.parse("42")
        result = check_done_gate(target, qa_db)
        assert not result.passed
        assert any("done" in e for e in result.errors)

    def test_tc_bypass_flag(self, qa_db, monkeypatch):
        monkeypatch.setenv("YOKE_QA_GATE_BYPASS", "1")
        _add_requirement(qa_db)
        target = GateTarget.parse("42")
        result = check_done_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_s3_handle_passes_without_local_file(self, qa_db):
        # Done gate accepts uploaded evidence structurally: an s3 handle is
        # durable-by-construction and needs no file on this machine.
        from yoke_core.domain.qa_artifact_handle import s3_handle

        req_id = _add_requirement(qa_db, qa_kind="browser_smoke")
        run_id = _add_run(qa_db, req_id, "pass", executor_type="browser_substrate")
        _add_artifact(
            qa_db, run_id,
            s3_handle("proj-prod-artifacts", "qa-artifacts/testproj/42/8/shot.png"),
        )
        target = GateTarget.parse("42")
        result = check_done_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_sha_mismatch_blocks_done(self, qa_db, tmp_path):
        # Done gate rejects browser passes recorded against older code.
        req_id = _add_requirement(qa_db, qa_kind="browser_smoke")
        raw = f'{{"code_identity":{{"branch":"{TEST_ITEM_REF}","sha":"old123"}}}}'
        run_id = _add_run(
            qa_db, req_id, "pass", executor_type="browser_substrate",
            created_at="2024-01-01T00:00:00Z", raw_result=raw,
        )
        art_file = tmp_path / "done-shot.png"
        art_file.write_bytes(b"PNG")
        _add_artifact(qa_db, run_id, str(art_file))
        target = GateTarget.parse("42")
        latest = LatestCodeRef(
            branch=TEST_ITEM_REF, sha="fresh999", timestamp="2025-01-01T00:00:00Z",
        )
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_latest_code_ref",
            return_value=latest,
        ):
            result = check_done_gate(target, qa_db)
        assert not result.passed
        assert any("Latest SHA: fresh999" in e for e in result.errors)


# --- check_epic_simulation_gate ---

class TestCheckEpicSimulationGate:
    def test_tc_clean_passes(self, qa_db):
        _add_simulation(qa_db, 42, "integration", "pass", "")
        result = check_epic_simulation_gate(42, qa_db)
        assert result.passed

    def test_tc_gaps_non_critical_passes(self, qa_db):
        body = "### GAP #1: Minor spacing issue\nSeverity: [WARNING]\nRecommendation: PROCEED"
        _add_simulation(qa_db, 42, "integration", "fail", body)
        result = check_epic_simulation_gate(42, qa_db)
        assert result.passed

    def test_tc_gaps_non_critical_logs_summary(self, qa_db, capsys):
        body = (
            "## Gaps Found: 1 (0 critical, 0 warning, 1 note)\n\n"
            "### GAP #1: Minor documentation drift\nSeverity: [NOTE]\nRecommendation: PROCEED"
        )
        _add_simulation(qa_db, 42, "integration", "fail", body)
        result = check_epic_simulation_gate(42, qa_db)
        captured = capsys.readouterr()
        assert result.passed
        assert "## Gaps Found: 1" in captured.err
        assert "### GAP #1: Minor documentation drift" in captured.err

    def test_tc_gaps_critical_fails(self, qa_db):
        body = "### GAP #1: Data loss\nSeverity: [CRITICAL]\nRecommendation: BLOCK"
        _add_simulation(qa_db, 42, "integration", "fail", body)
        result = check_epic_simulation_gate(42, qa_db)
        assert not result.passed
        assert any("blocking gaps" in e for e in result.errors)

    def test_tc_no_simulation_fails(self, qa_db):
        result = check_epic_simulation_gate(42, qa_db)
        assert not result.passed
        assert any("No integration simulation" in e for e in result.errors)

    def test_tc_bypass_flag(self, qa_db, monkeypatch):
        monkeypatch.setenv("YOKE_SKIP_SIMULATION", "1")
        result = check_epic_simulation_gate(42, qa_db)
        assert result.passed
