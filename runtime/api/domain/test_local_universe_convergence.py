"""A universe left behind its own engine, and what serving it costs.

An upgrade adds columns to the schema module; a database created by the
previous build does not have them. The board is the surface that showed it
first — its item query names the merge-queue columns directly, so a stale
universe cannot render a board at all. Both halves are proven here against a
real database: the degradation reproduces the failure, and the convergence the
serving path runs restores it.
"""

from __future__ import annotations

import psycopg
import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.board.config import parse_config
from yoke_core.board.data import collect_board_data
from yoke_core.board.db import BoardDB
from yoke_core.domain import local_universe, local_universe_convergence

# One additive column reached an existing universe only through the boot
# converge, so dropping it reproduces exactly the shape an upgraded install
# is left in.
_ADDITIVE_COLUMN = ("items", "merge_queue_landed_at")


@pytest.fixture()
def stale_universe(tmp_path):
    """A production-schema database degraded to a pre-upgrade shape."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            table, column = _ADDITIVE_COLUMN
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            conn.commit()
        finally:
            conn.close()
        yield db_path


def _column_exists(db_path, table: str, column: str) -> bool:
    conn = connect_test_db(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            (table, column),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def _collect_board(db_path, tmp_path):
    config = parse_config(str(tmp_path / "board-config"))
    with BoardDB(db_path) as db:
        return collect_board_data(db, scope="yoke", config=config)


def test_serving_converge_restores_a_column_the_upgrade_added(stale_universe):
    assert not _column_exists(stale_universe, *_ADDITIVE_COLUMN)

    local_universe_convergence.converge_serving_schema()

    assert _column_exists(stale_universe, *_ADDITIVE_COLUMN)


def test_board_collection_fails_on_a_universe_behind_its_engine(
    stale_universe, tmp_path
):
    with pytest.raises(psycopg.Error) as raised:
        _collect_board(stale_universe, tmp_path)

    assert _ADDITIVE_COLUMN[1] in str(raised.value)


def test_board_collection_succeeds_once_the_universe_is_converged(
    stale_universe, tmp_path
):
    local_universe_convergence.converge_serving_schema()

    payload = _collect_board(stale_universe, tmp_path)

    assert payload["entry_count"] > 0


def test_this_machine_owns_its_own_embedded_universe():
    assert local_universe_convergence.serves_own_universe(local_universe.local_dsn())


def test_a_cluster_this_machine_only_administers_is_not_its_own():
    foreign = "postgresql://yoke@shared.example.invalid:5432/yoke"

    assert not local_universe_convergence.serves_own_universe(foreign)


def test_an_empty_address_owns_nothing():
    assert not local_universe_convergence.serves_own_universe("")
