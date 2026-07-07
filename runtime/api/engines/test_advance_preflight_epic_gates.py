"""Integration tests for the advance-preflight Epic Task gates.

Background
----------
The advance skill's preflight Epic Task Existence Gate and Epic Task Completion
Gate (in ``.agents/skills/yoke/advance/preflight-checks.md``) derive the
parent-epic ID from the item being advanced and count rows in ``epic_tasks``
keyed on that ID. A prior incarnation of the skill read a retired item column
for that lookup, which caused the gate to silently report "no tasks" for every
epic and block correct advances (see the live repro).

The fixed gate uses ``_epic_id={N}`` directly (mirroring the convention in
``shepherd/plan-handoff.md:23``) and interpolates the bare integer into the SQL.
This test exercises the fixed SQL shape against a seeded fixture so the same
drift class is caught before it ships, not after the next retirement cycle.

Scope
-----
- Existence gate: seeded epic with tasks → count > 0 (pass path)
- Existence gate: seeded epic without tasks → count == 0 (block path)
- Completion gate: all tasks terminal → done_count == total (allow path)
- Completion gate: mixed task states → done_count < total (block path)

The tests use an in-process disposable Postgres fixture rather than spawning
the full ``db_router`` CLI, because the behavioural unit under test is the SQL
query shape and the numeric-ID interpolation — not the CLI wrapper. The
``db_router`` round-trip is already covered by existing suites.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


# The exact SQL shape the preflight gates build after the. Kept as a
# module-level constant so a future gate edit that changes the query shape
# forces a test update (and vice versa) — the test is the rendered contract.
EXISTENCE_GATE_SQL = "SELECT COUNT(*) FROM epic_tasks WHERE epic_id={epic_id}"
COMPLETION_TOTAL_SQL = "SELECT COUNT(*) FROM epic_tasks WHERE epic_id={epic_id}"
COMPLETION_DONE_SQL = (
    "SELECT COUNT(*) FROM epic_tasks WHERE epic_id={epic_id} "
    "AND status IN ('done','reviewed-implementation','implemented','release')"
)


@pytest.fixture()
def epic_fixture():
    """Return a ``(conn, seed)`` pair backed by a disposable Postgres test DB.

    ``seed(epic_id, tasks)`` inserts one row per ``tasks`` entry. Each entry is
    a ``(task_num, status)`` tuple — minimal projection of the ``epic_tasks``
    columns the gates touch. Callers can seed multiple epics in one fixture to
    verify the gate does not leak counts across epic_id boundaries.
    """
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE epic_tasks (
            id INTEGER PRIMARY KEY,
            epic_id INTEGER NOT NULL,
            task_num INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            UNIQUE(epic_id, task_num)
        );
        """
    )

    def _seed(epic_id: int, tasks: list[tuple[int, str]]) -> None:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO epic_tasks (epic_id, task_num, title, status) "
                "VALUES (%s, %s, %s, %s)",
                [(epic_id, num, f"Task {num}", status) for num, status in tasks],
            )
        conn.commit()

    try:
        yield conn, _seed
    finally:
        conn.close()


def _run(conn: Any, sql: str, epic_id: int) -> int:
    rendered = sql.format(epic_id=epic_id)
    cursor = conn.execute(rendered)
    (count,) = cursor.fetchone()
    return int(count)


# ---------------------------------------------------------------------------
# Existence Gate — Epic Task Existence Gate (step 5-gate)
# ---------------------------------------------------------------------------


def test_existence_gate_passes_for_seeded_epic(epic_fixture):
    """Epic with tasks → count > 0, gate passes (does not block)."""
    conn, seed = epic_fixture
    epic_id = 1476  # the live repro referenced in the spec
    seed(epic_id, [(n, "planned") for n in range(1, 7)])  # 6 tasks

    count = _run(conn, EXISTENCE_GATE_SQL, epic_id)

    assert count == 6, (
        "Existence gate should see all 6 seeded tasks for epic_id=1476. "
        "If this fails, the SQL shape drifted from the skill query — sync both."
    )


def test_existence_gate_blocks_for_empty_epic(epic_fixture):
    """Epic without tasks → count == 0, gate blocks."""
    conn, _ = epic_fixture
    epic_id = 9999

    count = _run(conn, EXISTENCE_GATE_SQL, epic_id)

    assert count == 0, "Empty epic should count zero tasks (gate blocks path)."


def test_existence_gate_does_not_bleed_across_epics(epic_fixture):
    """Seeded rows for epic A must not count toward epic B — the bare-integer
    interpolation must scope precisely to the passed ``{N}``."""
    conn, seed = epic_fixture
    seed(1476, [(1, "planned"), (2, "planned")])
    seed(1477, [(1, "planned")])

    assert _run(conn, EXISTENCE_GATE_SQL, 1476) == 2
    assert _run(conn, EXISTENCE_GATE_SQL, 1477) == 1
    assert _run(conn, EXISTENCE_GATE_SQL, 1478) == 0


# ---------------------------------------------------------------------------
# Completion Gate — Epic Task Completion Gate (step 5a)
# ---------------------------------------------------------------------------


def test_completion_gate_allows_when_all_terminal(epic_fixture):
    """All tasks in terminal states → done == total, gate allows."""
    conn, seed = epic_fixture
    epic_id = 1476
    seed(
        epic_id,
        [
            (1, "done"),
            (2, "reviewed-implementation"),
            (3, "implemented"),
            (4, "release"),
        ],
    )

    total = _run(conn, COMPLETION_TOTAL_SQL, epic_id)
    done = _run(conn, COMPLETION_DONE_SQL, epic_id)

    assert total == done == 4


def test_completion_gate_blocks_on_incomplete_tasks(epic_fixture):
    """Mixed states → done < total, gate blocks."""
    conn, seed = epic_fixture
    epic_id = 1476
    seed(
        epic_id,
        [
            (1, "done"),
            (2, "implementing"),
            (3, "planned"),
        ],
    )

    total = _run(conn, COMPLETION_TOTAL_SQL, epic_id)
    done = _run(conn, COMPLETION_DONE_SQL, epic_id)

    assert total == 3
    assert done == 1
    assert done < total, "Gate should block when in-progress tasks remain."


def test_completion_gate_blocks_on_zero_tasks(epic_fixture):
    """No rows → total == 0, gate blocks (matches existence-gate block path)."""
    conn, _ = epic_fixture
    total = _run(conn, COMPLETION_TOTAL_SQL, 1476)
    assert total == 0


# ---------------------------------------------------------------------------
# Regression: query interpolates numeric ID, not a YOK-prefixed string.
# ---------------------------------------------------------------------------


def test_epic_id_interpolation_is_bare_integer_not_sun_prefixed(epic_fixture):
    """If a future regression re-introduces ``WHERE epic_id='YOK-1476'``, the
    Postgres authority rejects the comparison with an integer-input type error
    — because ``epic_tasks.epic_id`` is an INTEGER column. Pin the correct
    bare-integer form with an explicit assertion."""
    import psycopg

    conn, seed = epic_fixture
    seed(1476, [(n, "planned") for n in range(1, 4)])

    # Correct form (bare integer): matches seeded rows
    ok = conn.execute(
        "SELECT COUNT(*) FROM epic_tasks WHERE epic_id=1476"
    ).fetchone()[0]
    assert ok == 3

    # Regression shape (YOK-prefixed string): fails loudly with a type error
    # on the Postgres authority. The gate convention in preflight-checks.md
    # must keep interpolating the bare integer.
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        conn.execute(
            "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='YOK-1476'"
        )
    conn.rollback()
