"""Reviewed-implementation gate coverage for yoke_core.domain.qa_gates.

Sibling to ``test_qa_gates.py`` which holds verification-entry, done, and
epic-simulation coverage. Fixtures are duplicated locally rather than
hoisted to a directory-wide conftest because they are scoped to qa_gates.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from yoke_core.domain import db_backend, qa_artifacts
from yoke_core.domain.qa_gates import (
    GateTarget,
    LatestCodeRef,
    check_reviewed_implementation_gate,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


QA_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    name TEXT,
    public_item_prefix TEXT DEFAULT 'YOK'
);
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT,
    type TEXT DEFAULT 'issue',
    status TEXT DEFAULT 'implementing',
    worktree TEXT,
    project_id INTEGER DEFAULT 1,
    project_sequence INTEGER NOT NULL
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
"""


def _apply_qa_schema() -> None:
    """``apply_schema`` strategy building ``QA_SCHEMA`` on the resolved test DB.

    Resolves its connection through the backend factory (``YOKE_DB`` on
    SQLite, the repointed ``YOKE_PG_DSN`` on Postgres).
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, QA_SCHEMA)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'YOK')",
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def qa_db(tmp_path):
    # The seam owns the per-test DB lifecycle: a real file under tmp_path on
    # SQLite, a disposable per-test database (dropped on context exit) on
    # Postgres. The test body runs while this generator is suspended at the
    # yield, so the repointed YOKE_PG_DSN init_test_db keeps active selects
    # the per-test database for the gate code-under-test on Postgres.
    with init_test_db(tmp_path, apply_schema=_apply_qa_schema) as db_path:
        with mock.patch.dict(os.environ, {"YOKE_DB": db_path}, clear=False):
            conn = connect_test_db(db_path)
            conn.execute(
                "INSERT INTO items (id, title, project_sequence) "
                "VALUES (42, 'Test item', 42)",
            )
            conn.commit()
            conn.close()
            yield db_path


def _add_requirement(db_path, item_id=42, qa_kind="implementation_review",
                     qa_phase="verification", blocking="blocking"):
    conn = connect_test_db(db_path)
    cur = conn.execute(
        "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, blocking_mode, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (item_id, qa_kind, qa_phase, blocking, "2026-04-20T00:00:00Z"),
    )
    req_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return req_id


def _add_run(db_path, req_id, verdict="pass", executor_type="agent",
             created_at=None, raw_result=None):
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


class TestCheckReviewedImplementationGate:
    def test_tc_passes_when_all_satisfied(self, qa_db):
        req_id = _add_requirement(qa_db)
        _add_run(qa_db, req_id, "pass")
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_fails_when_unsatisfied(self, qa_db):
        _add_requirement(qa_db)
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert not result.passed
        assert any("unsatisfied" in e for e in result.errors)

    def test_tc_unsatisfied_remediation_points_to_advance(self, qa_db):
        """generic gate failures tell the operator which advance command to run."""
        _add_requirement(qa_db)
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert f"/yoke advance {TEST_ITEM_REF} reviewed-implementation" in joined
        assert "browser QA and project E2E phases automatically" in joined

    def test_tc_passes_when_waived(self, qa_db):
        conn = connect_test_db(qa_db)
        conn.execute(
            "INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, blocking_mode, waived_at) "
            "VALUES (42, 'implementation_review', 'verification', 'blocking', '2024-01-01T00:00:00Z')"
        )
        conn.commit()
        conn.close()
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_evidence_enforcement(self, qa_db):
        """Browser requirements need substrate execution + artifacts."""
        req_id = _add_requirement(qa_db, qa_kind="browser_smoke")
        # Only agent-executed run — should fail
        _add_run(qa_db, req_id, "pass", executor_type="agent")
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert not result.passed
        assert any("substrate evidence" in e for e in result.errors)

    def test_tc_browser_evidence_remediation_text(self, qa_db):
        """Gate error includes remediation commands for manual fallback."""
    def test_tc_browser_evidence_remediation_points_to_advance(self, qa_db):
        """browser evidence failures point back to /yoke advance."""
        req_id = _add_requirement(qa_db, qa_kind="browser_smoke")
        _add_run(qa_db, req_id, "pass", executor_type="agent")
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "Remediation (manual screenshot fallback):" in joined
        assert "yoke qa run add" in joined
        assert "yoke qa artifact add" in joined
        # One-step --artifact-path stays the labelled operator-debug shape.
        assert "qa run-add" in joined
        assert "--artifact-path" in joined
        assert "snapshot screenshot <URL>" in joined
        assert "--qa-kind <REQ_KIND>" in joined
        assert f"/yoke advance {TEST_ITEM_REF} reviewed-implementation" in joined
        assert "browser QA automatically before updating status" in joined

    def test_tc_browser_evidence_passes_with_substrate(self, qa_db, tmp_path):
        """Browser requirement passes with substrate run + artifact on disk."""
        req_id = _add_requirement(qa_db, qa_kind="browser_smoke")
        run_id = _add_run(qa_db, req_id, "pass", executor_type="browser_substrate")
        # Create artifact with real file
        art_file = tmp_path / "screenshot.png"
        art_file.write_bytes(b"PNG")
        _add_artifact(qa_db, run_id, str(art_file))
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_s3_handle_passes_without_local_file(self, qa_db):
        """Uploaded (s3-handle) evidence passes without a machine-local file."""
        from yoke_core.domain.qa_artifact_handle import s3_handle

        req_id = _add_requirement(qa_db, qa_kind="browser_smoke")
        run_id = _add_run(qa_db, req_id, "pass", executor_type="browser_substrate")
        _add_artifact(
            qa_db, run_id,
            s3_handle("proj-prod-artifacts", "qa-artifacts/testproj/42/7/shot.png"),
        )
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_non_blocking_ignored(self, qa_db):
        """Non-blocking requirements don't block the gate."""
        _add_requirement(qa_db, blocking="non_blocking")
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_bypass_flag(self, qa_db, monkeypatch):
        monkeypatch.setenv("YOKE_QA_GATE_BYPASS", "1")
        _add_requirement(qa_db)
        target = GateTarget.parse("42")
        result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed

    def test_tc_browser_freshness_accepts_exact_sha_match(self, qa_db, tmp_path):
        """Fresh browser runs can match the latest code by explicit SHA."""
        req_id = _add_requirement(qa_db, qa_kind="browser_smoke")
        run_id = _add_run(
            qa_db,
            req_id,
            "pass",
            executor_type="browser_substrate",
            created_at="2024-01-01T00:00:00Z",
            raw_result=f'{{"code_identity":{{"branch":"{TEST_ITEM_REF}","sha":"fresh123"}}}}',
        )
        art_file = tmp_path / "screenshot.png"
        art_file.write_bytes(b"PNG")
        _add_artifact(qa_db, run_id, str(art_file))
        target = GateTarget.parse("42")
        with mock.patch(
            "yoke_core.domain.qa_gates._resolve_latest_code_ref",
            return_value=LatestCodeRef(
                branch=TEST_ITEM_REF,
                sha="fresh123",
                timestamp="2025-01-01T00:00:00Z",
            ),
        ):
            result = check_reviewed_implementation_gate(target, qa_db)
        assert result.passed
