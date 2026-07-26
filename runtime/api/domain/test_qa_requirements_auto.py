"""Tests for automatic AC verification requirements."""

from __future__ import annotations

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain.qa_requirements_auto import PYTEST_TARGET, auto_create_for_item
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


@pytest.fixture()
def qa_db(tmp_path):
    # Backend-aware: SQLite seeds a real file; Postgres provisions a disposable
    # per-test database (DSN repointed for the context) so the code-under-test,
    # which connects through the backend factory, reads the same DB the fixture
    # and the _insert_item / _requirements helpers write. apply_fixture_schema_ddl
    # applies the conftest SCHEMA_DDL on both engines.
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        yield db_path


def _insert_item(db_path: str, *, item_id: int = 1, spec: str = "", **kwargs) -> None:
    conn = connect_test_db(db_path)
    try:
        insert_item(conn, id=item_id, spec=spec, **kwargs)
    finally:
        conn.close()


def _requirements(db_path: str) -> list:
    conn = connect_test_db(db_path)
    try:
        return list(conn.execute("SELECT * FROM qa_requirements ORDER BY id"))
    finally:
        conn.close()


def test_missing_browser_metadata_on_issue_creates_ac_verification(qa_db) -> None:
    spec = "## Acceptance Criteria\n- [ ] AC-1: Verify the unit-tested path\n"
    _insert_item(qa_db, spec=spec)

    req_id = auto_create_for_item(1, db_path=qa_db)

    rows = _requirements(qa_db)
    assert req_id == rows[0]["id"]
    assert rows[0]["qa_kind"] == "ac_verification"
    assert rows[0]["qa_phase"] == "verification"
    assert rows[0]["blocking_mode"] == "blocking"
    assert rows[0]["requirement_source"] == "ac_derived"
    assert PYTEST_TARGET in rows[0]["success_policy"]
    assert "AC-1: Verify the unit-tested path" in rows[0]["success_policy"]


def test_existing_ac_verification_requirement_is_idempotent(qa_db) -> None:
    _insert_item(qa_db, spec="## Acceptance Criteria\n- [ ] AC-1: Once\n")

    first = auto_create_for_item(1, db_path=qa_db)
    second = auto_create_for_item(1, db_path=qa_db)

    assert second == first
    assert len(_requirements(qa_db)) == 1
