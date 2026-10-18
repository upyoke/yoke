"""Only an exact, still-stopped capacity predecessor may hand off custody."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_capacity_claim_transfer import transfer_capacity_claim
from yoke_core.domain.session_capacity_recovery import relaunch_capacity_worker
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_contracts.timestamps import format_instant
from runtime.api.domain.session_capacity_test_support import (
    CLAIM_ID,
    CURRENT,
    PREDECESSOR,
    capacity_connection,
    claim,
    state,
)


def _successor(monkeypatch):
    conn, _ = capacity_connection(monkeypatch)
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    conn.execute(
        "INSERT INTO harness_sessions (session_id,project_id,executor_surface,machine_id,model) VALUES ('successor',10,'claude-cli','m-codex','claude-opus-5-5')"
    )
    conn.commit()
    # Attribution's Postgres-only statements are independently tested; retain
    # their transaction contract while running launch/custody on SQLite here.
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_attribution.clear_current_item",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_attribution.set_current_item",
        lambda *_a, **_k: None,
    )
    return conn, get_launch(conn, result["launch_id"])


def test_registration_transfers_exact_claim_and_reaps_old_native(monkeypatch):
    conn, launch = _successor(monkeypatch)
    transfer_capacity_claim(conn, launch=launch, session_id="successor", now=CURRENT)
    conn.commit()
    assert tuple(claim(conn)) == (CLAIM_ID, "successor", None)


def test_exact_binding_transfers_claim_before_mandate_delivery(monkeypatch):
    from yoke_core.domain.session_launch_registered_session_binding import (
        bind_launch_to_session,
        require_registered_session_facts,
    )
    from yoke_core.domain.session_launch_store import update_launch

    conn, launch = _successor(monkeypatch)
    conn.execute(
        "UPDATE harness_sessions SET executor_version='2.1.259',executor='claude-code' WHERE session_id='successor'"
    )
    launch = update_launch(
        conn,
        launch.launch_id,
        state="awaiting_registration",
        native_session_id="successor",
    )
    bound = bind_launch_to_session(
        conn,
        launch=launch,
        session_id="successor",
        facts=require_registered_session_facts(conn, "successor"),
        now=CURRENT,
        wake_after=CURRENT,
    )
    conn.commit()
    assert bound.registered_session_id == "successor"
    assert tuple(claim(conn)) == (CLAIM_ID, "successor", None)
    receipt = conn.execute(
        "SELECT state FROM session_message_recipients WHERE session_id='successor'"
    ).fetchone()
    assert receipt[0] == "pending"
    old = conn.execute(
        "SELECT ended_at,terminated_at,termination_reason FROM harness_sessions WHERE session_id=?",
        (PREDECESSOR,),
    ).fetchone()
    assert old[0] and old[1]
    assert launch.launch_id in old[2]
    reap = conn.execute(
        "SELECT state FROM session_termination_reaps WHERE target_session_id=?",
        (PREDECESSOR,),
    ).fetchone()
    assert reap[0] == "pending"
    transfer_capacity_claim(conn, launch=launch, session_id="successor", now=CURRENT)
    assert tuple(claim(conn)) == (CLAIM_ID, "successor", None)


@pytest.mark.parametrize("change", ["released", "new_work", "other_actor"])
def test_changed_custody_refuses_without_transferring(monkeypatch, change):
    conn, launch = _successor(monkeypatch)
    if change == "released":
        conn.execute(
            "UPDATE work_claims SET released_at=? WHERE id=?",
            (format_instant(CURRENT), CLAIM_ID),
        )
    elif change == "new_work":
        conn.execute(
            "UPDATE harness_sessions SET last_tool_call_at=? WHERE session_id=?",
            (format_instant(CURRENT), PREDECESSOR),
        )
    else:
        conn.execute(
            "UPDATE harness_sessions SET actor_id=2 WHERE session_id='successor'"
        )
    conn.commit()
    with pytest.raises(SessionLaunchError, match="Recovery: steering"):
        transfer_capacity_claim(
            conn, launch=launch, session_id="successor", now=CURRENT
        )
    assert claim(conn)[1] == PREDECESSOR


def test_successor_capacity_does_not_return_to_prior_overloaded_model(monkeypatch):
    from yoke_core.domain.session_recovery_facts import (
        record_native_turn_end,
        reserve_resume_attempt,
        resume_episode_key,
    )

    conn, launch = _successor(monkeypatch)
    transfer_capacity_claim(conn, launch=launch, session_id="successor", now=CURRENT)
    conn.execute(
        "UPDATE session_launches SET registered_session_id='successor' WHERE launch_id=?",
        (launch.launch_id,),
    )
    record_native_turn_end(
        conn,
        "successor",
        observation={
            "observed_at": format_instant(CURRENT),
            "codex_error_info": "server_overloaded",
            "error_message": "Selected model is at capacity",
        },
        recorded_at=CURRENT,
    )
    for _ in range(3):
        reserve_resume_attempt(
            conn, "successor", episode_key=resume_episode_key(None), budget=3
        )
    conn.commit()
    result = relaunch_capacity_worker(conn, state=state(conn), now=CURRENT)
    assert result["status"] == "capacity_recovery_refused"
    assert result["code"] == "level_no_capacity"
    assert "gpt-6.1-sol" in result["detail"]
    assert claim(conn)[1] == "successor"
