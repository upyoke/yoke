"""Tests for the fail-closed planned-transition QA predicate."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.qa_plan_gate import check_plan_simulation_satisfied
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


TEST_ITEM_ID = 42

QA_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT
);
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
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
"""

# Minimal schema for the fail-closed case: only ``items`` exists, so the
# code-under-test's backend-native table-existence check reports
# ``qa_requirements`` absent.
ITEMS_ONLY_SCHEMA = "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT);"


def _apply_qa_schema() -> None:
    """``apply_schema`` strategy building ``QA_SCHEMA`` on the resolved test DB.

    Resolves its connection through the backend factory (``YOKE_DB`` on
    SQLite, the repointed ``YOKE_PG_DSN`` on Postgres).
    """
    _apply_inline_schema(QA_SCHEMA)


def _apply_items_only_schema() -> None:
    """``apply_schema`` strategy for the fail-closed (no qa tables) case."""
    _apply_inline_schema(ITEMS_ONLY_SCHEMA)


def _apply_inline_schema(schema_sql: str) -> None:
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, schema_sql)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def qa_db(tmp_path: Path):
    # The seam owns the per-test DB lifecycle: a real file under tmp_path on
    # SQLite, a disposable per-test database (dropped on context exit) on
    # Postgres. The test body runs while this generator is suspended at the
    # yield, so the repointed YOKE_PG_DSN init_test_db keeps active selects
    # the per-test database for the code-under-test on Postgres.
    with init_test_db(tmp_path, apply_schema=_apply_qa_schema) as db_path:
        with mock.patch.dict(os.environ, {"YOKE_DB": db_path}, clear=False):
            conn = connect_test_db(db_path)
            conn.execute(
                "INSERT INTO items (id, title) VALUES (%s, 'Test item')",
                (TEST_ITEM_ID,),
            )
            conn.commit()
            conn.close()
            yield db_path


def _add_requirement(
    db_path: str,
    *,
    item_id: int = TEST_ITEM_ID,
    qa_kind: str = "simulation",
    qa_phase: str = "verification",
    blocking_mode: str = "blocking",
    waived_at: Optional[str] = None,
) -> int:
    conn = connect_test_db(db_path)
    cur = conn.execute(
        "INSERT INTO qa_requirements "
        "(item_id, qa_kind, qa_phase, blocking_mode, waived_at, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            item_id,
            qa_kind,
            qa_phase,
            blocking_mode,
            waived_at,
            "2026-04-25T00:00:00Z",
        ),
    )
    req_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return int(req_id)


def _add_run(db_path: str, req_id: int, *, verdict: str) -> int:
    conn = connect_test_db(db_path)
    cur = conn.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, executor_type, qa_kind, verdict, created_at) "
        "VALUES (%s, 'agent', 'simulation', %s, %s) RETURNING id",
        (req_id, verdict, "2026-04-25T00:00:00Z"),
    )
    run_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return int(run_id)


class TestCheckPlanSimulationSatisfied:
    def test_passes_when_no_requirements_exist(self, qa_db: str) -> None:
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert result.passed

    def test_passes_when_blocking_req_has_passing_run(self, qa_db: str) -> None:
        req_id = _add_requirement(qa_db)
        _add_run(qa_db, req_id, verdict="pass")
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert result.passed

    def test_fails_when_blocking_req_has_only_failing_run(self, qa_db: str) -> None:
        req_id = _add_requirement(qa_db)
        _add_run(qa_db, req_id, verdict="fail")
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert "Cannot advance to 'planned'" in joined
        assert "no passing run" in joined
        assert f"#{req_id}" in joined
        assert "simulation" in joined

    def test_fails_when_blocking_req_has_no_runs(self, qa_db: str) -> None:
        req_id = _add_requirement(qa_db)
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert not result.passed
        assert any(f"#{req_id}" in e for e in result.errors)

    def test_passes_when_failing_run_followed_by_passing_run(self, qa_db: str) -> None:
        req_id = _add_requirement(qa_db)
        _add_run(qa_db, req_id, verdict="fail")
        _add_run(qa_db, req_id, verdict="pass")
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert result.passed

    def test_passes_when_blocking_req_is_waived(self, qa_db: str) -> None:
        _add_requirement(qa_db, waived_at="2026-04-25T00:00:00Z")
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert result.passed

    def test_passes_when_only_non_blocking_req_lacks_pass_run(self, qa_db: str) -> None:
        _add_requirement(qa_db, blocking_mode="non_blocking")
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert result.passed

    def test_passes_when_only_other_phase_lacks_pass_run(self, qa_db: str) -> None:
        _add_requirement(qa_db, qa_phase="post_deploy")
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert result.passed

    def test_lists_every_unsatisfied_requirement(self, qa_db: str) -> None:
        req1 = _add_requirement(qa_db, qa_kind="simulation")
        req2 = _add_requirement(qa_db, qa_kind="ac_verification")
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert not result.passed
        joined = "\n".join(result.errors)
        assert f"#{req1}" in joined
        assert f"#{req2}" in joined

    def test_bypass_flag(self, qa_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
        _add_requirement(qa_db)
        monkeypatch.setenv("YOKE_QA_GATE_BYPASS", "1")
        result = check_plan_simulation_satisfied(TEST_ITEM_ID, qa_db)
        assert result.passed

    def test_missing_qa_tables_fails_closed(self, tmp_path: Path) -> None:
        with init_test_db(
            tmp_path, apply_schema=_apply_items_only_schema
        ) as db_path:
            with mock.patch.dict(
                os.environ, {"YOKE_DB": db_path}, clear=False
            ):
                result = check_plan_simulation_satisfied(TEST_ITEM_ID, db_path)
        assert not result.passed
        assert any("QA tables are unavailable" in e for e in result.errors)
