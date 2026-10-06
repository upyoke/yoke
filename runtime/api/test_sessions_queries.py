# ruff: noqa: F401, F811
"""Session query tests: list, get, query surface, claim ownership.
Sibling modules cover related surfaces:

- ``test_sessions_queries_reclaim.py`` — stale/ended-session reclaim, race safety.
- ``test_sessions_queries_telemetry.py`` — Codex runtime ID and post-decision telemetry.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.test_sessions import (
    _insert_claimable_items,
    _register,
    conn,
    ownership_conn,
    _ensure_active_session,
)
from yoke_core.domain.sessions import (
    claim_work,
    end_session,
    get_claim_for_work_unit,
    list_harness_sessions,
    list_claims_for_session,
    release_claim,
    set_session_mode,
)
from runtime.api.test_constants import TEST_MODEL_ID


@pytest.fixture(autouse=True)
def _claimable_query_items(conn):
    _insert_claimable_items(conn, 1, 2, 100, 9999)


# ---------------------------------------------------------------------------
# Query surface tests
# ---------------------------------------------------------------------------


class TestQuerySurface:
    def test_list_harness_sessions(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2", execution_lane="review")
        harness_sessions = list_harness_sessions(conn)
        assert len(harness_sessions) == 2

    def test_list_harness_sessions_filter_lane(self, conn):
        _register(conn, session_id="sess-1", execution_lane="primary")
        _register(conn, session_id="sess-2", execution_lane="review")
        harness_sessions = list_harness_sessions(conn, lane="review")
        assert len(harness_sessions) == 1
        assert harness_sessions[0]["session_id"] == "sess-2"

    def test_list_harness_sessions_filter_mode(self, conn):
        _register(conn, session_id="sess-1", mode="charge")
        _register(conn, session_id="sess-2", mode="wait")
        harness_sessions = list_harness_sessions(conn, mode="charge")
        assert len(harness_sessions) == 1

    def test_list_harness_sessions_excludes_ended(self, conn):
        _register(conn, session_id="sess-1")
        _register(conn, session_id="sess-2")
        end_session(conn, "sess-2")
        harness_sessions = list_harness_sessions(conn)
        assert len(harness_sessions) == 1

    def test_list_claims_for_session(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=1)
        claim_work(conn, session_id="sess-1", item_id=2)
        claims = list_claims_for_session(conn, "sess-1")
        assert len(claims) == 2
        assert {claim["scope"]["item_id"] for claim in claims} == {1, 2}
        assert all("item_id" not in claim for claim in claims)

    def test_list_claims_active_only(self, conn):
        _register(conn)
        c = claim_work(conn, session_id="sess-1", item_id=1)
        claim_work(conn, session_id="sess-1", item_id=2)
        release_claim(conn, c["id"])
        active = list_claims_for_session(conn, "sess-1", active_only=True)
        all_claims = list_claims_for_session(conn, "sess-1", active_only=False)
        assert len(active) == 1
        assert len(all_claims) == 2

    def test_get_claim_for_item(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=9999)
        result = get_claim_for_work_unit(conn, item_id=9999)
        assert result is not None
        assert result["session_id"] == "sess-1"
        assert result["scope"] == {"item_id": 9999}
        assert "item_id" not in result

    def test_get_claim_for_epic_parent_item(self, conn):
        """epic task ownership uses parent item claim."""
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id=100)
        result = get_claim_for_work_unit(conn, item_id=100)
        assert result is not None
        assert result["session_id"] == "sess-1"

    def test_get_claim_for_unclaimed_item(self, conn):
        result = get_claim_for_work_unit(conn, item_id=99)
        assert result is None

    def test_get_claim_returns_none_for_no_spec(self, conn):
        result = get_claim_for_work_unit(conn)
        assert result is None

    def test_set_session_mode_updates_session(self, conn):
        _register(conn)
        result = set_session_mode(conn, "sess-1", "charge")
        assert result["mode"] == "charge"

        row = conn.execute(
            "SELECT mode FROM harness_sessions WHERE session_id='sess-1'"
        ).fetchone()
        assert row["mode"] == "charge"


# ---------------------------------------------------------------------------
# Basic ownership-helper tests (basics + contract). Lane/reclaim/telemetry
# tests live in sibling files (see header docstring).
# ---------------------------------------------------------------------------
