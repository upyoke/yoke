"""Project refusal preserves turn boundaries without authorizing project work."""

from __future__ import annotations

from fastapi import BackgroundTasks
import json
from types import SimpleNamespace

import pytest

from yoke_core.api.routes.hooks import HookEvaluateRequest, post_hooks_evaluate
from runtime.api.domain.test_session_native_turn_end import (
    LATER,
    NOW,
    _apply,
    _codex_connection,
    _posture,
    _send,
    _pending,
)
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.api.http_auth import HttpAuthContext


@pytest.mark.parametrize(
    "executor,event,project",
    [
        ("codex", "Stop", None),
        ("claude", "Stop", None),
        ("cursor", "SessionEnd", None),
        ("codex", "Stop", 7),
    ],
)
def test_project_denied_turn_end_stamps_owned_session_and_preserves_refusal(
    executor,
    event,
    project,
    monkeypatch,
):
    conn = _codex_connection()
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: conn)
    monkeypatch.setattr(
        "yoke_core.domain.session_scope_identity.actor_visible_project_ids",
        lambda *_: set(),
    )
    monkeypatch.setattr(
        "yoke_core.api.routes.hooks.require_auth_context",
        lambda _: HttpAuthContext(1, 10, "test"),
    )
    monkeypatch.setattr(
        "yoke_core.api.routes.hooks._emit_route_denial", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "yoke_core.api.routes.hooks.datetime", SimpleNamespace(now=lambda _: LATER)
    )
    monkeypatch.setattr(
        "yoke_core.api.routes.hooks.evaluate_remote",
        lambda **_: pytest.fail("project work must stay denied"),
    )
    request = HookEvaluateRequest(
        event_name=event,
        executor=executor,
        project_id=project,
        stdin=json.dumps({"session_id": "s2", "identity_stamped": True}),
    )
    body = json.loads(
        post_hooks_evaluate(SimpleNamespace(), request, BackgroundTasks()).body
    )
    assert body["outcome"] == "denied"
    assert body["exit_code"] == 1
    assert "HOOK_PROJECT_DENIED" in body["stdout"]
    assert body["degraded"] == []
    assert _posture(conn) == "waiting"
    _send(conn)
    eligible = wake_eligible_recipients(conn, now=LATER)
    assert [entry["session_id"] for entry in eligible] == ["s2"]
    assert eligible[0]["wake_mode"] == "waiting"


def test_clean_rollout_recovers_a_denied_stop_and_routes_next_message_to_resume(
    tmp_path,
):
    from yoke_harness.session_relay_codex_turn_record import terminal_turn
    from yoke_contracts.timestamps import format_instant

    conn = _codex_connection()
    assert _pending(conn) == [{"session_id": "s2", "executor_surface": "codex-cli"}]
    day = tmp_path / "2026" / "08" / "22"
    day.mkdir(parents=True)
    (day / "rollout-2026-08-22T16-00-00-s2.jsonl").write_text(
        json.dumps(
            {
                "timestamp": format_instant(NOW),
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": "clean-turn",
                    "error": None,
                },
            }
        )
        + "\n"
    )
    observed = terminal_turn("s2", transcript_roots=[tmp_path])
    assert observed is not None
    assert _apply(
        conn,
        observed_at=format_instant(observed.observed_at),
        evidence=observed.evidence,
    ) == {"reclassified": ["s2"], "skipped": []}
    eligible = wake_eligible_recipients(conn, now=LATER)
    assert [entry["session_id"] for entry in eligible] == ["s2"]
    assert eligible[0]["wake_mode"] == "waiting"


@pytest.mark.parametrize("actor,event", [(11, "Stop"), (10, "UserPromptSubmit")])
def test_project_refusal_does_not_grant_foreign_session_or_prompt_authority(
    actor, event, monkeypatch
):
    conn = _codex_connection()
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: conn)
    monkeypatch.setattr(
        "yoke_core.domain.session_scope_identity.actor_visible_project_ids",
        lambda *_: set(),
    )
    monkeypatch.setattr(
        "yoke_core.api.routes.hooks.require_auth_context",
        lambda _: HttpAuthContext(1, actor, "test"),
    )
    monkeypatch.setattr(
        "yoke_core.api.routes.hooks._emit_route_denial", lambda *a, **k: None
    )
    request = HookEvaluateRequest(
        event_name=event, stdin=json.dumps({"session_id": "s2"})
    )
    body = json.loads(
        post_hooks_evaluate(SimpleNamespace(), request, BackgroundTasks()).body
    )
    assert _posture(conn) == "running"
    if actor == 11:
        assert "turn_posture_owner_unverified" in body["stdout"]
        assert body["degraded"]


def test_posture_database_failure_keeps_project_refusal_and_teaches_recovery(
    monkeypatch,
):
    def unavailable():
        raise RuntimeError("unavailable")

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", unavailable)
    monkeypatch.setattr(
        "yoke_core.api.routes.hooks.require_auth_context",
        lambda _: HttpAuthContext(1, 10, "test"),
    )
    monkeypatch.setattr(
        "yoke_core.api.routes.hooks._emit_route_denial", lambda *a, **k: None
    )
    request = HookEvaluateRequest(
        event_name="Stop", stdin=json.dumps({"session_id": "s2"})
    )
    body = json.loads(
        post_hooks_evaluate(SimpleNamespace(), request, BackgroundTasks()).body
    )
    assert body["outcome"] == "denied"
    assert "HOOK_SCOPE_AUTH_UNAVAILABLE" in body["stdout"]
    assert "turn_posture_unavailable" in body["stdout"]
    assert "yoke hook evaluate" in body["stdout"]
