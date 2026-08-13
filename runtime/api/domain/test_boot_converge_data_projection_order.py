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
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_content_transition_guard import (
    adoption_transition_guard_function_name,
    ensure_adoption_transition_guard,
)
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_ADOPTION_EVIDENCE_CONTRACT,
    YOKE_LEDGER_CONTRACT,
)
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.schema_init import converge_core_schema

ENTRY_NAME = "0008_qa_runner_identity_columns"


def _entry():
    """Load the entry the way the applier does: by path, not by import name."""
    directory = history_dir(migration_history_package)
    match = next(
        record for record in ordered_entries(directory) if record.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{match.name}.py", match.name)


def _unstamp(conn, entry_name: str) -> None:
    """Make one entry pending again on a database that recorded it at birth.

    Ledger membership is immutable in the running product — a database may
    never forget an entry it applied — so the only way to model a universe that
    predates an entry is to lift that guard, remove the row, and put the guard
    back exactly as it was. Dropping the guard's function takes its triggers
    with it, so the public name is all this needs to know.
    """
    function = adoption_transition_guard_function_name(
        YOKE_LEDGER_CONTRACT, YOKE_ADOPTION_EVIDENCE_CONTRACT
    )
    conn.execute(f"DROP FUNCTION IF EXISTS {function}() CASCADE")
    conn.execute(
        f"DELETE FROM {YOKE_LEDGER_CONTRACT.table} "
        f"WHERE {YOKE_LEDGER_CONTRACT.entry_column} = %s",
        (entry_name,),
    )
    ensure_adoption_transition_guard(
        conn, YOKE_LEDGER_CONTRACT, YOKE_ADOPTION_EVIDENCE_CONTRACT
    )
    conn.commit()


def _regress_to_retired_qa_vocabulary(conn) -> None:
    """Undo the entry, leaving the shape every live tenant boots with.

    The retired names are read from the entry rather than written here, so this
    fixture keeps describing the same database the entry describes.
    """
    for table, retired, current in _entry().RENAMED_COLUMNS:
        conn.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{current}" TO "{retired}"')
    _unstamp(conn, ENTRY_NAME)


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


def test_a_universe_on_the_retired_qa_vocabulary_converges(
    tmp_path: Path, named_restore_point: None
) -> None:
    """The tenant boot that the fleet preflight caught failing."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _regress_to_retired_qa_vocabulary(conn)
            assert _column_exists(conn, "qa_methods", "runner_id") is False

            converge_core_schema(conn)

            entry = _entry()
            entry.invariants(conn)
            for table, retired, current in entry.RENAMED_COLUMNS:
                assert _column_exists(conn, table, retired) is False
                assert _column_exists(conn, table, current) is True
        finally:
            conn.close()


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
            _regress_to_retired_qa_vocabulary(conn)

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
            _regress_to_retired_qa_vocabulary(conn)
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
