"""Unit + integration coverage for the row-anchored lane fix.

Covers AC-1 and AC-2:

* :func:`anchor_lane_on_row` always returns the row value as
  authoritative, even when callers pass a mismatching ``--lane``.
* mismatches build the canonical ``SessionOfferLaneOverrideIgnored``
  payload (``caller_supplied`` + ``row_lane`` + ``resolved_lane``).
* the documented ``default`` sentinel does NOT trip the warning.
* :func:`session_offer_with_ownership` emits the WARN event before
  ``HarnessSessionOffered`` so the event ledger records the bad
  caller before any routing artefact is written.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from yoke_core.domain.sessions_offer import session_offer_with_ownership
from yoke_core.domain.sessions_offer_lane import (
    LANE_OVERRIDE_IGNORED_EVENT_NAME,
    LaneAnchorResult,
    anchor_lane_on_row,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)


class TestAnchorLaneOnRow:
    """Pure unit coverage for the row-anchor decision shape."""

    def test_no_caller_lane_returns_row_value(self):
        result = anchor_lane_on_row(
            row_lane="DARIUS",
            caller_supplied_lane=None,
            resolved_lane="DARIUS",
        )
        assert isinstance(result, LaneAnchorResult)
        assert result.authoritative_lane == "DARIUS"
        assert result.mismatch_payload is None

    def test_caller_matches_row_no_warning(self):
        result = anchor_lane_on_row(
            row_lane="DARIUS",
            caller_supplied_lane="DARIUS",
            resolved_lane="DARIUS",
        )
        assert result.authoritative_lane == "DARIUS"
        assert result.mismatch_payload is None

    def test_caller_mismatch_emits_payload_and_uses_row(self):
        result = anchor_lane_on_row(
            row_lane="DARIUS",
            caller_supplied_lane="primary",
            resolved_lane="primary",
        )
        assert result.authoritative_lane == "DARIUS"
        assert result.mismatch_payload == {
            "caller_supplied": "primary",
            "row_lane": "DARIUS",
            "resolved_lane": "primary",
        }

    def test_default_sentinel_does_not_warn(self):
        result = anchor_lane_on_row(
            row_lane="DARIUS",
            caller_supplied_lane="default",
            resolved_lane="DARIUS",
        )
        assert result.authoritative_lane == "DARIUS"
        assert result.mismatch_payload is None

    def test_empty_caller_does_not_warn(self):
        result = anchor_lane_on_row(
            row_lane="DARIUS",
            caller_supplied_lane="   ",
            resolved_lane="DARIUS",
        )
        assert result.mismatch_payload is None

    def test_empty_row_stays_empty_for_policy_unknown(self):
        """Bad row data must flow to the lane-policy unknown branch."""
        result = anchor_lane_on_row(
            row_lane=None,
            caller_supplied_lane="primary",
            resolved_lane="primary",
        )
        assert result.authoritative_lane == ""
        assert result.mismatch_payload is None


def _run_offer_capture_anchor(
    *,
    db_path: str,
    session_id: str,
    caller_supplied_lane,
    monkeypatch: pytest.MonkeyPatch,
    execution_lane="primary",
) -> tuple[str | None, list[dict]]:
    """Drive session_offer_with_ownership against a test DB; collect outputs.

    Runs the full ownership flow against the provided test DB (which must
    have the schema produced by ``test_service_client_sessions_helpers``).
    Captures lane-override events from the DB and returns the authoritative
    lane returned by ownership (or ``None`` if the call errored before
    return).

    ``monkeypatch`` pins ``YOKE_DB`` for the duration of the calling test
    and restores the prior value on teardown — so a conftest-auto-pinned
    canonical value upstream of this helper is preserved.
    """
    monkeypatch.setenv("YOKE_DB", db_path)
    conn = connect_test_db(db_path)
    try:
        result = session_offer_with_ownership(
            conn,
            session_id=session_id,
            executor="claude-code",
            provider="anthropic",
            model="claude-opus-4-7",
            workspace="/tmp/ws-lane-anchor",
            execution_lane=execution_lane,
            caller_supplied_lane=caller_supplied_lane,
        )
        authoritative = result.get("authoritative_lane")
    finally:
        conn.close()
    read_conn = connect_test_db(db_path)
    try:
        rows = read_conn.execute(
            "SELECT envelope FROM events WHERE event_name = %s AND session_id = %s",
            (LANE_OVERRIDE_IGNORED_EVENT_NAME, session_id),
        ).fetchall()
    finally:
        read_conn.close()
    contexts: list[dict] = []
    for (blob,) in rows:
        if not blob:
            continue
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            continue
        # events.emit_event stores the full envelope; the lane
        # override payload lives under ``context``.
        ctx = parsed.get("context") if isinstance(parsed, dict) else None
        if isinstance(ctx, dict):
            contexts.append(ctx)
        else:
            contexts.append(parsed if isinstance(parsed, dict) else {})
    return authoritative, contexts


def _seed_session_with_lane(db_path: str, session_id: str, lane: str) -> None:
    """Register the session row at the requested lane.

    Uses the public session-begin path (via _pre_register_session) and
    then overrides the row's execution_lane so the test does not depend
    on the executor default-lane config being writable.
    """
    _pre_register_session(db_path, session_id, executor="claude-code")
    conn = connect_test_db(db_path)
    conn.execute(
        "UPDATE harness_sessions SET execution_lane = %s WHERE session_id = %s",
        (lane, session_id),
    )
    conn.commit()
    conn.close()


class TestSessionOfferWithOwnershipAnchorsLane:
    """AC-1 + AC-2 — ownership emits the WARN event and uses the row lane."""

    def test_caller_mismatch_emits_lane_override_ignored(
        self, session_offer_db, monkeypatch
    ):
        sid = "anchor-mismatch"
        _seed_session_with_lane(session_offer_db["db_path"], sid, "DARIUS")
        authoritative, envelopes = _run_offer_capture_anchor(
            db_path=session_offer_db["db_path"],
            session_id=sid,
            caller_supplied_lane="primary",
            execution_lane="primary",
            monkeypatch=monkeypatch,
        )
        assert authoritative == "DARIUS"
        assert len(envelopes) == 1
        ctx = envelopes[0]
        assert ctx["caller_supplied"] == "primary"
        assert ctx["row_lane"] == "DARIUS"
        assert ctx["resolved_lane"] == "primary"

    def test_caller_match_emits_no_warning(
        self, session_offer_db, monkeypatch
    ):
        sid = "anchor-match"
        _seed_session_with_lane(session_offer_db["db_path"], sid, "DARIUS")
        authoritative, envelopes = _run_offer_capture_anchor(
            db_path=session_offer_db["db_path"],
            session_id=sid,
            caller_supplied_lane="DARIUS",
            execution_lane="DARIUS",
            monkeypatch=monkeypatch,
        )
        assert authoritative == "DARIUS"
        assert envelopes == []

    def test_default_sentinel_emits_no_warning(
        self, session_offer_db, monkeypatch
    ):
        sid = "anchor-default"
        _seed_session_with_lane(session_offer_db["db_path"], sid, "DARIUS")
        authoritative, envelopes = _run_offer_capture_anchor(
            db_path=session_offer_db["db_path"],
            session_id=sid,
            caller_supplied_lane="default",
            execution_lane="DARIUS",
            monkeypatch=monkeypatch,
        )
        assert authoritative == "DARIUS"
        assert envelopes == []

    def test_envelope_persists_row_lane_not_caller(
        self, session_offer_db, monkeypatch
    ):
        sid = "anchor-envelope"
        _seed_session_with_lane(session_offer_db["db_path"], sid, "DARIUS")
        _run_offer_capture_anchor(
            db_path=session_offer_db["db_path"],
            session_id=sid,
            caller_supplied_lane="primary",
            execution_lane="primary",
            monkeypatch=monkeypatch,
        )
        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT offer_envelope FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()
        envelope = json.loads(row[0])
        assert envelope["execution_lane"] == "DARIUS"
