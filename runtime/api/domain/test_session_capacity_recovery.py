"""Capacity recovery runs through actual placement, launch and report owners."""

from __future__ import annotations

import json

from yoke_core.domain.session_capacity_recovery import relaunch_capacity_worker
from yoke_core.domain.session_vendor_error_resume import resume_vendor_error_sessions
from yoke_core.domain.steering_fleet_report_render_vendor_errors import _next_actor
from yoke_core.domain.steering_fleet_report_vendor_errors import vendor_error_sessions
from yoke_contracts.timestamps import format_instant
from runtime.api.domain.session_capacity_test_support import (
    CURRENT,
    PREDECESSOR,
    capacity_connection,
    claim,
    observation,
    state,
)


def test_exhausted_overload_relaunches_different_same_level_model_once(monkeypatch):
    conn, _ = capacity_connection(monkeypatch)
    original = tuple(claim(conn))
    outcome = resume_vendor_error_sessions(
        conn, machine_id="m-codex", authorized_projects=(10,), actor_id=2, now=CURRENT
    )
    assert outcome["resumed"] == []
    assert len(outcome["relaunched"]) == 1
    launch = conn.execute("SELECT * FROM session_launches").fetchone()
    assert launch["requested_level"] == "SENIOR"
    assert launch["requested_machine_id"] == launch["assigned_machine_id"] == "m-codex"
    assert launch["resolved_model"] == "claude-opus-5-5"
    assert launch["requester_actor_id"] == 1
    placement = json.loads(launch["level_placement"])
    assert any(
        c["model"] == "gpt-6.1-sol"
        and c["blocked"].startswith("model_capacity_excluded")
        for c in placement["candidates"]
    )
    assert placement["capacity_recovery"]["predecessor_session_id"] == PREDECESSOR
    body = conn.execute("SELECT body FROM session_messages").fetchone()[0]
    assert "Progress Log" in body and "preserve dirty files" in body
    assert tuple(claim(conn)) == original
    assert state(conn)["status"] == "capacity_recovery_pending"
    again = resume_vendor_error_sessions(
        conn, machine_id="m-codex", authorized_projects=(10,), actor_id=2, now=CURRENT
    )
    assert again["relaunched"] == []
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 1


def test_model_capacity_waits_for_wake_budget_before_relaunch(monkeypatch):
    from yoke_core.domain.session_recovery_facts import (
        reserve_resume_attempt,
        resume_episode_key,
    )

    conn, _ = capacity_connection(
        monkeypatch,
        error="Selected model is at capacity. Please try a different model.",
        attempts=0,
    )
    assert state(conn)["status"] == "due"
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 0
    for attempt in range(3):
        reserve_resume_attempt(
            conn, PREDECESSOR, episode_key=resume_episode_key(None), budget=3
        )
        if attempt < 2:
            assert state(conn)["status"] == "waiting_backoff"
    assert state(conn)["status"] == "relaunch_due"
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    assert "launch_id" in result
    assert observation(conn)["error_message"].startswith("Selected model")


def test_no_alternative_preserves_claim_and_surfaces_named_refusal_to_steering(
    monkeypatch,
):
    conn, _ = capacity_connection(monkeypatch, alternative=False)
    original = tuple(claim(conn))
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    assert result["status"] == "capacity_recovery_refused"
    assert result["code"] == "level_no_capacity"
    assert "model_capacity_excluded" in result["detail"]
    assert tuple(claim(conn)) == original
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 0
    rows = vendor_error_sessions(conn, project_id=10, now=format_instant(CURRENT))
    assert rows[0].seat_owed
    assert "level_no_capacity" in _next_actor(rows[0])
    assert "Relaunch at another level" in _next_actor(rows[0])
    assert state(conn)["status"] == "capacity_recovery_refused"


def test_remote_alternative_refuses_when_local_model_overloaded(monkeypatch):
    conn, _ = capacity_connection(monkeypatch, alternative_machine="m-remote")
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    assert result["code"] == "level_no_capacity"
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 0
    assert claim(conn)[1] == PREDECESSOR


