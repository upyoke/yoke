"""Regression tests for the ``action_hint=no_work`` offer path.

Reproduces a session shape: a single runnable frontier item whose
offer-time reclaim is refused by the claim-aware activity window. Pre-fix, ``cmd_session_offer`` fell through to the schedule_result
branch, the frontier projected the stale claim as runnable, and the decision
engine returned ``action=charge`` for an item the ownership block had already
given up on. The new ``action_hint=no_work`` branch must return a non-charge
WAIT action with the live-claim ``wait_reason`` and surface the holder
session id; the same-step skip-memory filter keeps the schedule_result
branch from picking the same item if a future change re-routes through it.

Sibling of ``test_service_client_sessions_offer_charge.py``; broken out so
the original charge test file does not exceed the 350-line authored ceiling.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest  # noqa: F401  (used by capsys/monkeypatch fixtures)

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_constants import TEST_MODEL_ID


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_stale_holder_with_recent_activity(
    db_path: str,
    *,
    item_id: int,
    holder_session: str,
) -> None:
    """Seed the shape: stale heartbeats + recent HarnessToolCall.

    The scheduler reads heartbeats from ``harness_sessions`` and
    ``work_claims`` and classifies the claim as ``CLAIMED_BY_STALE`` when
    every signal is older than the stale TTL. The reclaim path
    (``classify_reclaimable``) additionally consults
    ``harness_sessions.last_tool_call_at``; one fresh tool-call stamp is
    enough to flip the classification to ``REASON_FRESH`` so the offer
    refuses to steal the claim. ``claim_work`` then fails with
    ``ALREADY_CLAIMED`` and the offer records a ``live_claim_conflict``
    skip.
    """
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=2)
    conn = connect_test_db(db_path)
    p = _p(conn)
    try:
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, project_id, workspace,
                offered_at, last_heartbeat)
               VALUES ({p}, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}', 1,
                       '/tmp', {p}, {p})""",
            (holder_session, _iso(old), _iso(old)),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type,
                claimed_at, last_heartbeat)
               VALUES ({p}, 'item', {p}, 'exclusive', {p}, {p})""".format(p=p),
            (holder_session, item_id, _iso(old), _iso(old)),
        )
        conn.execute(
            """UPDATE harness_sessions
               SET last_tool_call_at = {p},
                   tool_call_count = COALESCE(tool_call_count, 0) + 1
               WHERE session_id = {p}""".format(p=p),
            (_iso(now), holder_session),
        )
        conn.commit()
    finally:
        conn.close()


def _holder_event_count(db_path: str, session_id: str, event_name: str) -> int:
    conn = connect_test_db(db_path)
    p = _p(conn)
    try:
        cur = conn.execute(
            f"SELECT COUNT(*) FROM events WHERE session_id = {p} AND event_name = {p}",
            (session_id, event_name),
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


class TestSessionOfferNoWork:
    """Offer must not return charge for live-claim-blocked items."""

    def test_action_hint_no_work_returns_wait_with_holder(
        self, session_offer_db
    ):
        """AC-1, AC-2, AC-5, AC-12: live-claim conflict → non-charge, no charge.

        With events-backed liveness, ``scheduler_claims._evaluate_claim_states`` routes
        through :func:`session_reclaim_activity.latest_activity`, so a
        holder whose heartbeat is stale but whose tool events are fresh
        is classified directly as ``CLAIMED_BY_OTHER_LIVE`` — filtering
        the item out of ``runnable_items`` rather than letting the offer
        try-and-fail through the reclaim classifier. The terminal action
        is now non-charge (``WAIT`` when no other branches fire, or
        ``ESCALATE`` when the FEED process gate is disabled by config);
        AC-1 (the load-bearing invariant) is preserved in both shapes.
        """
        holder = "yok-1628-holder"
        _seed_stale_holder_with_recent_activity(
            session_offer_db["db_path"],
            item_id=10,  # fixture-seeded runnable refined-idea item
            holder_session=holder,
        )

        sid = "yok-1628-offerer"
        _pre_register_session(
            session_offer_db["db_path"], sid, workspace=session_offer_db["tmp_dir"],
        )
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)

        # Never charge for the live-claim-blocked item.
        assert data["action"] != "charge", data
        assert data["action"] in ("wait", "escalate"), data

        ctx = data.get("context") or {}
        # Dispatch-bearing fields are absent so /yoke do has nothing
        # to dispatch from regardless of the terminal action shape.
        assert not ctx.get("selected_item")
        assert not ctx.get("scheduler")
        assert not ctx.get("scheduler_context")
        assert not data.get("chainable")

    def test_skip_memory_filter_is_targeted_not_blanket(self):
        """AC-3 / AC-6: skip-memory filter drops only named ids, keeps the rest.

        Builds a SchedulerResult with two assignable items and asserts the
        filter only removes the explicitly skipped one. This covers the
        defense-in-depth path inside the schedule_result branch — even if a
        future change re-routes ``no_work`` through that branch, the
        unblocked candidate must still surface as runnable so ``charge``
        keeps working when the frontier has multiple candidates.
        """
        from yoke_core.domain.scheduler_types import (
            ClaimState,
            NextStep,
            ScheduledStep,
            SchedulerResult,
            SMLState,
        )
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        steps = [
            ScheduledStep(
                item_id="YOK-10",
                item_type="issue",
                status="refined-idea",
                title="blocked",
                priority="high",
                next_step=NextStep.ADVANCE,
                rank=0,
                claim_state=ClaimState.CLAIMED_BY_STALE,
            ),
            ScheduledStep(
                item_id="YOK-13",
                item_type="issue",
                status="refined-idea",
                title="unblocked",
                priority="high",
                next_step=NextStep.ADVANCE,
                rank=1,
                claim_state=ClaimState.UNCLAIMED,
            ),
        ]
        schedule = SchedulerResult(
            project_scope=["yoke"],
            sml_state=SMLState(coherent=True),
            ranked_steps=steps,
            selected_step=steps[0],
        )

        # No skip filter: both runnable, selected is the higher-priority item.
        baseline = build_frontier_state_from_schedule(schedule)
        assert baseline.runnable_items == ["YOK-10", "YOK-13"]
        assert baseline.selected_item == "YOK-10"

        # With the selected id in skip memory: it is dropped from
        # runnable_items, and the next-ranked item is promoted into
        # selected_item / scheduler_context so /yoke do charge dispatch
        # keeps working when the scheduler's top pick is filtered.
        filtered = build_frontier_state_from_schedule(
            schedule, skip_memory_item_ids={"YOK-10"},
        )
        assert filtered.runnable_items == ["YOK-13"]
        assert filtered.selected_item == "YOK-13"
        assert filtered.scheduler_context["next_step"] == "advance"
        assert filtered.scheduler_context["item_type"] == "issue"


class TestNoWorkWaitContextHelper:
    """Direct unit tests for the wait-context helper."""

    def test_live_claim_only_uses_specific_wait_reason(self):
        from yoke_core.domain.sessions_offer_revalidation import (
            build_no_work_wait_context,
        )

        skip_memory = [
            {
                "item_id": "YOK-1627",
                "skip_reason": "live_claim_conflict",
                "chain_step": 1,
                "claim_holder_session_id": "holder-a",
                "claim_id": 1483,
            },
        ]
        ctx = build_no_work_wait_context(
            terminal_reason="all_candidates_blocked",
            skip_memory=skip_memory,
            chain_step=1,
        )
        assert ctx["wait_reason"] == "all_runnable_items_blocked_by_live_claims"
        assert ctx["terminal_reason"] == "all_candidates_blocked"
        assert ctx["holder_session_ids"] == ["holder-a"]
        assert ctx["chain_skip_summary"][0]["skip_reason"] == "live_claim_conflict"

    def test_unknown_terminal_reason_falls_back_to_generic_wait_reason(self):
        from yoke_core.domain.sessions_offer_revalidation import (
            build_no_work_wait_context,
            map_terminal_reason_to_wait_reason,
        )

        ctx = build_no_work_wait_context(
            terminal_reason=None, skip_memory=[], chain_step=1,
        )
        assert ctx["wait_reason"] == "no_actionable_work_on_frontier"
        assert ctx["terminal_reason"] == "no_candidates"
        assert "holder_session_ids" not in ctx
        assert map_terminal_reason_to_wait_reason("unknown") == (
            "no_actionable_work_on_frontier"
        )


class TestChargeClaimInvariant:
    """Direct unit tests for validate_charge_claim_invariant."""

    def _charge_action(self, selected: str | None) -> object:
        from yoke_core.domain.session_contract import ActionKind, NextAction

        return NextAction(
            action=ActionKind.CHARGE,
            reason="test",
            chainable=True,
            correlation_id="sess-1",
            context={"selected_item": selected} if selected else {},
        )

    def test_charge_without_claim_fails(self):
        from yoke_core.api.service_client_sessions_offer_helpers import (
            validate_charge_claim_invariant,
        )

        ok, err = validate_charge_claim_invariant(
            self._charge_action("YOK-10"), None,
        )
        assert ok is False
        assert err is not None
        assert "without a backing work claim" in err

    def test_charge_with_mismatched_claim_fails(self):
        from yoke_core.api.service_client_sessions_offer_helpers import (
            validate_charge_claim_invariant,
        )

        ok, err = validate_charge_claim_invariant(
            self._charge_action("YOK-10"), {"item_id": 99},
        )
        assert ok is False
        assert err is not None
        assert "does not match" in err

    def test_charge_with_matching_claim_passes_across_id_formats(self):
        from yoke_core.api.service_client_sessions_offer_helpers import (
            validate_charge_claim_invariant,
        )

        # selected_item arrives as ``YOK-N`` from the scheduler; new_claim
        # stores the bare integer. The invariant must accept the match.
        ok, err = validate_charge_claim_invariant(
            self._charge_action("YOK-10"), {"item_id": 10},
        )
        assert ok is True
        assert err is None

    def test_non_charge_actions_pass_through(self):
        from yoke_core.domain.session_contract import ActionKind, NextAction
        from yoke_core.api.service_client_sessions_offer_helpers import (
            validate_charge_claim_invariant,
        )

        wait = NextAction(
            action=ActionKind.WAIT,
            reason="test",
            chainable=False,
            correlation_id="sess-1",
        )
        ok, err = validate_charge_claim_invariant(wait, None)
        assert ok is True
        assert err is None
