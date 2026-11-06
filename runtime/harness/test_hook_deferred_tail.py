"""Remote bookkeeping never delays guard results or changes denials."""

from datetime import datetime, timezone
from types import SimpleNamespace
import time

import pytest

from yoke_core.hooks.run_tail import flush_run_tail
from yoke_core.hooks.deferred_tail import bounded_tail_connection


@pytest.mark.parametrize("outcome", ["allow", "deny"])
@pytest.mark.parametrize("budget_remaining", [True, False])
def test_remote_tail_defers_observation_posture_and_lifecycle(
    monkeypatch,
    outcome,
    budget_remaining,
):
    calls = []
    monkeypatch.setattr(
        "yoke_core.hooks.telemetry.flush_hook_telemetry",
        lambda records, **kw: calls.append(("flush", records, kw)),
    )
    monkeypatch.setattr(
        "yoke_core.hooks.session_turn_posture_tail.persist_accepted_hook_turn_posture",
        lambda **kw: calls.append(("posture", kw)),
    )
    monkeypatch.setattr(
        "yoke_core.hooks.remote_lifecycle.run_remote_session_lifecycle",
        lambda *args, **kw: calls.append(("lifecycle", kw)),
    )
    context = SimpleNamespace(
        session_id="remote",
        executor_family="codex",
        item_id=None,
        tool_name="",
        now=None,
    )
    controls = SimpleNamespace(remote=True, actor_id=1, deferred_telemetry=None)
    flush_run_tail(
        event_name="PreToolUse",
        context=context,
        chain_length=1,
        final_outcome=outcome,
        hook_wait_ms=2,
        timed_out=False,
        deadline=SimpleNamespace(
            telemetry_allowed=lambda: budget_remaining, budget_ms=100
        ),
        payload={},
        stdin_data="",
        controls=controls,
        telem_records=[],
    )
    assert len(calls) == 1
    assert calls[0][2]["ensure_session"] is not None
    assert calls[0][2]["observed_session"] is None
    controls.deferred_telemetry(123)
    assert [call[0] for call in calls] == (
        ["flush", "flush", "posture"] + (["lifecycle"] if outcome == "allow" else [])
    )
    assert calls[1][2]["observed_session"][0] == "remote"
    assert calls[1][1][-1][1]["extra"]["server_wall_ms"] == 123
    assert calls[2][1]["final_outcome"] == outcome


def _minimal_schema():
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        conn.execute(
            "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, "
            "turn_posture TEXT, turn_posture_at TIMESTAMPTZ)"
        )
        conn.execute("INSERT INTO harness_sessions VALUES ('locked','running',NULL)")
        conn.commit()


def test_locked_session_does_not_hold_response_and_background_skips_write(
    tmp_path, monkeypatch, bound_project_context
):
    from runtime.api.fixtures.file_test_db import init_test_db, connect_test_db
    from yoke_core.hooks.session_turn_posture_tail import (
        persist_accepted_hook_turn_posture,
    )

    with init_test_db(tmp_path, apply_schema=_minimal_schema) as db_path:
        lock = connect_test_db(db_path)
        lock.execute(
            "UPDATE harness_sessions SET turn_posture='running' WHERE session_id='locked'"
        )
        try:
            started = time.monotonic()
            context = SimpleNamespace(
                session_id="locked",
                executor_family="codex",
                item_id=None,
                tool_name="",
                now=datetime.now(timezone.utc),
            )
            import json
            import sys
            import types
            from yoke_core.hooks import runner
            from yoke_core.hooks.remote_entry import evaluate_remote
            from yoke_core.hooks.types import HookDecision, Next, Outcome

            guard = types.ModuleType("locked_session.guard")
            guard.evaluate = lambda _context: HookDecision(
                outcome=Outcome.DENY,
                next=Next.STOP,
                message="guard remains denied",
            )
            monkeypatch.setitem(sys.modules, "locked_session.guard", guard)
            monkeypatch.setattr(
                runner, "chain_for", lambda *a, **kw: ["locked_session.guard"]
            )
            result = evaluate_remote(
                "Stop",
                json.dumps({"session_id": "locked"}),
                "codex",
                None,
                10000,
                project_id=7,
                project_slug="example",
                actor_id=3,
            )
            assert time.monotonic() - started < 1
            assert result.outcome == "denied"
            assert "guard remains denied" in result.stdout
            assert result.flush_telemetry is not None
            # Exercise the same background connection factory against a real PG row lock.
            started = time.monotonic()
            assert not persist_accepted_hook_turn_posture(
                event_name="Stop",
                session_id="locked",
                observed_at=context.now,
                final_outcome="allow",
                timed_out=False,
                failed=False,
                connection_factory=bounded_tail_connection,
            )
            assert 1.5 < time.monotonic() - started < 4
        finally:
            lock.rollback()
            lock.close()


def test_background_tail_keeps_authorized_request_context(monkeypatch):
    from contextvars import ContextVar
    from yoke_core.hooks.deferred_tail import deferred_flush

    project = ContextVar("test_authorized_project", default="ambient")
    observed = []
    monkeypatch.setattr(
        "yoke_core.hooks.telemetry.flush_hook_telemetry",
        lambda *a, **kw: observed.append(project.get()),
    )
    monkeypatch.setattr(
        "yoke_core.hooks.session_turn_posture_tail.persist_accepted_hook_turn_posture",
        lambda **kw: observed.append(project.get()),
    )
    token = project.set("authorized")
    flush = deferred_flush(
        [],
        {},
        observed_session=None,
        event_name="Stop",
        context=SimpleNamespace(session_id="", now=None),
        final_outcome="deny",
        timed_out=False,
        failed=False,
    )
    project.reset(token)
    flush(10)
    assert observed == ["authorized", "authorized"]
    assert project.get() == "ambient"
