"""Pytest fixture for planning-phase path-claim guard tests."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.path_claim_bash_guard_planning_phase_test_helpers import (
    _apply_widener_schema,
    _configure_scratch,
)


@pytest.fixture
def widener_db(tmp_path, monkeypatch):
    with init_test_db(tmp_path, apply_schema=_apply_widener_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            _configure_scratch(monkeypatch)
            monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
            yield conn
        finally:
            conn.close()
