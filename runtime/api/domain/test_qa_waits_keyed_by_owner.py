"""Migration 0122 retires the session index without changing waits."""

from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module

OLD = "idx_qa_test_machine_waits_live_session"
NEW = "idx_qa_test_machine_waits_live_owner"


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_session_index_removal_replays_without_changing_waits(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TEMP TABLE qa_test_machine_waits "
        "(test_machine TEXT, session_id TEXT, qa_plan_execution_id TEXT, state TEXT)"
    )
    conn.execute(
        "INSERT INTO qa_test_machine_waits VALUES ('lab','session','execution','waiting')"
    )
    conn.execute(f"CREATE UNIQUE INDEX {OLD} ON qa_test_machine_waits(test_machine, session_id)")
    if backend == "sqlite":
        conn.execute(
            f"CREATE UNIQUE INDEX {NEW} ON qa_test_machine_waits "
            "(test_machine, COALESCE(qa_plan_execution_id, session_id))"
        )
        indexes_sql = "SELECT name FROM sqlite_temp_master WHERE type='index'"
    else:
        indexes_sql = "SELECT indexname FROM pg_indexes WHERE tablename='qa_test_machine_waits'"
    path = Path(migrations.__file__).parent / "0122_qa_waits_keyed_by_owner.py"
    migration = load_migration_module(path, path.stem)

    for _ in range(2):
        migration.apply(conn)
        indexes = {row[0] for row in conn.execute(indexes_sql).fetchall()}
        assert OLD not in indexes
        assert NEW in indexes
        [row] = conn.execute("SELECT * FROM qa_test_machine_waits").fetchall()
        assert tuple(row) == ("lab", "session", "execution", "waiting")
