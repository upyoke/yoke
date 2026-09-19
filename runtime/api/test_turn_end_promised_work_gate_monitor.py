"""Which Stops the promised-work gate holds, and which it lets through."""

from __future__ import annotations

from yoke_contracts.turn_end_evidence import TurnEndEvidence
from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.hooks.types import HookContext, Outcome, Next


class _Conn:
    def close(self) -> None:
        return None


def _ctx() -> HookContext:
    return HookContext(
        event_name="Stop",
        executor_family="claude",
        executor_surface="desktop",
        payload={},
        session_id="sess-1",
        remote=False,
    )


def _present() -> TurnEndEvidence:
    return TurnEndEvidence(available=True, present=True, question=False)


def _patch(
    monkeypatch,
    *,
    at_cap: bool,
    monitor_armed: bool,
    parked: bool = False,
) -> list[dict]:
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: _Conn())
    monkeypatch.setattr(gate, "session_was_relay_launched", lambda conn, sid: False)
    monkeypatch.setattr(
        gate,
        "_live_claim",
        lambda conn, sid: {"item_id": 42, "status": "implementing"},
    )
    monkeypatch.setattr(gate, "_at_reinjection_cap", lambda conn, sid, item_id: at_cap)
    monkeypatch.setattr(gate, "session_parked", lambda conn, sid: parked)
    monkeypatch.setattr(
        gate, "monitor_waiter_armed", lambda conn, sid: monitor_armed
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        gate, "_emit_deferred", lambda **kwargs: captured.append(kwargs)
    )
    return captured


def test_monitor_armed_holds_even_at_cap(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch(monkeypatch, at_cap=True, monitor_armed=True)
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.DENY
    assert decision.block is True
    assert decision.next is Next.STOP
    assert decision.message == gate.MONITOR_DIRECTIVE
    assert captured[0]["reason"] == gate.REASON_MONITOR_ARMED
    assert captured[0]["cap_reached"] is False


def test_monitor_armed_does_not_call_cap(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())

    def _cap(*_args, **_kwargs) -> bool:
        raise AssertionError("cap must not run while a Monitor waiter is armed")

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: _Conn())
    monkeypatch.setattr(gate, "session_was_relay_launched", lambda conn, sid: False)
    monkeypatch.setattr(
        gate,
        "_live_claim",
        lambda conn, sid: {"item_id": 7, "status": "implementing"},
    )
    monkeypatch.setattr(gate, "_at_reinjection_cap", _cap)
    monkeypatch.setattr(gate, "session_parked", lambda conn, sid: False)
    monkeypatch.setattr(gate, "monitor_waiter_armed", lambda conn, sid: True)
    captured: list[dict] = []
    monkeypatch.setattr(
        gate, "_emit_deferred", lambda **kwargs: captured.append(kwargs)
    )
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.DENY
    assert captured[0]["reason"] == gate.REASON_MONITOR_ARMED


def test_non_monitor_still_respects_cap(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch(monkeypatch, at_cap=True, monitor_armed=False)
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.ALLOW
    assert captured[0]["reason"] == gate.REASON_CAP_REACHED


def test_a_parked_session_may_end_its_turn(monkeypatch) -> None:
    """Parking is the declaration that going quiet is the intended state.

    Holding it anyway is the loop the gate must not create: blocked Stop,
    re-arm, blocked Stop, with nothing the directive could accomplish.
    """
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch(
        monkeypatch, at_cap=False, monitor_armed=True, parked=True
    )
    decision = gate.evaluate(_ctx())

    assert decision.outcome is Outcome.ALLOW
    assert decision.next is Next.CONTINUE
    assert captured[0]["reason"] == gate.REASON_SESSION_PARKED
    # Allowed on the declaration itself, so it never spends a hold.
    assert captured[0]["cap_reached"] is False


def test_a_parked_session_does_not_spend_the_cap(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())

    def _cap(*_args, **_kwargs) -> bool:
        raise AssertionError("a parked session is allowed before the cap")

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: _Conn())
    monkeypatch.setattr(gate, "session_was_relay_launched", lambda conn, sid: False)
    monkeypatch.setattr(
        gate,
        "_live_claim",
        lambda conn, sid: {"item_id": 7, "status": "implementing"},
    )
    monkeypatch.setattr(gate, "_at_reinjection_cap", _cap)
    monkeypatch.setattr(gate, "session_parked", lambda conn, sid: True)
    monkeypatch.setattr(gate, "monitor_waiter_armed", lambda conn, sid: False)
    monkeypatch.setattr(gate, "_emit_deferred", lambda **kwargs: None)

    assert gate.evaluate(_ctx()).outcome is Outcome.ALLOW
