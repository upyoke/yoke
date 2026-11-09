"""Code-owned rows are projected only after the history has run.

The boot converge does two different jobs. It brings the schema up to the code
— creating tables, adding additive columns, then applying whatever the ordered
history says this database still owes — and it projects the rows the code
itself owns, such as the built-in QA methods and the methods a Pack ships.

Those two jobs are ordered, and the order is not a preference. A projection
writes the column names the current code knows, so it can only run against a
schema the history has finished transforming. Run it earlier and a universe
still carrying a retired column name meets an INSERT naming the current one,
which fails — and because boot is fail-hard, that universe stops serving
rather than converging. This is what a live tenant looks like on the boot
after the QA runner-vocabulary rename deploys.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
from yoke_core.domain.schema_init import converge_core_schema


def _method_runner(conn, method_id: str) -> str:
    row = conn.execute(
        "SELECT runner_id FROM qa_methods WHERE id = %s", (method_id,)
    ).fetchone()
    assert row is not None, f"{method_id} was not projected"
    return row["runner_id"] if isinstance(row, dict) else row[0]


@pytest.fixture()
def named_restore_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """The applier refuses a destructive entry no restore point covers."""
    monkeypatch.setenv(RESTORE_POINT_ENV, "snapshot:boot-converge-order-test")


def test_the_projected_methods_carry_their_runner(
    tmp_path: Path, named_restore_point: None
) -> None:
    """Converging is not enough: the projection has to have actually run.

    An ordering fix that merely moved the failure out of the way would leave a
    universe whose QA catalog no longer matches the code it runs.
    """
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            converge_core_schema(conn)

            assert _method_runner(conn, "command") == "worktree_run"
        finally:
            conn.close()


def test_a_method_the_universe_has_never_seen_is_projected(
    tmp_path: Path, named_restore_point: None
) -> None:
    """The insert half of the projection, not just the update half.

    Every built-in method already exists on a live tenant, so a projection that
    only ever takes its conflict branch would hide the defect: the failing
    statement is an INSERT, and only a method id the database does not already
    carry reaches it.
    """
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            conn.execute("DELETE FROM qa_plan_cases WHERE method_id = 'command'")
            conn.execute("DELETE FROM qa_requirements WHERE method_id = 'command'")
            conn.execute("DELETE FROM qa_methods WHERE id = 'command'")
            conn.commit()

            converge_core_schema(conn)

            assert _method_runner(conn, "command") == "worktree_run"
        finally:
            conn.close()


def test_a_newborn_universe_still_gets_its_projected_methods(
    tmp_path: Path, named_restore_point: None
) -> None:
    """The path every fresh install takes, which the reorder must not disturb."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            converge_core_schema(conn)

            assert _method_runner(conn, "command") == "worktree_run"
            assert os.environ.get(RESTORE_POINT_ENV)
        finally:
            conn.close()
