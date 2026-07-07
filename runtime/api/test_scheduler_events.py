"""Tests for scheduler telemetry emission.

Covers ``emit_scheduler_offer_skipped`` for the path-claim-blocked
skip-reason and the canonical taxonomy exported by
:mod:`yoke_core.domain.scheduler_skip_reasons`.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.events_schema import _create_events_table
from yoke_core.domain.scheduler_events import emit_scheduler_offer_skipped
from yoke_core.domain.scheduler_skip_reasons import (
    SKIP_REASON_PATH_CLAIM_BLOCKED,
    SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM,
    SKIP_REASONS,
    is_valid_skip_reason,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_events_schema() -> None:
    """``apply_schema`` strategy building just the ``events`` table.

    Backend-aware: ``db_backend.connect()`` resolves to the repointed
    per-test Postgres DSN, so the events table lands wherever ``emit_event``
    will write it (``write_event_row`` routes ambient ``db_path=None`` emits
    to the same backend factory).
    """
    conn = db_backend.connect()
    try:
        _create_events_table(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def events_db(tmp_path, monkeypatch):
    """Provide an events-table-bearing test DB on either backend.

    On SQLite a non-canonical ``YOKE_DB`` file (one of the explicit
    isolation-gate escape hatches) so ``emit_event`` writes there without an
    explicit ``conn`` kwarg. On Postgres a disposable per-test database; the
    ambient ``write_event_row`` path routes the emit through the backend
    factory at the repointed DSN, so the row lands in the same DB the reader
    opens.
    """
    with init_test_db(tmp_path, apply_schema=_apply_events_schema) as db_path:
        # SQLite emit resolution reads YOKE_DB (init_test_db only patches it
        # for the duration of the apply call); keep it set for the test body.
        # On Postgres the ambient emit ignores the path (routes to the DSN),
        # so setting it is harmless.
        monkeypatch.setenv("YOKE_DB", str(db_path))
        yield db_path


def _events(db_path) -> list:
    conn = connect_test_db(db_path)
    try:
        return list(
            conn.execute(
                "SELECT event_name, envelope, session_id, item_id "
                "FROM events WHERE event_name = 'SchedulerOfferSkipped' "
                "ORDER BY id"
            )
        )
    finally:
        conn.close()


class TestSkipReasonTaxonomy:
    def test_path_claim_blocked_is_in_taxonomy(self):
        assert SKIP_REASON_PATH_CLAIM_BLOCKED == "path_claim_blocked"
        assert SKIP_REASON_PATH_CLAIM_BLOCKED in SKIP_REASONS

    def test_existing_reasons_remain_in_taxonomy(self):
        expected = {
            "stale_lifecycle",
            SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM,
            "live_claim_conflict",
            "recoverable_substrate",
            "process_disabled_by_config",
            "path_claim_blocked",
        }
        assert set(SKIP_REASONS) == expected

    def test_stale_lifecycle_post_claim_is_in_taxonomy(self):
        assert SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM in SKIP_REASONS

    def test_validation_helper(self):
        assert is_valid_skip_reason("path_claim_blocked") is True
        assert is_valid_skip_reason("stale_lifecycle") is True
        assert is_valid_skip_reason(SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM) is True
        assert is_valid_skip_reason("not_a_real_reason") is False


class TestEmitSchedulerOfferSkipped:
    def test_path_claim_blocked_produces_event(self, events_db):
        emit_scheduler_offer_skipped(
            session_id="test-session",
            skip_reason=SKIP_REASON_PATH_CLAIM_BLOCKED,
            chain_step=2,
            project="yoke",
            item_id="9999",
            claim_id=42,
        )
        rows = _events(events_db)
        assert len(rows) == 1
        assert rows[0]["event_name"] == "SchedulerOfferSkipped"
        envelope = json.loads(rows[0]["envelope"])
        ctx = envelope["context"]
        assert ctx["skip_reason"] == "path_claim_blocked"
        assert ctx["chain_step"] == 2
        assert ctx["claim_id"] == 42
        assert ctx["item_id"] == "9999"
        assert rows[0]["session_id"] == "test-session"

    def test_existing_skip_reason_still_emits(self, events_db):
        emit_scheduler_offer_skipped(
            session_id="test-session",
            skip_reason="stale_lifecycle",
            chain_step=1,
        )
        rows = _events(events_db)
        assert len(rows) == 1
        envelope = json.loads(rows[0]["envelope"])
        assert envelope["context"]["skip_reason"] == "stale_lifecycle"

    def test_stale_lifecycle_post_claim_produces_event(self, events_db):
        emit_scheduler_offer_skipped(
            session_id="test-session",
            skip_reason=SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM,
            chain_step=2,
            project="yoke",
            item_id="1234",
            current_status="reviewed-implementation",
            claim_id=99,
            extra={"expected_status": "reviewing-implementation"},
        )
        rows = _events(events_db)
        assert len(rows) == 1
        envelope = json.loads(rows[0]["envelope"])
        ctx = envelope["context"]
        assert ctx["skip_reason"] == SKIP_REASON_STALE_LIFECYCLE_POST_CLAIM
        assert ctx["chain_step"] == 2
        assert ctx["claim_id"] == 99
        assert ctx["current_status"] == "reviewed-implementation"
        assert ctx["expected_status"] == "reviewing-implementation"

    def test_invalid_skip_reason_is_rejected(self, events_db):
        with pytest.raises(ValueError, match="invalid SchedulerOfferSkipped"):
            emit_scheduler_offer_skipped(
                session_id="test-session",
                skip_reason="not_a_real_reason",
                chain_step=1,
            )
        assert _events(events_db) == []