def test_placeholder_model_requires_identity_repair_before_relaunch(monkeypatch):
    conn, _ = capacity_connection(monkeypatch)
    conn.execute(
        "UPDATE harness_sessions SET model='default' WHERE session_id=?", (PREDECESSOR,)
    )
    conn.commit()
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    assert result["code"] == "capacity_recovery_identity_missing"
    assert state(conn)["status"] == "capacity_recovery_refused"
    assert claim(conn)[1] == PREDECESSOR


def test_published_model_alias_excludes_the_same_capacity_overloaded_model(monkeypatch):
    from yoke_core.domain.universe_levels import write_universe_levels
    from runtime.api.domain.session_launch_level_test_support import CODEX_SOL

    conn, _ = capacity_connection(monkeypatch)
    write_universe_levels(
        conn,
        [
            {
                "name": "SENIOR",
                "glyph": "🦉",
                "options": [
                    CODEX_SOL,
                    {
                        "model": "claude-fable-5-1",
                        "min_effort": "medium",
                    },
                ],
            }
        ],
        actor_id=1,
    )
    conn.execute(
        "UPDATE harness_sessions SET model='claude-fable-5.1',executor_surface='claude-cli',executor='claude-code' WHERE session_id=?",
        (PREDECESSOR,),
    )
    conn.commit()
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    assert "launch_id" in result, result
    launch = conn.execute(
        "SELECT resolved_model,level_placement FROM session_launches"
    ).fetchone()
    assert launch[0] == "gpt-6.1-sol"
    candidates = json.loads(launch[1])["candidates"]
    assert next(c for c in candidates if c["model"] == "claude-fable-5-1")[
        "blocked"
    ].startswith("model_capacity_excluded")


def test_successor_launch_failure_is_actionable_and_does_not_loop(monkeypatch):
    conn, _ = capacity_connection(monkeypatch)
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    conn.execute(
        "UPDATE session_launches SET state='failed',result_code='native_spawn_failed' WHERE launch_id=?",
        (result["launch_id"],),
    )
    conn.commit()
    found = state(conn)
    assert found["status"] == "capacity_recovery_refused"
    assert "capacity_successor_failed" in found["reason"]
    assert "native_spawn_failed" in found["reason"]
    assert tuple(claim(conn))[1:] == (PREDECESSOR, None)


def test_new_work_prevents_capacity_relaunch(monkeypatch):
    conn, _ = capacity_connection(monkeypatch)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=? WHERE session_id=?",
        (format_instant(CURRENT), PREDECESSOR),
    )
    conn.commit()
    outcome = resume_vendor_error_sessions(
        conn, machine_id="m-codex", authorized_projects=(10,), actor_id=1, now=CURRENT
    )
    assert outcome["relaunched"] == []


def test_retry_preserves_model_exclusion_and_predecessor_custody(monkeypatch):
    from yoke_core.domain.session_launch_requests import retry_launch
    from runtime.api.domain.session_launch_test_support import authorization

    conn, _ = capacity_connection(monkeypatch)
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    conn.execute(
        "UPDATE session_launches SET state='failed' WHERE launch_id=?",
        (result["launch_id"],),
    )
    conn.commit()
    retried = retry_launch(
        conn, launch_id=result["launch_id"], auth=authorization(), now=CURRENT
    )
    assert retried.resolved_model == "claude-opus-5-5"
    recovery = json.loads(retried.level_placement)["capacity_recovery"]
    assert recovery["predecessor_session_id"] == PREDECESSOR
    assert "gpt-6.1-sol" in recovery["excluded_models"]
    assert claim(conn)[1] == PREDECESSOR


def test_unexpected_recovery_failure_is_named_and_retains_custody(monkeypatch):
    conn, _ = capacity_connection(monkeypatch)

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated failure during launch admission")

    monkeypatch.setattr(
        "yoke_core.domain.session_launch_mandate.launch_request_for_create", fail
    )
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    assert result["code"] == "capacity_recovery_failed"
    assert state(conn)["status"] == "capacity_recovery_refused"
    assert claim(conn)[1] == PREDECESSOR
