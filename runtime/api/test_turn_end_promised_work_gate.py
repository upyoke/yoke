"""Turn-end promised-work gate: trigger, escapes, cap, and snapshot consume."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_contracts.turn_end_evidence import TurnEndEvidence, UNAVAILABLE
from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain.sessions_render_end_chain_pending import ChainPendingState
from yoke_core.hooks.types import HookContext, Outcome, Next


class _Conn:
    def close(self) -> None:
        return None


_NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)


def _ctx(**kwargs) -> HookContext:
    payload = kwargs.pop("payload", {})
    return HookContext(
        event_name=kwargs.pop("event_name", "Stop"),
        executor_family=kwargs.pop("executor_family", "claude"),
        executor_surface="desktop",
        payload=payload,
        session_id=kwargs.pop("session_id", "sess-1"),
        remote=kwargs.pop("remote", False),
        **kwargs,
    )


def _present() -> TurnEndEvidence:
    return TurnEndEvidence(available=True, present=True, question=False)


def _question() -> TurnEndEvidence:
    return TurnEndEvidence(available=True, present=True, question=True)


def _patch_db(monkeypatch, *, claim, at_cap=False, emitted=None):
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: _Conn())
    monkeypatch.setattr(gate, "_live_claim", lambda conn, sid: claim)
    monkeypatch.setattr(
        gate,
        "_at_reinjection_cap",
        lambda conn, sid, item_id: at_cap,
    )

    captured: list[dict] = emitted if emitted is not None else []

    def _emit(**kwargs) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(gate, "_emit_deferred", _emit)
    return captured


def test_stop_chain_registers_gate_before_dispatch() -> None:
    assert ordered_pipeline_for("Stop") == [
        "yoke_core.domain.turn_end_promised_work_gate",
        "yoke_core.hooks.session_message_delivery",
        "yoke_core.hooks.session_dispatch",
    ]


def test_session_end_and_subagent_stop_are_untouched() -> None:
    assert "turn_end_promised_work_gate" not in ordered_pipeline_for("SessionEnd")
    assert "turn_end_promised_work_gate" not in ordered_pipeline_for("SubagentStop")
    decision = gate.evaluate(_ctx(event_name="SessionEnd"))
    assert decision.outcome is Outcome.NOOP


def test_hold_for_live_mid_lifecycle_claim(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    _patch_db(monkeypatch, claim={"item_id": 42, "status": "implementing"})
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.DENY
    assert decision.block is True
    assert decision.next is Next.STOP
    assert decision.message == gate.DIRECTIVE
    assert "release the claim" in gate.DIRECTIVE
    assert "stop deliberately" in gate.DIRECTIVE


def test_hold_without_chain_checkpoint(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch_db(
        monkeypatch,
        claim={"item_id": 9, "status": "refined-idea"},
    )
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.DENY
    assert captured[0]["reason"] == gate.REASON_REINJECTED
    assert captured[0]["cap_reached"] is False


def test_question_escape_allows(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _question())
    captured = _patch_db(
        monkeypatch,
        claim={"item_id": 1, "status": "implementing"},
    )
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.ALLOW
    assert captured == []


def test_terminal_and_wait_allow(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    for status in ("done", "blocked", "cancelled", "stopped", "failed"):
        captured = _patch_db(monkeypatch, claim={"item_id": 3, "status": status})
        decision = gate.evaluate(_ctx())
        assert decision.outcome is Outcome.ALLOW
        assert captured == []


def test_no_live_claim_is_unaffected(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch_db(monkeypatch, claim=None)
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.ALLOW
    assert captured == []


def test_cap_allows_and_records(monkeypatch) -> None:
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: _present())
    captured = _patch_db(
        monkeypatch,
        claim={"item_id": 5, "status": "implementing"},
        at_cap=True,
    )
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.ALLOW
    assert captured[0]["reason"] == gate.REASON_CAP_REACHED
    assert captured[0]["cap_reached"] is True


def test_recent_hold_stays_capped_without_consulting_tool_use(monkeypatch) -> None:
    assert not hasattr(gate, "_completed_tool_use_since")
    held_at = _NOW - gate.REINJECTION_COOLDOWN + timedelta(seconds=1)
    monkeypatch.setattr(
        gate,
        "_reinjection_history",
        lambda conn, sid, item_id: (held_at.isoformat(), 1),
    )

    def _unexpected_tool_lookup(*args) -> bool:
        raise AssertionError("tool use must not affect the reinjection cooldown")

    monkeypatch.setattr(
        gate,
        "_completed_tool_use_since",
        _unexpected_tool_lookup,
        raising=False,
    )
    assert gate._at_reinjection_cap(_Conn(), "sess-1", 5, now=_NOW) is True


def test_expired_cooldown_reinjects_until_ceiling(monkeypatch) -> None:
    held_at = _NOW - gate.REINJECTION_COOLDOWN
    for hold_count in (1, gate.REINJECTION_CEILING - 1):
        monkeypatch.setattr(
            gate,
            "_reinjection_history",
            lambda conn, sid, item_id, count=hold_count: (
                held_at.isoformat(),
                count,
            ),
        )
        assert gate._at_reinjection_cap(_Conn(), "sess-1", 5, now=_NOW) is False


def test_ceiling_stays_capped_regardless_of_elapsed_time(monkeypatch) -> None:
    held_at = _NOW - (gate.REINJECTION_COOLDOWN * 10)
    monkeypatch.setattr(
        gate,
        "_reinjection_history",
        lambda conn, sid, item_id: (
            held_at.isoformat(),
            gate.REINJECTION_CEILING,
        ),
    )
    assert gate._at_reinjection_cap(_Conn(), "sess-1", 5, now=_NOW) is True


def test_ceiling_is_scoped_to_the_claim_item(monkeypatch) -> None:
    held_at = _NOW - gate.REINJECTION_COOLDOWN
    histories = {
        5: (held_at.isoformat(), gate.REINJECTION_CEILING),
        6: (held_at.isoformat(), 1),
    }
    monkeypatch.setattr(
        gate,
        "_reinjection_history",
        lambda conn, sid, item_id: histories[item_id],
    )
    assert gate._at_reinjection_cap(_Conn(), "sess-1", 5, now=_NOW) is True
    assert gate._at_reinjection_cap(_Conn(), "sess-1", 6, now=_NOW) is False


def test_reinjection_history_query_filters_claim_item(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Rows:
        def fetchone(self) -> dict[str, object]:
            return {"last_hold_at": _NOW.isoformat(), "hold_count": 2}

    class _HistoryConn:
        def execute(self, query: str, params: tuple[object, ...]) -> _Rows:
            captured["query"] = query
            captured["params"] = params
            return _Rows()

    monkeypatch.setattr(
        "yoke_core.domain.db_backend.connection_is_postgres",
        lambda conn: True,
    )
    assert gate._reinjection_history(_HistoryConn(), "sess-1", 6) == (
        _NOW.isoformat(),
        2,
    )
    assert "{context,item_id}" in str(captured["query"])
    assert captured["params"] == ("sess-1", gate.REASON_REINJECTED, "6")


def test_unavailable_evidence_fails_open(monkeypatch) -> None:
    emitted: list[str] = []
    monkeypatch.setattr(gate, "_evidence_for", lambda ctx: UNAVAILABLE)
    monkeypatch.setattr(
        gate,
        "_emit_unavailable",
        lambda ctx: emitted.append(ctx.session_id or ""),
    )
    decision = gate.evaluate(_ctx())
    assert decision.outcome is Outcome.ALLOW
    assert emitted == ["sess-1"]


def test_remote_uses_payload_facts_only(monkeypatch) -> None:
    seen: list[bool] = []

    def _fake_read(path: str) -> str:
        seen.append(True)
        return path

    monkeypatch.setattr(gate, "read_transcript_tail", _fake_read)
    ctx = _ctx(
        remote=True,
        payload={
            "transcript_path": "/tmp/should-not-read.jsonl",
            "turn_end_evidence": {
                "available": True,
                "present": True,
                "question": True,
            },
        },
    )
    evidence = gate._evidence_for(ctx)
    assert evidence.question is True
    assert seen == []


def test_emit_deferred_consumes_chain_pending_state(monkeypatch) -> None:
    seen: list[str] = []
    state = ChainPendingState(
        pending=False,
        step=0,
        max_chain_steps=3,
        chainable=False,
        handler_outcome=None,
        action=None,
        item_id=None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end_chain_pending.chain_pending_state",
        lambda conn, sid: seen.append("snapshot") or state,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end_chain_pending.last_released_at",
        lambda conn, sid: None,
    )
    emitted: list[dict] = []
    monkeypatch.setattr(
        "yoke_core.domain.scheduler_events.emit_chain_end_deferred",
        lambda **kwargs: emitted.append(kwargs),
    )
    gate._emit_deferred(
        conn=_Conn(),
        session_id="sess-1",
        item_id=11,
        reason=gate.REASON_REINJECTED,
        cap_reached=False,
    )
    assert seen == ["snapshot"]
    assert emitted[0]["reason"] == gate.REASON_REINJECTED
    assert emitted[0]["checkpoint_step"] == 0


def test_remote_tail_skips_lifecycle_on_deny(monkeypatch) -> None:
    """A held Stop must not run remote session-end cleanup."""
    from types import SimpleNamespace

    from yoke_core.hooks.remote_policy import RunControls
    from yoke_core.hooks.run_tail import flush_run_tail

    lifecycle: list[str] = []
    monkeypatch.setattr(
        "yoke_core.hooks.telemetry.flush_hook_telemetry",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.hooks.remote_lifecycle.run_remote_session_lifecycle",
        lambda event_name, context: lifecycle.append(event_name),
    )
    deadline = SimpleNamespace(telemetry_allowed=lambda: True, budget_ms=1000)
    context = SimpleNamespace(
        executor_family="claude",
        session_id="sess-1",
        item_id=1,
        tool_name="",
    )
    kwargs = dict(
        event_name="Stop",
        context=context,
        chain_length=2,
        hook_wait_ms=1,
        timed_out=False,
        deadline=deadline,
        payload={},
        stdin_data="",
        controls=RunControls(remote=True),
        telem_records=[],
    )
    flush_run_tail(final_outcome="deny", **kwargs)
    assert lifecycle == []
    flush_run_tail(final_outcome="allow", **kwargs)
    assert lifecycle == ["Stop"]
