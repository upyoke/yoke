"""Boot convergence alone creates every table this build declares it reads.

A tenant database is born by ``converge_core_schema`` on its first boot. A
table whose DDL lives outside that path (as the shepherd tables once did) is
missing on such a database until someone runs its private init by hand, and
the first reader fails with ``UndefinedTable``. Building an empty database
with converge only and comparing it to the declared catalog catches that.
"""

from __future__ import annotations

from typing import Dict, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_backend
from yoke_core.domain.schema_expected_catalog import parse_expected_schema
from yoke_core.domain.schema_init import converge_core_schema


@pytest.fixture(scope="module")
def converged_dsn() -> Iterator[str]:
    """An empty database brought up by ``converge_core_schema`` and nothing else."""
    name = pg_testdb.create_test_database(pooled=False)
    try:
        conn = pg_testdb.connect_test_database(name)
        try:
            converge_core_schema(conn)
        finally:
            conn.close()
        yield pg_testdb.dsn_for_test_database(name)
    finally:
        pg_testdb.drop_test_database(name, pooled=False)


def _live_columns(dsn: str) -> Dict[str, set]:
    conn = db_backend._open_native_postgres(dsn)
    try:
        rows = conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        ).fetchall()
    finally:
        conn.close()
    live: Dict[str, set] = {}
    for table, column in rows:
        live.setdefault(str(table), set()).add(str(column))
    return live


def test_converge_alone_creates_every_catalog_table_and_column(
    converged_dsn: str,
) -> None:
    live = _live_columns(converged_dsn)
    expected = parse_expected_schema()
    missing_tables = sorted(set(expected) - set(live))
    assert missing_tables == [], (
        "converge_core_schema did not create these catalog tables; move their "
        f"DDL into schema_creation: {missing_tables}"
    )
    missing_columns = sorted(
        f"{table}.{column}"
        for table, columns in expected.items()
        for column in columns
        if column not in live[table]
    )
    assert missing_columns == [], (
        f"converge_core_schema did not create these catalog columns: {missing_columns}"
    )


def test_dependency_readers_work_on_a_converge_only_database(
    converged_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The readers that failed in the fleet preflight run against converge alone."""
    from yoke_core.domain.frontier_list_read import list_frontier

    monkeypatch.setenv(db_backend.PG_DSN_ENV, converged_dsn)
    assert isinstance(list_frontier(), dict)

    conn = db_backend._open_native_postgres(converged_dsn)
    try:
        rows = conn.execute(
            "SELECT dependent_item_id, blocking_item_id, gate_point, satisfaction, "
            "rationale, evidence_json FROM item_dependencies"
        ).fetchall()
        verdicts = conn.execute("SELECT COUNT(*) FROM shepherd_verdicts").fetchone()
        caveats = conn.execute("SELECT COUNT(*) FROM caveat_dispositions").fetchone()
    finally:
        conn.close()
    assert list(rows) == []
    assert verdicts[0] == 0 and caveats[0] == 0
