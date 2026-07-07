"""Regression cases for the resume no-progress detector.

The detector lives in ``yoke_core.domain.session_decision_resume`` and
fires ``ESCALATE`` only when the prior chain step legitimately ran a
handler that did not move the item. These cases pin the four wires:

1. Healthy lifecycle handoff (pre_status != status) → RESUME.
2. Genuinely stuck state (pre_status == status, both present) → ESCALATE.
3. Backfill — pre_status missing on the checkpoint, falls back to the
   legacy same_state heuristic → ESCALATE.
4. Sanity — different item on the prior step → RESUME, the detector
   does not confuse work across items.

The detector is consumed by both the service_client subprocess path and
the FastAPI route path; both bridges map ``checkpoint.get("pre_status")``
into ``last_completed_step["pre_status"]`` so the detector sees the
field. The bridge regression below exercises the full writer → reader →
detector pipeline against a real schema-loaded database, proving that
``pre_status`` round-trips through ``update_chain_checkpoint`` and that
the bridge-shaped dict construction surfaces it to the detector.
"""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_core.domain.session_contract import (
    ActionKind,
    ClaimedWork,
    FrontierState,
    SessionOffer,
)
from yoke_core.domain.session_decision_resume import decide_resume_action
from yoke_core.domain.sessions_queries_chain import (
    read_chain_checkpoint,
    update_chain_checkpoint,
)


_SESSION_ID = "resume-no-progress-test-session"


def _make_offer(*, step: int = 2) -> SessionOffer:
    return SessionOffer(
        session_id=_SESSION_ID,
        executor="DARIUS",
        provider="anthropic",
        model="test-model",
        workspace="/tmp/yoke",
        execution_lane="DARIUS",
        step=step,
        supported_paths=[],
    )


def _make_frontier(last_step: dict | None) -> FrontierState:
    return FrontierState(last_completed_step=last_step)


def test_healthy_lifecycle_handoff_returns_resume() -> None:
    """Polish → implemented advanced the item; usher next step on same status.

    Replay of the YOK-1813 chain step 3 shape: prior checkpoint recorded
    ``pre_status=polishing-implementation`` and ``status=implemented``
    (the polish handler moved the item), and the new offer dispatches
    ``usher`` against the same ``status=implemented``. The legacy
    same_state heuristic would have OR-fired on the status match; the
    new direct-progress check sees that the prior step advanced the item
    and routes RESUME.
    """
    last_step = {
        "action": "resume",
        "item_id": "YOK-1813",
        "task_num": None,
        "pre_status": "polishing-implementation",
        "status": "implemented",
        "required_path": "polish",
        "handler_outcome": "completed",
    }
    claim = ClaimedWork(
        item_id="YOK-1813",
        status="implemented",
        item_type="issue",
        required_path="usher",
    )

    result = decide_resume_action(
        _make_offer(), _make_frontier(last_step), claim, _SESSION_ID, None,
    )

    assert result.action is ActionKind.RESUME
    assert result.chainable is True
    assert result.context.get("escalate_reason") is None


def test_genuinely_stuck_returns_escalate() -> None:
    """Refining-idea handler returned with the item still at refining-idea.

    Same item, same path, same status before and after — the handler
    completed without making progress. The detector must still fire
    ESCALATE for this shape.
    """
    last_step = {
        "action": "resume",
        "item_id": "YOK-9001",
        "task_num": None,
        "pre_status": "refining-idea",
        "status": "refining-idea",
        "required_path": "refine",
        "handler_outcome": "completed",
    }
    claim = ClaimedWork(
        item_id="YOK-9001",
        status="refining-idea",
        item_type="issue",
        required_path="refine",
    )

    result = decide_resume_action(
        _make_offer(), _make_frontier(last_step), claim, _SESSION_ID, None,
    )

    assert result.action is ActionKind.ESCALATE
    assert result.chainable is False
    assert result.context.get("escalate_reason") == "resume_no_progress"


