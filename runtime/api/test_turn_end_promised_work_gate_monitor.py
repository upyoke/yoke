"""Monitor-armed and live-command Stop holds do not spend the promised-work cap."""

from __future__ import annotations

from yoke_contracts.turn_end_evidence import TurnEndEvidence
from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain.session_tool_call_projections import (
    LAST_COMPLETED_TOOL_COLUMN,
    OPEN_TOOL_CALL_COLUMN,
)
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


def _patch(monkeypatch, *, at_cap: bool, block_reason: str | None) -> list[dict]:
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: _Conn())
    monkeypatch.setattr(gate, "session_was_relay_launched", lambda conn, sid: False)
    monkeypatch.setattr(
        gate,
        "_live_claim",
        lambda conn, sid: {"item_id": 42, "status": "implementing"},
    )
    monkeypatch.setattr(gate, "_at_reinjection_cap", lambda conn, sid, item_id: at_cap)
    monkeypatch.setattr(
        gate, "_live_stop_block_reason", lambda conn, sid: block_reason
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        gate, "_emit_deferred", lambda **kwargs: captured.append(kwargs)
    )
    return captured


def test_monitor_armed_holds_even_at_cap(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch(monkeypatch, at_cap=True, block_reason=gate.REASON_MONITOR_ARMED)
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
    monkeypatch.setattr(
        gate, "_live_stop_block_reason", lambda conn, sid: gate.REASON_MONITOR_ARMED
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        gate, "_emit_deferred", lambda **kwargs: captured.append(kwargs)
    )
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.DENY
    assert captured[0]["reason"] == gate.REASON_MONITOR_ARMED


def test_parked_or_non_monitor_still_respects_cap(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch(monkeypatch, at_cap=True, block_reason=None)
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.ALLOW
    assert captured[0]["reason"] == gate.REASON_CAP_REACHED


def test_live_command_holds_even_at_cap(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch(
        monkeypatch, at_cap=True, block_reason=gate.REASON_LIVE_COMMAND
    )
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.DENY
    assert decision.message == gate.LIVE_COMMAND_DIRECTIVE
    assert captured[0]["reason"] == gate.REASON_LIVE_COMMAND
    assert captured[0]["cap_reached"] is False


def test_live_command_does_not_call_cap(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())

    def _cap(*_args, **_kwargs) -> bool:
        raise AssertionError("cap must not run while a local command is live")

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: _Conn())
    monkeypatch.setattr(gate, "session_was_relay_launched", lambda conn, sid: False)
    monkeypatch.setattr(
        gate,
        "_live_claim",
        lambda conn, sid: {"item_id": 7, "status": "implementing"},
    )
    monkeypatch.setattr(gate, "_at_reinjection_cap", _cap)
    monkeypatch.setattr(
        gate, "_live_stop_block_reason", lambda conn, sid: gate.REASON_LIVE_COMMAND
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        gate, "_emit_deferred", lambda **kwargs: captured.append(kwargs)
    )
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.DENY
    assert captured[0]["reason"] == gate.REASON_LIVE_COMMAND


class _Rows:
    def __init__(self, row: dict | None) -> None:
        self._row = row

    def fetchone(self) -> dict | None:
        return self._row


class _SessionConn:
    """Answers the one combined session-and-last-call read the gate makes."""

    def __init__(self, row: dict) -> None:
        self._row = row
        self.queries: list[str] = []

    def execute(self, query: str, params: tuple[object, ...]) -> _Rows:
        self.queries.append(query)
        return _Rows(self._row)


def _no_events(monkeypatch) -> None:
    """The waiter fact comes from the call rows, so events are never read."""
    monkeypatch.setattr(
        "yoke_core.domain.session_tool_call_projections.has_session_tool_calls_table",
        lambda conn: True,
    )


def test_armed_helper_skips_parked_session(monkeypatch) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn({"mode": "parked", LAST_COMPLETED_TOOL_COLUMN: "Monitor"})

    assert gate._armed_monitor_blocks_stop(conn, "sess-1") is False


def test_armed_helper_true_for_last_monitor(monkeypatch) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn({"mode": "dash", LAST_COMPLETED_TOOL_COLUMN: "Monitor"})

    assert gate._armed_monitor_blocks_stop(conn, "sess-1") is True
    assert not any("events" in query for query in conn.queries)


def test_armed_helper_false_when_the_last_call_was_something_else(
    monkeypatch,
) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn({"mode": "dash", LAST_COMPLETED_TOOL_COLUMN: "Bash"})

    assert gate._armed_monitor_blocks_stop(conn, "sess-1") is False


_LIVE_STAMP = "2026-09-15T02:30:31Z"


def test_live_open_command_blocks_stop_during_cooldown(monkeypatch) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn(
        {
            "mode": "dash",
            LAST_COMPLETED_TOOL_COLUMN: "Read",
            OPEN_TOOL_CALL_COLUMN: _LIVE_STAMP,
            "last_tool_call_at": _LIVE_STAMP,
        }
    )

    assert gate._live_stop_block_reason(conn, "sess-1") == gate.REASON_LIVE_COMMAND
    assert not any("events" in query for query in conn.queries)


def test_settled_command_does_not_block_stop(monkeypatch) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn(
        {
            "mode": "dash",
            LAST_COMPLETED_TOOL_COLUMN: "Bash",
            OPEN_TOOL_CALL_COLUMN: None,
            "last_tool_call_at": _LIVE_STAMP,
        }
    )

    assert gate._live_stop_block_reason(conn, "sess-1") is None


def test_residue_open_row_does_not_block_stop(monkeypatch) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn(
        {
            "mode": "dash",
            LAST_COMPLETED_TOOL_COLUMN: "Read",
            OPEN_TOOL_CALL_COLUMN: "2026-09-15T00:00:00Z",
            "last_tool_call_at": _LIVE_STAMP,
        }
    )

    assert gate._live_stop_block_reason(conn, "sess-1") is None


def test_parked_session_does_not_block_on_live_command(monkeypatch) -> None:
    _no_events(monkeypatch)
    conn = _SessionConn(
        {
            "mode": "parked",
            LAST_COMPLETED_TOOL_COLUMN: "Read",
            OPEN_TOOL_CALL_COLUMN: _LIVE_STAMP,
            "last_tool_call_at": _LIVE_STAMP,
        }
    )

    assert gate._live_stop_block_reason(conn, "sess-1") is None
