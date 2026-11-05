# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain.sessions_analytics_core import (
    DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES,
)

from runtime.api.sessions_test_support import _apply_session_schema, _register, conn

from runtime.api.fixtures.backlog import insert_item, seed_fixture_operating_actor

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from runtime.api.sessions_api_stale_test_helpers import (
    EVENTS_TABLE_FOR_STALE_DETECTION,
    apply_ddl_statements,
)

from yoke_core.domain.sessions import (
    SessionError,
    claim_work,
    end_session,
    get_claim_for_work_unit,
    list_claims_for_session,
    release_all_claims,
    release_claim,
)

from yoke_core.domain.work_claim_targets import make_item_target


@pytest.fixture(autouse=True)
def _seed_claim_items(conn):
    for item_id in (1, 2, 99, 9999):
        insert_item(conn, id=item_id, workflow_id="issue")
