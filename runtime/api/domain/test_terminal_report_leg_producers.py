"""The leg marker moves only where the REAL producers move it.

The sibling work-leg tests set ``episode_started_at`` and ``turn_posture_at``
with direct UPDATEs, which proves what the key does with a given marker but not
which live code path changes one. That gap is exactly how an earlier keying
passed its tests and was still wrong: ``turn_posture_at`` looks like a turn
boundary and is also stamped by ordinary tool-call activity.

So this module drives the producers themselves against the production schema —
``register_session`` for a fresh start, for an active duplicate, and for a
reactivation after the session ended, plus the telemetry pipeline's own
``apply_envelope_state`` for a tool call — and asserts which of them may let a
second completion reach the seat.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain import db_backend
from yoke_core.domain import sessions_lifecycle_registry
from yoke_core.domain.actor_permissions import (
    ROLE_OPERATOR,
    grant_actor_project_role,
)
from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.sessions_analytics_core import SessionError
from yoke_core.domain.sessions_lifecycle_registry import register_session
from runtime.api.fixtures.file_test_db import init_test_db


WORKER = "worker-session"
SEAT = "seat-session"
NOW = datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)
STAMP = "2026-09-15T16:00:00Z"
RESUMED_STAMP = "2026-09-15T16:31:00Z"
ACTOR_ID = 2
#: At or above the hook-route floor: an unroutable seat is no recipient at all.
ROUTABLE_VERSION = "2.1.269"


@pytest.fixture(autouse=True)
def _registration_clock(monkeypatch):
    """Pin the registration clock so episode stamps are chosen, not raced.

    ``episode_started_at`` has second granularity, and a test registers and
    reactivates far faster than that. Real resumes are minutes apart; pinning
    the clock states which episode each registration belongs to instead of
    depending on wall-clock elapsing between two calls.
    """

    def _set(stamp: str) -> None:
        monkeypatch.setattr(
            sessions_lifecycle_registry, "_now_iso", lambda: stamp, raising=True
        )

    _set(STAMP)
    return _set


def _register(conn, workspace: str, *, session_id: str = WORKER) -> dict:
    """The one real registration path, used for every shape under test."""
    return register_session(
        conn,
        session_id=session_id,
        executor="claude-code",
        provider="anthropic",
        model_facts=SessionModelFacts(),
        execution_lane="DARIUS",
        workspace=workspace,
        project_id=1,
        entrypoint="claude-cli",
        actor_id=ACTOR_ID,
        executor_version=ROUTABLE_VERSION,
    )


def _seed(conn, workspace: str) -> int:
    """One item, a steering seat, and a worker holding that item's claim."""
    grant_actor_project_role(
        conn, actor_id=ACTOR_ID, project_id=1, role_name=ROLE_OPERATOR
    )
    item_id = int(
        conn.execute(
            "INSERT INTO items (title, status, created_at, updated_at, "
            "project_id, project_sequence, workflow_id, workflow_version_id) "
            "VALUES ('leg producers', 'implementing', %s, %s, 1, 9001, "
            "'dash', 1) RETURNING id",
            (STAMP, STAMP),
        ).fetchone()[0]
    )
    _register(conn, workspace, session_id=SEAT)
    _register(conn, workspace)
    for session_id, kind, scope in (
        (SEAT, "steering", '{"project_id":1}'),
        (WORKER, "item", '{"item_id":%d}' % item_id),
    ):
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, "
            "claimed_at, last_heartbeat) VALUES (%s, %s, %s, %s, %s)",
            (session_id, kind, scope, STAMP, STAMP),
        )
    conn.commit()
    return item_id


def _report(conn, body: str) -> dict:
    return send_message(
        conn,
        actor_id=ACTOR_ID,
        sender_session_id=WORKER,
        selector=RecipientSelector(steering=True),
        body=body,
        now=NOW,
    )


def _tool_call(conn, *, at: str) -> None:
    """The producer that defeated the previous keying: ordinary activity."""
    apply_envelope_state(
        conn,
        {
            "event_name": "HarnessToolCallCompleted",
            "session_id": WORKER,
            "event_time": at,
            "tool_use_id": f"tool-{at}",
            "tool_name": "Bash",
        },
    )
    conn.commit()


def _end(conn) -> None:
    conn.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        (STAMP, WORKER),
    )
    conn.commit()


def _worker_row(conn) -> dict:
    row = conn.execute(
        "SELECT episode_started_at, turn_posture_at FROM harness_sessions "
        "WHERE session_id=%s",
        (WORKER,),
    ).fetchone()
    return {"episode": str(row[0]), "posture_at": row[1]}


def _live_item_claims(conn) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE session_id=%s "
            "AND target_kind='item' AND released_at IS NULL",
            (WORKER,),
        ).fetchone()[0]
    )


def test_a_real_tool_call_does_not_open_a_leg(tmp_path) -> None:
    with init_test_db(tmp_path):
        conn = db_backend.connect()
        _seed(conn, str(tmp_path))
        first = _report(conn, "DONE YOK-9001 first completion.")
        opened = _worker_row(conn)

        _tool_call(conn, at="2026-09-15T16:05:00+00:00")
        after = _worker_row(conn)
        retry = _report(conn, "DONE YOK-9001 first completion, reworded.")

        # The activity really did move the posture stamp — which is why the
        # leg must not read it — and really did not move the episode.
        assert after["posture_at"] != opened["posture_at"]
        assert after["episode"] == opened["episode"]
        assert retry["message_id"] == first["message_id"]
        assert retry["deduplicated"] is True


def test_an_active_duplicate_registration_does_not_open_a_leg(tmp_path) -> None:
    with init_test_db(tmp_path):
        conn = db_backend.connect()
        _seed(conn, str(tmp_path))
        first = _report(conn, "DONE YOK-9001 first completion.")
        opened = _worker_row(conn)

        # A live session re-registering is refused outright, so it can never
        # restamp the episode behind a worker that is still mid-leg.
        with pytest.raises(SessionError) as refused:
            _register(conn, str(tmp_path))
        retry = _report(conn, "DONE YOK-9001 first completion, again.")

        assert refused.value.code == "SESSION_EXISTS"
        assert _worker_row(conn)["episode"] == opened["episode"]
        assert retry["message_id"] == first["message_id"]


def test_a_real_reactivation_lets_the_next_completion_reach_the_seat(
    tmp_path, _registration_clock
) -> None:
    with init_test_db(tmp_path):
        conn = db_backend.connect()
        _seed(conn, str(tmp_path))
        first = _report(conn, "DONE YOK-9001 first completion.")
        opened = _worker_row(conn)

        # The worker's session ended; a wake re-registers it. The claim is
        # never released, so this is the retained-lane resume.
        _end(conn)
        _registration_clock(RESUMED_STAMP)
        _register(conn, str(tmp_path))
        resumed = _report(conn, "DONE YOK-9001 retest green after resume.")

        assert _worker_row(conn)["episode"] != opened["episode"]
        assert _live_item_claims(conn) == 1
        assert resumed["message_id"] != first["message_id"]
        assert resumed["deduplicated"] is False
