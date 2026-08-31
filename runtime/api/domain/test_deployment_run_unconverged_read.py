"""Release-driver run reads survive a live table missing additive columns."""

from __future__ import annotations

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.deployment_run_projection import _locked_existing
from yoke_core.domain.deployment_runs_schema import (
    RUN_FIELDS,
    _run_named_columns,
    _run_select,
)
from runtime.api.fixtures.file_test_db import connect_test_db

pytest_plugins = ["runtime.api.deployment_runs_test_db"]


def _drop_carried_work(db_path: str) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute("ALTER TABLE deployment_runs DROP COLUMN carried_work")
        conn.commit()
    finally:
        conn.close()


def test_runs_get_succeeds_when_carried_work_column_is_absent(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    _drop_carried_work(db_path)

    result = dr.cmd_get(run_id, db_path=db_path)

    assert result is not None
    parts = result.split("|")
    assert len(parts) == len(RUN_FIELDS)
    assert parts[0] == run_id
    assert parts[RUN_FIELDS.index("carried_work")] == ""


def test_runs_get_field_returns_empty_when_carried_work_is_absent(
    db_path: str,
) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    _drop_carried_work(db_path)

    assert dr.cmd_get(run_id, field="carried_work", db_path=db_path) == ""


def test_runs_list_succeeds_when_carried_work_column_is_absent(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    _drop_carried_work(db_path)

    listed = dr.cmd_list(db_path=db_path)
    row = listed.split("\n")[0]
    parts = row.split("|")
    assert parts[0] == run_id
    assert parts[RUN_FIELDS.index("carried_work")] == ""


def test_named_and_pipe_selects_project_empty_carried_work(db_path: str) -> None:
    dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    _drop_carried_work(db_path)
    conn = connect_test_db(db_path)
    try:
        pipe_sql = _run_select(conn)
        named_sql, _join = _run_named_columns(conn)
    finally:
        conn.close()

    assert "'' AS carried_work" in pipe_sql
    assert "COALESCE(carried_work" not in pipe_sql
    assert "NULL AS carried_work" in named_sql
    assert "dr.carried_work" not in named_sql


def test_locked_existing_read_survives_missing_carried_work(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    _drop_carried_work(db_path)
    conn = connect_test_db(db_path)
    try:
        snapshot = _locked_existing(conn, run_id)
    finally:
        conn.close()

    assert snapshot is not None
    assert snapshot["id"] == run_id
    assert snapshot["carried_work"] is None
