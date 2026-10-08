"""A changed effective stage level hands staffing to an admitted successor."""

from __future__ import annotations

import pytest

from yoke_core.domain import workflow_level_handoff as handoffs
from yoke_core.domain.session_launch_assignment import refuse_held_assigned_item
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.domain.session_launch_level_test_support import (
    CODEX_SOL,
    level_connection,
)
from runtime.api.domain.session_launch_test_support import NOW
from runtime.api.domain.test_session_launch_terminal_admission import _seed_pinned_item


def context(monkeypatch, *, target_level="JUNIOR", released=True):
    conn = level_connection(CODEX_SOL)
    ref = _seed_pinned_item(conn, status="release")
    conn.execute("ALTER TABLE items ADD COLUMN workflow_posture TEXT DEFAULT '{}'")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN execution_level TEXT")
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, execution_level) VALUES ('predecessor',10,'SENIOR')"
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat, released_at) VALUES (?, 'item', ?, 'exclusive', ?, ?, ?)",
        (
            "predecessor",
            make_item_target(41).scope_json(),
            NOW,
            NOW,
            NOW if released else None,
        ),
    )
    monkeypatch.setattr(
        handoffs,
        "item_stage_level",
        lambda *_a, **_k: {"level": target_level} if target_level else None,
    )
    conn.commit()
    return conn, ref


def test_different_effective_level_names_exact_successor_command(monkeypatch):
    conn, ref = context(monkeypatch)
    handoff = handoffs.level_handoff(
        conn, item_id=41, session_id="predecessor", stage_id="release"
    )
    assert handoff["reason"] == "level_change"
    assert handoff["stage_id"] == "release"
    assert handoff["level"] == "JUNIOR"
    assert f"--item {ref}" in handoff["next_command"]
    assert "--level" not in handoff["next_command"]


@pytest.mark.parametrize("target_level", ["SENIOR", None])
def test_same_effective_level_or_terminal_stage_has_no_handoff(
    monkeypatch, target_level
):
    conn, _ref = context(monkeypatch, target_level=target_level)
    assert (
        handoffs.level_handoff(
            conn, item_id=41, session_id="predecessor", stage_id="release"
        )
        is None
    )


def test_only_latest_released_holder_can_launch_its_own_level_successor(monkeypatch):
    conn, _ref = context(monkeypatch)
    args = dict(item_id=41, session_id="predecessor", level="JUNIOR")
    assert handoffs.released_level_predecessor(conn, **args) == "predecessor"
    assert (
        handoffs.released_level_predecessor(conn, **{**args, "level": "PRINCIPAL"})
        is None
    )
    conn.execute("UPDATE work_claims SET released_at=NULL")
    assert handoffs.released_level_predecessor(conn, **args) is None


def test_active_predecessor_claim_still_blocks_successor(monkeypatch):
    conn, ref = context(monkeypatch, released=False)
    with pytest.raises(SessionLaunchError) as failure:
        refuse_held_assigned_item(
            conn,
            public_ref=ref,
            project_id=10,
            predecessor_session_id="predecessor",
            successor_level="JUNIOR",
        )
    assert failure.value.code == "item_has_live_worker"


def test_released_predecessor_launch_is_exempt_but_other_live_launch_is_not(
    monkeypatch,
):
    from runtime.api.domain.session_launch_test_support import (
        add_relay,
        assigned_launch,
    )

    conn, ref = context(monkeypatch)
    add_relay(conn)
    old = assigned_launch(conn, key="old-worker")
    conn.execute(
        "UPDATE session_launches SET session_name=?, registered_session_id='predecessor', state='succeeded' WHERE launch_id=?",
        (f"{ref}: Active launch target", old.launch_id),
    )
    args = dict(
        public_ref=ref,
        project_id=10,
        predecessor_session_id="predecessor",
        successor_level="JUNIOR",
    )
    refuse_held_assigned_item(conn, **args)
    with pytest.raises(SessionLaunchError):
        refuse_held_assigned_item(conn, **{**args, "successor_level": "SENIOR"})
    conn.execute(
        "UPDATE session_launches SET registered_session_id=NULL, state='assigned'"
    )
    with pytest.raises(SessionLaunchError):
        refuse_held_assigned_item(conn, **args)


@pytest.mark.parametrize("changed", [False, True])
def test_transition_result_emits_handoff_only_for_a_level_change(monkeypatch, changed):
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.handlers import lifecycle_transition as handler

    monkeypatch.setattr(
        handler, "_read_current_status", lambda _id: ("implementing", "LP-41")
    )
    monkeypatch.setattr(handler, "_frozen_blocked", lambda *_a: None)
    monkeypatch.setattr(
        "yoke_core.domain.backlog.execute_update", lambda **_k: {"success": True}
    )
    monkeypatch.setattr(
        "yoke_core.domain.execution_instruction_delivery.item_instructions",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "yoke_core.domain.workflow_skill_handoff.item_skill_handoff",
        lambda *_a: (None, []),
    )
    handoff = {
        "reason": "level_change",
        "stage_id": "reviewing-implementation",
        "level": "JUNIOR",
        "next_command": "successor command",
    }
    monkeypatch.setattr(
        handoffs, "item_level_handoff", lambda *_a: (handoff if changed else None, [])
    )
    request = FunctionCallRequest(
        function="lifecycle.transition.execute",
        actor=ActorContext(actor_id="1", session_id="predecessor"),
        target=TargetRef(kind="item", item_id=41, public_ref="LP-41"),
        payload={
            "source_status": "implementing",
            "target_status": "reviewing-implementation",
        },
    )
    outcome = handler.handle_transition(request)
    assert outcome.primary_success
    if changed:
        assert outcome.result_payload["handoff"] == handoff
    else:
        assert "handoff" not in outcome.result_payload


def test_unresolved_session_label_does_not_invent_a_level_change(monkeypatch):
    from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL

    conn, _ref = context(monkeypatch)
    conn.execute(
        "UPDATE harness_sessions SET execution_level=?", (UNRESOLVED_EXECUTION_LEVEL,)
    )
    assert (
        handoffs.level_handoff(
            conn, item_id=41, session_id="predecessor", stage_id="release"
        )
        is None
    )
