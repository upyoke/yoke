"""``qa.cmd_init`` — table creation and idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import qa
from yoke_core.domain.schema_common import _table_exists
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_test_helpers import make_qa_db_file

@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


class TestInit:
    def test_creates_tables(self, db_path: str) -> None:
        conn = connect_test_db(db_path)
        try:
            assert _table_exists(conn, "qa_requirements")
            assert _table_exists(conn, "qa_runs")
            assert _table_exists(conn, "qa_artifacts")
        finally:
            conn.close()

    def test_idempotent(self, db_path: str) -> None:
        """Running init twice should not raise."""
        qa.cmd_init(db_path=db_path)
