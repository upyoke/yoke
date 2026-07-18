"""Coverage for the strategy_checkpoints state owner."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import strategy_checkpoints
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path: Path):
    with init_test_db(tmp_path) as path:
        yield path


class TestRecordCheckpoint:
    def test_records_by_slug_and_reads_latest(self, db_path):
        conn = connect_test_db(db_path)
        try:
            assert strategy_checkpoints.record_checkpoint(
                conn, project="yoke", kind="strategize",
            )
            conn.commit()
            latest = strategy_checkpoints.latest_checkpoint_at(conn, "yoke")
            assert latest is not None
            row = conn.execute(
                "SELECT project_id, kind FROM strategy_checkpoints"
            ).fetchone()
            assert tuple(row) == (1, "strategize")
        finally:
            conn.close()

    def test_records_by_numeric_id(self, db_path):
        conn = connect_test_db(db_path)
        try:
            assert strategy_checkpoints.record_checkpoint(
                conn, project=2, kind="drift_review",
            )
            conn.commit()
            assert strategy_checkpoints.latest_checkpoint_at(conn, 2)
            assert strategy_checkpoints.latest_checkpoint_at(conn, "externalwebapp")
            assert strategy_checkpoints.latest_checkpoint_at(conn, "yoke") is None
        finally:
            conn.close()

    def test_rejects_invalid_kind_and_unknown_project(self, db_path):
        conn = connect_test_db(db_path)
        try:
            assert not strategy_checkpoints.record_checkpoint(
                conn, project="yoke", kind="bogus",
            )
            assert not strategy_checkpoints.record_checkpoint(
                conn, project="no-such-project", kind="strategize",
            )
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM strategy_checkpoints"
            ).fetchone()[0]
            assert int(count) == 0
        finally:
            conn.close()

    def test_bulk_scope_records_one_row_per_project(self, db_path):
        conn = connect_test_db(db_path)
        try:
            landed = strategy_checkpoints.record_checkpoints(
                conn, projects=[1, 2], kind="drift_review",
            )
            conn.commit()
            assert landed == 2
            rows = conn.execute(
                "SELECT project_id FROM strategy_checkpoints ORDER BY project_id"
            ).fetchall()
            assert [int(r[0]) for r in rows] == [1, 2]
        finally:
            conn.close()
