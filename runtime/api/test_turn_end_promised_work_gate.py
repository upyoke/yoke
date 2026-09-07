"""Turn-end promised-work gate: trigger, escapes, cap, and snapshot consume."""

from __future__ import annotations

from runtime.api.turn_end_promised_work_test_support import _Conn
from yoke_contracts.turn_end_evidence import TurnEndEvidence, UNAVAILABLE
from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain.session_recovery_facts import PROMISED_WORK_HOLDS_TABLE
from yoke_core.domain.sessions_render_end_chain_pending import ChainPendingState
from yoke_core.hooks.types import HookContext, Outcome, Next


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
    monkeypatch.setattr(gate, "session_was_relay_launched", lambda conn, sid: False)
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


def test_session_end_and_subagent_stop_are_untouched() -> None:
    from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for

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
    assert captured[0]["claim"]["item_id"] == 5


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
    monkeypatch.setattr(
        "yoke_core.domain.session_recovery_facts.promised_work_holds_table_present",
        lambda conn: True,
    )
    conn = _Conn()
    gate._emit_deferred(
        conn=conn,
        session_id="sess-1",
        item_id=11,
        reason=gate.REASON_REINJECTED,
        cap_reached=False,
    )
    assert seen == ["snapshot"]
    # The hold is recorded with the decision that makes it, so the ceiling
    # survives whatever the events ledger retains.
    holds = [
        params
        for query, params in conn.statements
        if PROMISED_WORK_HOLDS_TABLE in query
    ]
    assert [params[:2] for params in holds] == [("sess-1", 11)]
    assert conn.commits == 1
    assert emitted[0]["reason"] == gate.REASON_REINJECTED
    assert emitted[0]["checkpoint_step"] == 0
    assert emitted[0].get("unfinished_work") is None
    assert emitted[0].get("severity", "INFO") == "INFO"


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
