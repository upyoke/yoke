"""Dispatch-time freshness checks for charge and resume routing."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from yoke_core.domain.session_contract import (
    ActionKind, ClaimedWork, FrontierState, SessionOffer,
)
from yoke_core.domain.session_decision_charge import decide_charge_action
from yoke_core.domain.session_decision_freshness import (
    FreshnessOutcome, evaluate_freshness,
)
from yoke_core.domain.session_decision_resume import decide_resume_action
from runtime.api.fixtures.backlog_inserts import insert_item

_SESSION_ID = "freshness-test-session-001"
_EMITTED_EVENTS: list = []


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_session(conn, session_id: str = _SESSION_ID) -> None:
    now = _iso_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model,"
        " workspace, offered_at, last_heartbeat, offer_envelope, mode) VALUES"
        " (%s, 'DARIUS', 'anthropic', 'test-model', '/tmp/yoke', %s, %s, '{}', 'charge')",
        (session_id, now, now),
    )
    conn.commit()


def _insert_claim(conn, *, item_id: int, session_id: str = _SESSION_ID) -> int:
    now = _iso_now()
    cursor = conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type,"
        " claimed_at, last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', %s, %s) RETURNING id",
        (session_id, item_id, now, now),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.commit()
    return int(row[0])


def _make_offer(*, session_id=_SESSION_ID, supported_paths=None, step=1,
                execution_lane="DARIUS") -> SessionOffer:
    return SessionOffer(
        session_id=session_id, executor="DARIUS", provider="anthropic",
        model="test-model", workspace="/tmp/yoke",
        execution_lane=execution_lane, step=step,
        supported_paths=supported_paths or [],
    )


def _chain_skip_memory(conn, session_id: str = _SESSION_ID) -> list:
    row = conn.execute(
        "SELECT offer_envelope FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if not row or not row[0]:
        return []
    return json.loads(row[0]).get("chain_skip_memory", [])


def _event_count(conn, *, event_name: str, session_id: str = _SESSION_ID) -> int:
    return sum(
        1 for e in _EMITTED_EVENTS
        if e["event_name"] == event_name and e.get("session_id") == session_id
    )


def _active_claim_count(conn, item_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM work_claims WHERE item_id = %s AND released_at IS NULL",
        (item_id,),
    ).fetchone()[0]


def _eval(test_db, *, item_id, expected_status="refined-idea",
          expected_next_step="advance", supported_paths=("advance",),
          scheduler_context=None, lane_allowed_paths=None):
    return evaluate_freshness(
        item_id=str(item_id),
        expected_status=expected_status,
        expected_next_step=expected_next_step,
        scheduler_context=scheduler_context
        or {"status": expected_status, "next_step": expected_next_step},
        supported_paths=list(supported_paths),
        execution_lane="DARIUS",
        lane_allowed_paths=lane_allowed_paths,
        session_id=_SESSION_ID,
        chain_step=1,
        conn_override=test_db,
    )


def _charge_frontier(item_id, *, status="refined-idea", next_step="advance"):
    return FrontierState(
        runnable_items=[f"YOK-{item_id}"],
        selected_item=f"YOK-{item_id}",
        scheduler_context={
            "status": status, "next_step": next_step, "item_type": "issue",
        },
        sml_coherent=True,
    )


@pytest.fixture(autouse=True)
def _capture_emitted_events(monkeypatch):
    from yoke_core.domain import events as _events_mod
    _EMITTED_EVENTS.clear()
    monkeypatch.setattr(
        _events_mod, "emit_event",
        lambda event_name, **kw: _EMITTED_EVENTS.append({"event_name": event_name, **kw}),
    )


@pytest.fixture
def freshness_uses_test_db(test_db, monkeypatch):
    from contextlib import contextmanager
    from yoke_core.domain import session_decision_freshness as fresh_mod

    @contextmanager
    def _open_conn_test(conn_override):
        yield conn_override if conn_override is not None else test_db

    monkeypatch.setattr(fresh_mod, "_open_conn", _open_conn_test)
    return test_db


class TestEvaluateFreshness:
    def test_unchanged_when_status_matches(self, test_db):
        _insert_session(test_db)
        insert_item(test_db, id=4001, type="issue", status="refined-idea")
        v = _eval(test_db, item_id=4001)
        assert v.outcome is FreshnessOutcome.UNCHANGED
        assert v.current_status == "refined-idea"

    def test_rewrite_when_status_advances_but_serviceable(self, test_db):
        _insert_session(test_db)
        insert_item(test_db, id=4002, type="issue", status="implementing")
        v = _eval(test_db, item_id=4002, scheduler_context={
            "status": "refined-idea", "next_step": "advance",
            "title": "carried-through",
        })
        assert v.outcome is FreshnessOutcome.REWRITE
        assert v.current_status == "implementing"
        assert v.current_next_step == "advance"
        assert v.refreshed_context["next_step"] == "advance"
        assert v.refreshed_context["status"] == "implementing"
        assert v.refreshed_context["from_status"] == "refined-idea"
        assert v.refreshed_context["title"] == "carried-through"
        assert _event_count(test_db, event_name="SchedulerOfferSkipped") == 1

    def test_unserviceable_releases_claim_and_skips(self, test_db):
        _insert_session(test_db)
        insert_item(test_db, id=4003, type="issue", status="reviewed-implementation")
        _insert_claim(test_db, item_id=4003)
        assert _active_claim_count(test_db, 4003) == 1
        v = _eval(test_db, item_id=4003)
        assert v.outcome is FreshnessOutcome.UNSERVICEABLE
        assert v.current_status == "reviewed-implementation"
        assert v.current_next_step == "polish"
        memory = _chain_skip_memory(test_db)
        assert len(memory) == 1
        assert memory[0]["item_id"] == "4003"
        assert memory[0]["detection_phase"] == "dispatch"
        assert memory[0]["expected_status"] == "refined-idea"
        assert memory[0]["current_status"] == "reviewed-implementation"
        assert _event_count(test_db, event_name="SchedulerOfferSkipped") == 1
        assert _active_claim_count(test_db, 4003) == 0

    def test_failopen_when_item_missing(self, test_db):
        _insert_session(test_db)
        v = _eval(test_db, item_id=9999)
        assert v.outcome is FreshnessOutcome.UNAVAILABLE
        assert _event_count(test_db, event_name="SchedulerOfferSkipped") == 1

    def test_failopen_when_conn_unavailable(self, monkeypatch, test_db):
        _insert_session(test_db)
        from yoke_core.domain import session_decision_freshness as fresh_mod
        monkeypatch.setattr(
            fresh_mod, "connect",
            lambda: (_ for _ in ()).throw(FileNotFoundError("no DB")),
        )
        v = evaluate_freshness(
            item_id="4001", expected_status="refined-idea",
            expected_next_step="advance",
            scheduler_context={"status": "refined-idea", "next_step": "advance"},
            supported_paths=["advance"], execution_lane="DARIUS",
            lane_allowed_paths=None, session_id=_SESSION_ID, chain_step=1,
            conn_override=None,
        )
        assert v.outcome is FreshnessOutcome.UNAVAILABLE
        assert _event_count(test_db, event_name="SchedulerOfferSkipped") == 1

    def test_unserviceable_when_path_not_supported(self, test_db):
        _insert_session(test_db)
        insert_item(test_db, id=4004, type="issue", status="implementing")
        _insert_claim(test_db, item_id=4004)
        v = _eval(test_db, item_id=4004, supported_paths=("polish",))
        assert v.outcome is FreshnessOutcome.UNSERVICEABLE
        assert v.current_next_step == "advance"

    def test_failopen_when_session_not_registered(self, test_db):
        insert_item(test_db, id=4005, type="issue", status="refined-idea")
        v = _eval(test_db, item_id=4005)
        assert v.outcome is FreshnessOutcome.UNAVAILABLE


class TestResumeFreshness:
    def test_resume_branch_freshness_rewrite(self, freshness_uses_test_db):
        test_db = freshness_uses_test_db
        _insert_session(test_db)
        insert_item(test_db, id=4101, type="issue", status="reviewing-implementation")
        offer = _make_offer(supported_paths=["advance", "polish"])
        frontier = FrontierState()
        claim = ClaimedWork(
            item_id="4101",
            status="implementing",
            item_type="issue",
            required_path="advance",
        )
        result = decide_resume_action(
            offer, frontier, claim, offer.session_id, None,
        )
        assert result.action is ActionKind.RESUME
        assert result.context["status"] == "reviewing-implementation"
        assert result.context["required_path"] == "advance"
        assert result.context.get("freshness_refreshed") is True
        assert result.context.get("from_status") == "implementing"
        assert _event_count(test_db, event_name="SchedulerOfferSkipped") == 1

    def test_resume_branch_freshness_unserviceable(self, freshness_uses_test_db):
        test_db = freshness_uses_test_db
        _insert_session(test_db)
        insert_item(test_db, id=4102, type="issue", status="reviewed-implementation")
        _insert_claim(test_db, item_id=4102)
        offer = _make_offer(supported_paths=["advance"])
        frontier = FrontierState()
        claim = ClaimedWork(
            item_id="4102",
            status="implementing",
            item_type="issue",
            required_path="advance",
        )
        result = decide_resume_action(
            offer, frontier, claim, offer.session_id, None,
        )
        assert result.action is ActionKind.WAIT
        assert result.context["wait_reason"] == "stale_lifecycle_dispatch"
        assert result.context["item_id"] == "4102"
        assert _chain_skip_memory(test_db)
        assert _active_claim_count(test_db, 4102) == 0


class TestChargeIntegration:
    def test_charge_integration_rewrite(self, freshness_uses_test_db):
        test_db = freshness_uses_test_db
        _insert_session(test_db)
        insert_item(test_db, id=4201, type="issue", status="implementing")
        offer = _make_offer(supported_paths=["advance"])
        frontier = _charge_frontier(4201, status="refined-idea")
        result = decide_charge_action(offer, frontier, offer.session_id, None)
        scheduler = (result.context or {}).get("scheduler", {})
        assert result.action is ActionKind.CHARGE
        assert scheduler["status"] == "implementing"
        assert scheduler["next_step"] == "advance"
        assert scheduler.get("freshness_refreshed") is True

    def test_charge_integration_unserviceable_returns_wait(self, freshness_uses_test_db):
        test_db = freshness_uses_test_db
        _insert_session(test_db)
        insert_item(test_db, id=4202, type="issue", status="reviewed-implementation")
        _insert_claim(test_db, item_id=4202)
        offer = _make_offer(supported_paths=["advance"])
        frontier = _charge_frontier(4202, status="refined-idea")
        result = decide_charge_action(offer, frontier, offer.session_id, None)
        assert result.action is ActionKind.WAIT
        assert result.context["wait_reason"] == "stale_lifecycle_dispatch"
        assert _active_claim_count(test_db, 4202) == 0


class TestChargeDispatchContextGuard:
    def test_missing_next_step_returns_wait(self):
        offer = _make_offer(supported_paths=["advance"])
        frontier = FrontierState(
            runnable_items=["YOK-5001"], selected_item="YOK-5001",
            scheduler_context={
                "selected_item": "YOK-5001",
                "skipped_process": {"reason": "STRATEGIZE recommended but disabled"},
            },
            sml_coherent=True,
        )
        result = decide_charge_action(offer, frontier, offer.session_id, None)
        assert result.action is ActionKind.WAIT
        assert result.context["wait_reason"] == "missing_scheduler_next_step"
        assert result.context["selected_item"] == "YOK-5001"

    def test_empty_next_step_returns_wait(self):
        offer = _make_offer(supported_paths=["advance"])
        frontier = FrontierState(
            runnable_items=["YOK-5002"], selected_item="YOK-5002",
            scheduler_context={"next_step": "", "status": "refined-idea"},
            sml_coherent=True,
        )
        result = decide_charge_action(offer, frontier, offer.session_id, None)
        assert result.action is ActionKind.WAIT
        assert result.context["wait_reason"] == "missing_scheduler_next_step"

    def test_scheduler_item_mismatch_returns_wait(self):
        offer = _make_offer(supported_paths=["advance"])
        frontier = FrontierState(
            runnable_items=["YOK-5003"], selected_item="YOK-5003",
            scheduler_context={
                "selected_item": "YOK-9999", "next_step": "advance",
                "status": "refined-idea", "item_type": "issue",
            },
            sml_coherent=True,
        )
        result = decide_charge_action(offer, frontier, offer.session_id, None)
        assert result.action is ActionKind.WAIT
        assert result.context["wait_reason"] == "scheduler_context_item_mismatch"
        assert result.context["scheduler_selected_item"] == "YOK-9999"

    def test_no_scheduler_context_falls_through_to_fallback_branch(self):
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-5004"], selected_item="YOK-5004",
            scheduler_context=None, sml_coherent=True,
        )
        result = decide_charge_action(offer, frontier, offer.session_id, None)
        assert result.action is ActionKind.CHARGE
