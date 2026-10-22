"""A staffed item with real launch storage and multiple level options."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.session_recovery_facts import (
    record_native_turn_end,
    reserve_resume_attempt,
    resume_episode_key,
)
from yoke_core.domain.session_vendor_error_states import vendor_error_states
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization
from runtime.api.domain.test_session_launch_terminal_admission import _seed_pinned_item

STOPPED = parse_instant(NOW)
CURRENT = STOPPED + timedelta(minutes=1)
PREDECESSOR = "capacity-worker"
CLAIM_ID = 17


def capacity_connection(
    monkeypatch,
    *,
    alternative=True,
    alternative_machine="m-codex",
    error="server overloaded",
    attempts=3,
):
    options = (CODEX_SOL, CLAUDE_OPUS) if alternative else (CODEX_SOL,)
    conn = level_connection(*options)
    from yoke_core.domain.model_reference_store import (
        create_model_reference_table,
        seed_initial_catalog,
    )

    create_model_reference_table(conn)
    seed_initial_catalog(conn)
    ref = _seed_pinned_item(conn, status="implementing")
    for declaration in (
        "actor_id INTEGER DEFAULT 1",
        "last_tool_call_at TEXT",
        "turn_posture TEXT DEFAULT 'waiting'",
        "execution_level TEXT DEFAULT 'SENIOR'",
        "executor TEXT DEFAULT 'codex'",
        "last_heartbeat TEXT",
        "current_item_id TEXT",
        "current_item_set_at TEXT",
        "recent_item_id TEXT",
        "recent_item_status TEXT",
        "recent_item_recorded_at TEXT",
        "terminated_by_actor_id INTEGER",
        "terminated_by_session_id TEXT",
        "termination_reason TEXT",
    ):
        conn.execute(f"ALTER TABLE harness_sessions ADD COLUMN {declaration}")
    conn.execute(
        "INSERT INTO harness_sessions (session_id,project_id,executor_surface,machine_id,model) "
        "VALUES (?,10,'codex-cli','m-codex',?)",
        (PREDECESSOR, CODEX_SOL["model"]),
    )
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES (?,?,'item',?,'exclusive',?,?)",
        (CLAIM_ID, PREDECESSOR, make_item_target(41).scope_json(), NOW, NOW),
    )
    add_surface(conn, "m-codex", "codex-cli", [weekly(95)])
    if alternative:
        add_surface(conn, alternative_machine, "claude-cli", [weekly(40)])
    record_native_turn_end(
        conn,
        PREDECESSOR,
        observation={
            "observed_at": NOW,
            "codex_error_info": "server_overloaded",
            "error_message": error,
        },
        recorded_at=NOW,
    )
    for _ in range(attempts):
        reserve_resume_attempt(
            conn, PREDECESSOR, episode_key=resume_episode_key(None), budget=3
        )
    pin_live_workers(monkeypatch, {})
    monkeypatch.setattr(
        "yoke_core.domain.session_launch_authorization.launch_authorization",
        lambda *_a, **_k: authorization(),
    )
    monkeypatch.setattr(
        "yoke_core.domain.workflow_execution_instructions.resolve_for_item",
        lambda *_a, **_k: [],
    )
    conn.commit()
    return conn, ref


def state(conn):
    return vendor_error_states(conn, authorized_projects=(10,), now=CURRENT)[0]


def claim(conn):
    return conn.execute(
        "SELECT id,session_id,released_at FROM work_claims WHERE id=?", (CLAIM_ID,)
    ).fetchone()


def observation(conn):
    return json.loads(
        conn.execute(
            "SELECT native_turn_end_observation FROM harness_sessions WHERE session_id=?",
            (PREDECESSOR,),
        ).fetchone()[0]
    )
