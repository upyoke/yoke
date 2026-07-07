"""Fresh-env schema chain creates the strategy authority table.

The ``strategy_docs`` table originally landed on prod via a since-retired
governed migration; the canonical init chain must create it for fresh
envs (stage/ephemeral/self-host bootstrap) so the strategy surfaces are
live rather than skipping on a missing table.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.schema_common import _get_columns, _table_exists
from yoke_core.domain.strategy_docs import STRATEGY_DOCS_TABLE
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def test_fresh_init_creates_strategy_docs(tmp_path: Path) -> None:
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            assert _table_exists(conn, STRATEGY_DOCS_TABLE)
            cols = set(_get_columns(conn, STRATEGY_DOCS_TABLE))
            assert {
                "id", "slug", "content", "updated_at", "updated_by_actor_id",
            } <= cols
        finally:
            conn.close()


def test_init_replay_is_idempotent_for_strategy_docs(tmp_path: Path) -> None:
    from yoke_core.domain import schema_init

    with init_test_db(tmp_path) as db_path:
        schema_init.cmd_init()  # replay on an already-initialized DB
        conn = connect_test_db(db_path)
        try:
            assert _table_exists(conn, STRATEGY_DOCS_TABLE)
        finally:
            conn.close()