def test_backfill_missing_pre_status_falls_back_to_same_state() -> None:
    """Older in-flight checkpoint without pre_status uses legacy heuristic.

    When ``pre_status`` is missing from the checkpoint, the detector
    falls back to the original ``same_state = (status_match OR
    path_match)`` heuristic so previously-deployed sessions are not
    silently rerouted. This fixture matches status but not path; the
    legacy OR-branch still fires ESCALATE.
    """
    last_step = {
        "action": "resume",
        "item_id": "YOK-9002",
        "task_num": None,
        # No pre_status — older session, pre-patch checkpoint.
        "status": "implemented",
        "required_path": "polish",
        "handler_outcome": "completed",
    }
    claim = ClaimedWork(
        item_id="YOK-9002",
        status="implemented",
        item_type="issue",
        required_path="usher",
    )

    result = decide_resume_action(
        _make_offer(), _make_frontier(last_step), claim, _SESSION_ID, None,
    )

    assert result.action is ActionKind.ESCALATE
    assert result.chainable is False
    assert result.context.get("escalate_reason") == "resume_no_progress"


def _seed_session(conn, session_id: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model,"
        " workspace, offered_at, last_heartbeat, offer_envelope, mode) VALUES"
        " (%s, 'DARIUS', 'anthropic', 'test-model', '/tmp/yoke', %s, %s, '{}', 'charge')",
        (session_id, now, now),
    )
    conn.commit()


def test_writer_reader_bridge_round_trip_yields_resume(test_db) -> None:
    """AC-12: end-to-end — writer persists pre_status, reader returns it,
    bridge dict surfaces it to the detector, and the detector routes RESUME.

    Mirrors the YOK-1813 chain step 3 shape: prior chain step polish handler
    advanced the item ``polishing-implementation → implemented`` and wrote a
    checkpoint with ``--pre-status polishing-implementation --status
    implemented``. The next session-offer dispatches ``usher`` against the
    same ``implemented`` status — the legacy same_state heuristic would have
    fired ESCALATE on the status match; the patched detector reads
    ``pre_status`` from the bridge-shaped ``last_completed_step`` dict and
    routes RESUME because progress was made.

    Both bridges (subprocess path in ``service_client_sessions_offer.py``
    and HTTP route path in ``routes/sessions_offer.py``) construct the
    ``last_step`` dict with identical keys via ``checkpoint.get("...")``.
    This test exercises that shape against a real schema-loaded DB so a
    silent drift in either bridge (a missing ``pre_status`` mapping) would
    cause the assertion below to fail.
    """
    session_id = "ac12-e2e-session"
    _seed_session(test_db, session_id)

    update_chain_checkpoint(
        test_db,
        session_id,
        step=2,
        action="resume",
        chainable=True,
        handler_outcome="completed",
        item_id="YOK-1813",
        status="implemented",
        required_path="polish",
        pre_status="polishing-implementation",
    )

    persisted = read_chain_checkpoint(test_db, session_id)
    assert persisted is not None
    assert persisted.get("pre_status") == "polishing-implementation"
    assert persisted.get("status") == "implemented"

    last_step = {
        "action": persisted.get("action"),
        "item_id": persisted.get("item_id"),
        "task_num": persisted.get("task_num"),
        "status": persisted.get("status"),
        "required_path": persisted.get("required_path"),
        "handler_outcome": persisted.get("handler_outcome"),
        "pre_status": persisted.get("pre_status"),
    }
    assert last_step["pre_status"] == "polishing-implementation"

    claim = ClaimedWork(
        item_id="YOK-1813",
        status="implemented",
        item_type="issue",
        required_path="usher",
    )

    result = decide_resume_action(
        _make_offer(step=3),
        FrontierState(last_completed_step=last_step),
        claim,
        session_id,
        None,
    )

    assert result.action is ActionKind.RESUME
    assert result.chainable is True
    assert result.context.get("escalate_reason") is None


def test_different_item_on_prior_step_returns_resume() -> None:
    """Sanity case — same_work=False because item_ids differ.

    Prior step worked on YOK-9100; current offer claims YOK-9101. The
    detector's ``same_work`` predicate is False, so it short-circuits and
    routes RESUME regardless of any other shape.
    """
    last_step = {
        "action": "resume",
        "item_id": "YOK-9100",
        "task_num": None,
        "pre_status": "implementing",
        "status": "implementing",
        "required_path": "advance",
        "handler_outcome": "completed",
    }
    claim = ClaimedWork(
        item_id="YOK-9101",
        status="implementing",
        item_type="issue",
        required_path="advance",
    )

    result = decide_resume_action(
        _make_offer(), _make_frontier(last_step), claim, _SESSION_ID, None,
    )

    assert result.action is ActionKind.RESUME
    assert result.chainable is True
    assert result.context.get("escalate_reason") is None
