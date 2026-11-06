# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from unittest.mock import patch

from runtime.api.domain.browser_qa_test_helpers import (
    _browser_check_steps,
    _placeholder,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_core.domain.browser_qa_freshness_outcome import (
    EXECUTION_TARGET_UNAUTHORIZED,
)

from yoke_core.domain.browser_qa_sign_in_evidence import (
    AUTHENTICATION_WALL_LABEL,
    PROFILE_AUTHORIZED,
    PROFILE_THROWAWAY,
    describe_sign_in,
)


def _raw_result(db_path: str, req_id: int) -> dict:
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT raw_result FROM qa_runs WHERE qa_requirement_id = {p}",
        (req_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    return json.loads(row[0])
