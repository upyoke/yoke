"""Item-bound launches refuse a live holder the worker cannot clear."""

from __future__ import annotations

from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.domain.session_launch_test_support import NOW
from runtime.api.domain.test_session_launch_terminal_admission import (
    _create_conn,
    _create_payload,
    _request,
    _write_counts,
)


def test_held_item_create_refuses_before_any_write(monkeypatch):
    conn, item = _create_conn(monkeypatch, status="idea")
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, model) "
        "VALUES ('holder-session', 10, 'gpt-5')"
    )
    target = make_item_target(41)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, "
        "last_heartbeat) VALUES (?, 'item', ?, 'exclusive', ?, ?)",
        ("holder-session", target.scope_json(), NOW, NOW),
    )
    conn.commit()
    before = _write_counts(conn)

    outcome = handlers.handle_launch_create(
        _request(_create_payload(item, compose_mandate=True, key="held-1"))
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "assignment_item_claimed"
    assert "holder-session" in outcome.error.message
    assert "yoke sessions terminate holder-session" in outcome.error.message
    assert "held work claims" in outcome.error.message
    assert _write_counts(conn) == before
