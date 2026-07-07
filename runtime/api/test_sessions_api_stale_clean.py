"""TestCleanStaleHarnessSessions: unified stale-session cleanup tests."""

from __future__ import annotations

import json

import pytest

from runtime.api.test_sessions import _register  # noqa: F401  (plain helper)
from yoke_core.domain.sessions import (
    claim_work,
    clean_stale_harness_sessions,
)
from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    _now_literal,
    conn,  # noqa: F401  (backend-aware pytest fixture)
)


def _stamp_tool_activity(conn, session_id: str, ago_minutes: int) -> None:
    """Stamp the tool-activity columns the observe pipeline maintains."""
    conn.execute(
        """UPDATE harness_sessions
           SET last_tool_call_at = %s,
               tool_call_count = COALESCE(tool_call_count, 0) + 1
           WHERE session_id = %s""",
        (_ago_minutes(ago_minutes), session_id),
    )


class TestCleanStaleHarnessSessions:
    """Tests for unified stale-session cleanup."""

    @pytest.fixture
    def conn_with_events(self, conn):
        """Activity state lives on harness_sessions columns now."""
        return conn

    def test_reclaims_never_engaged_session(self, conn_with_events):
        """Stale heartbeat + zero tool events = never_engaged."""
        conn = conn_with_events
        _register(conn, session_id="stale-offer")
        _ts30 = _ago_minutes(30)
        conn.execute(
            """UPDATE harness_sessions
               SET offered_at = %s, last_heartbeat = %s
               WHERE session_id = 'stale-offer'""",
            (_ts30, _ts30),
        )
        conn.commit()
        claim_work(conn, session_id="stale-offer", item_id="YOK-100")
        conn.execute(
            """UPDATE work_claims
               SET claimed_at = %s, last_heartbeat = %s
               WHERE session_id = 'stale-offer'""",
            (_ts30, _ts30),
        )
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=10)

        assert len(result["never_engaged"]) == 1
        assert result["never_engaged"][0]["session_id"] == "stale-offer"
        assert result["total_reclaimed"] == 1

        # Verify session ended and claim released
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = 'stale-offer'",
        ).fetchone()
        assert row["ended_at"] is not None
        claim_row = conn.execute(
            "SELECT release_reason FROM work_claims WHERE item_id = '100'",
        ).fetchone()
        assert claim_row["release_reason"] == "reclaimed"

    def test_reclaims_heartbeat_stale_session(self, conn_with_events):
        """Stale heartbeat + has tool events = heartbeat_stale."""
        conn = conn_with_events
        _register(conn, session_id="dead-worker")
        _ts30 = _ago_minutes(30)
        conn.execute(
            """UPDATE harness_sessions
               SET offered_at = %s, last_heartbeat = %s
               WHERE session_id = 'dead-worker'""",
            (_ts30, _ts30),
        )
        conn.commit()
        claim_work(conn, session_id="dead-worker", item_id="YOK-200")
        conn.execute(
            """UPDATE work_claims
               SET claimed_at = %s, last_heartbeat = %s
               WHERE session_id = 'dead-worker'""",
            (_ts30, _ts30),
        )
        conn.commit()

        # Insert tool events so it's not never-engaged
        _stamp_tool_activity(conn, 'dead-worker', 25)
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=10)

        assert len(result["heartbeat_stale"]) == 1
        assert result["heartbeat_stale"][0]["session_id"] == "dead-worker"
        assert len(result["never_engaged"]) == 0
        assert result["total_reclaimed"] == 1

    def test_reclaims_progress_stale_session(self, conn_with_events):
        """Fresh heartbeat + old tool events = progress_stale."""
        conn = conn_with_events
        _register(conn, session_id="wedged-sess")
        # Heartbeat is fresh (just now), but tool events are old
        claim_work(conn, session_id="wedged-sess", item_id="YOK-300")

        _stamp_tool_activity(conn, 'wedged-sess', 120)
        conn.commit()

        result = clean_stale_harness_sessions(
            conn, stale_threshold_minutes=10, progress_threshold_minutes=90,
        )

        assert len(result["progress_stale"]) == 1
        assert result["progress_stale"][0]["session_id"] == "wedged-sess"
        assert len(result["heartbeat_stale"]) == 0
        assert len(result["never_engaged"]) == 0
        assert result["total_reclaimed"] == 1

    def test_skips_active_session_with_recent_progress(self, conn_with_events):
        """Fresh heartbeat + recent tool events = not stale."""
        conn = conn_with_events
        _register(conn, session_id="healthy-sess")
        claim_work(conn, session_id="healthy-sess", item_id="YOK-400")

        _stamp_tool_activity(conn, 'healthy-sess', 5)
        conn.commit()

        result = clean_stale_harness_sessions(
            conn, stale_threshold_minutes=10, progress_threshold_minutes=90,
        )

        assert len(result["never_engaged"]) == 0
        assert len(result["heartbeat_stale"]) == 0
        assert len(result["progress_stale"]) == 0
        assert result["total_reclaimed"] == 0

    def test_skips_already_ended_sessions(self, conn_with_events):
        """Already-ended sessions are not double-cleaned."""
        conn = conn_with_events
        _register(conn, session_id="ended-sess")
        _ts30 = _ago_minutes(30)
        _ts20 = _ago_minutes(20)
        conn.execute(
            """UPDATE harness_sessions
               SET offered_at = %s, last_heartbeat = %s, ended_at = %s
               WHERE session_id = 'ended-sess'""",
            (_ts30, _ts30, _ts20),
        )
        conn.commit()

        result = clean_stale_harness_sessions(conn, stale_threshold_minutes=10)
        assert result["total_reclaimed"] == 0

    def test_mixed_scenario_categorizes_correctly(self, conn_with_events):
        """Multiple sessions of different stale types are categorized correctly."""
        conn = conn_with_events
        _ts30 = _ago_minutes(30)

        # Never-engaged: stale heartbeat, no tool events
        _register(conn, session_id="never-engaged")
        conn.execute(
            """UPDATE harness_sessions
               SET offered_at = %s, last_heartbeat = %s
               WHERE session_id = 'never-engaged'""",
            (_ts30, _ts30),
        )

        # Heartbeat-stale: stale heartbeat, has tool events
        _register(conn, session_id="hb-stale")
        conn.execute(
            """UPDATE harness_sessions
               SET offered_at = %s, last_heartbeat = %s
               WHERE session_id = 'hb-stale'""",
            (_ts30, _ts30),
        )
        _stamp_tool_activity(conn, 'hb-stale', 25)

        # Progress-stale: fresh heartbeat, old tool events
        _register(conn, session_id="prog-stale")
        _stamp_tool_activity(conn, 'prog-stale', 120)

        # Healthy: fresh heartbeat, recent tool events
        _register(conn, session_id="healthy")
        _stamp_tool_activity(conn, 'healthy', 5)
        conn.commit()

        result = clean_stale_harness_sessions(
            conn, stale_threshold_minutes=10, progress_threshold_minutes=90,
        )

        ne_ids = {e["session_id"] for e in result["never_engaged"]}
        hb_ids = {e["session_id"] for e in result["heartbeat_stale"]}
        ps_ids = {e["session_id"] for e in result["progress_stale"]}

        assert ne_ids == {"never-engaged"}
        assert hb_ids == {"hb-stale"}
        assert ps_ids == {"prog-stale"}
        assert result["total_reclaimed"] == 3

    def test_aborts_reclaim_when_fresh_activity_lands_before_mutation(
        self, conn_with_events, monkeypatch,
    ):
        """AC-14: fresh activity between snapshot and mutation aborts reclaim.

        Snapshot picks the holder up as ``heartbeat_stale``; the
        recheck (``classify_reclaimable``) is monkey-patched to refresh
        the holder's heartbeat right before re-classifying, mirroring
        the real race shape. The cleanup must skip the mutation, leave
        ``ended_at`` NULL, and emit ``ReclaimAborted`` with
        ``scope='session_cleanup'``.
        """
        c = conn_with_events
        _register(c, session_id="racy-sess")
        _ts30 = _ago_minutes(30)
        c.execute(
            """UPDATE harness_sessions
               SET offered_at = %s, last_heartbeat = %s
               WHERE session_id = 'racy-sess'""",
            (_ts30, _ts30),
        )
        c.commit()
        claim_work(c, session_id="racy-sess", item_id="YOK-700")
        # With latest_activity centralizing liveness, the cleanup sweep uses
        # ``session_reclaim_activity.latest_activity`` for the snapshot,
        # which MAX-es harness + work_claims + tool-event signals. Age
        # the freshly-stamped claim heartbeat too so the snapshot picks
        # the session up as stale; the fresh_first_classify monkeypatch
        # below refreshes ``harness_sessions.last_heartbeat`` between
        # snapshot and mutation to exercise the race window.
        c.execute(
            """UPDATE work_claims
               SET claimed_at = %s, last_heartbeat = %s
               WHERE session_id = 'racy-sess' AND released_at IS NULL""",
            (_ts30, _ts30),
        )
        c.commit()

        from yoke_core.domain import sessions_cleanup as _sc

        real_classify = _sc.classify_reclaimable

        def fresh_first_classify(conn, sid, **kwargs):
            if sid == "racy-sess":
                conn.execute(
                    "UPDATE harness_sessions SET last_heartbeat = %s "
                    "WHERE session_id = %s",
                    (_now_literal(), sid),
                )
                conn.commit()
            return real_classify(conn, sid, **kwargs)

        monkeypatch.setattr(_sc, "classify_reclaimable", fresh_first_classify)

        # Capture emitted events via _sa._emit_session_event so we can assert
        # on the ReclaimAborted payload without depending on the full
        # production events-table schema being present in the test fixture.
        emitted = []
        from yoke_core.domain import sessions_analytics as _sa
        real_emit_session_event = _sa._emit_session_event

        def capture_emit(event_name, *, session_id, item_id=None,
                         task_num=None, context=None, outcome="completed"):
            emitted.append({
                "event_name": event_name,
                "session_id": session_id,
                "item_id": item_id,
                "task_num": task_num,
                "context": context,
                "outcome": outcome,
            })
            return real_emit_session_event(
                event_name,
                session_id=session_id,
                item_id=item_id,
                task_num=task_num,
                context=context,
                outcome=outcome,
            )

        monkeypatch.setattr(_sc._sa, "_emit_session_event", capture_emit)

        result = clean_stale_harness_sessions(c, stale_threshold_minutes=10)

        assert result["total_reclaimed"] == 0

        aborted = [e for e in emitted if e["event_name"] == "ReclaimAborted"]
        assert len(aborted) == 1
        ctx = aborted[0]["context"]
        assert ctx["scope"] == "session_cleanup"
        assert ctx["original_session_id"] == "racy-sess"
        assert ctx["abort_reason"] == "fresh"

        sess_row = c.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = 'racy-sess'",
        ).fetchone()
        assert sess_row["ended_at"] is None

        claim_row = c.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE item_id = 700",
        ).fetchone()
        assert claim_row["released_at"] is None
        assert claim_row["release_reason"] is None
