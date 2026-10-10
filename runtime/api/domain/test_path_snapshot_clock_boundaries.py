"""Path resolution keeps Native clocks until PostgreSQL or SQLite writes."""

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant
from yoke_core.domain.path_registry import (
    KIND_DIRECTORY,
    KIND_FILE,
    ROOT_PATH_SENTINEL,
    _resolve_path_target_id,
)
from yoke_core.domain.path_snapshot_targets import resolve_snapshot_target_ids


@pytest.fixture(params=["postgres", "sqlite"])
def clock_connection(request, test_db):
    if request.param == "postgres":
        conn = test_db
        prefix, identity, clock_type = (
            "CREATE TEMP TABLE",
            "SERIAL PRIMARY KEY",
            "TIMESTAMPTZ",
        )
    else:
        conn = sqlite3.connect(":memory:")
        prefix, identity, clock_type = "CREATE TABLE", "INTEGER PRIMARY KEY", "TEXT"
    conn.execute(f"""{prefix} projects (
        id INTEGER PRIMARY KEY, slug TEXT, name TEXT, public_item_prefix TEXT
    )""")
    conn.execute(
        "INSERT INTO projects VALUES (1, 'clock-project', 'Clock project', 'CLK')"
    )
    conn.execute(f"""{prefix} path_targets (
        id {identity}, project_id INTEGER, kind TEXT, path_string TEXT,
        generation INTEGER, parent_target_id INTEGER,
        materialization_state TEXT DEFAULT 'observed', created_at {clock_type}
    )""")
    conn.execute(f"""{prefix} path_snapshots (
        id INTEGER PRIMARY KEY, project_id INTEGER, commit_sha TEXT,
        built_at {clock_type}
    )""")
    conn.execute(f"""{prefix} path_snapshot_entries (
        snapshot_id INTEGER, target_id INTEGER
    )""")
    yield conn, request.param
    if request.param == "sqlite":
        conn.close()


@pytest.fixture(params=["single", "bulk"])
def target_writer(request):
    def write(conn, observed_at):
        if request.param == "single":
            return _resolve_path_target_id(
                conn, 1, "clock.py", KIND_FILE, None, observed_at
            )
        return resolve_snapshot_target_ids(
            conn,
            project_id=1,
            targets=[(ROOT_PATH_SENTINEL, KIND_DIRECTORY), ("clock.py", KIND_FILE)],
            observed_at=observed_at,
        ).target_ids["clock.py"]

    return write


@pytest.mark.parametrize("offset", [0, 330, -240])
@pytest.mark.parametrize("microsecond", [0, 123456])
def test_target_clock_keeps_native_type_or_fixed_six_sqlite_bytes(
    clock_connection,
    target_writer,
    offset,
    microsecond,
):
    conn, backend = clock_connection
    instant = datetime(1969, 12, 31, 23, 59, 59, microsecond, tzinfo=timezone.utc)
    supplied = instant.astimezone(timezone(timedelta(minutes=offset)))
    target_id = target_writer(conn, supplied)
    stored = conn.execute(
        "SELECT created_at FROM path_targets WHERE path_string='clock.py'"
    ).fetchone()[0]
    if backend == "postgres":
        assert isinstance(stored, datetime)
        assert stored == instant
    else:
        assert stored == format_instant(instant)
    assert target_writer(conn, supplied) == target_id


@pytest.mark.parametrize("reuse", [False, True])
@pytest.mark.parametrize("bad", [datetime(2026, 1, 1), "2026-01-01T00:00:00Z"])
def test_target_resolution_refuses_non_native_clock_even_when_reusing(
    clock_connection,
    target_writer,
    reuse,
    bad,
):
    conn, _ = clock_connection
    if reuse:
        target_writer(
            conn, datetime(1969, 12, 31, 23, 59, 59, 123456, tzinfo=timezone.utc)
        )
    before = [
        tuple(row)
        for row in conn.execute("SELECT * FROM path_targets ORDER BY id").fetchall()
    ]
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        target_writer(conn, bad)
    after = [
        tuple(row)
        for row in conn.execute("SELECT * FROM path_targets ORDER BY id").fetchall()
    ]
    assert after == before
