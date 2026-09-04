"""Headless Stop continuation and durable deferred-work behavior."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain.session_relay_launch_context import (
    session_was_relay_launched,
)
from yoke_core.domain.sessions_render_end_chain_pending import ChainPendingState
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


class _Conn:
    def close(self) -> None:
        return None


def test_relay_launch_context_uses_durable_session_correlation() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE session_launches (registered_session_id TEXT)")

    assert not session_was_relay_launched(conn, "interactive")
    conn.execute("INSERT INTO session_launches VALUES ('worker')")
    assert session_was_relay_launched(conn, "worker")


def test_relay_launch_context_fails_safe_against_stop_denial() -> None:
    class _BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("launch context unavailable")

    assert session_was_relay_launched(_BrokenConnection(), "worker")


def _context(executor: str, entrypoint: str) -> HookContext:
    return HookContext(
        event_name="Stop",
        executor_family=executor,
        executor_surface=entrypoint,
        payload={"entrypoint": entrypoint},
        session_id="sess-1",
        remote=True,
    )


def _patch_live_claim(
    monkeypatch,
    emitted: list[dict],
    *,
    relay_launched: bool = False,
) -> None:
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", _Conn)
    monkeypatch.setattr(
        gate,
        "_evidence_for",
        lambda _record: type("Evidence", (), {"available": True, "question": False})(),
    )
    monkeypatch.setattr(
        gate,
        "_live_claim",
        lambda _conn, _sid: {"item_id": 42, "status": "implementing"},
    )
    monkeypatch.setattr(
        gate,
        "session_was_relay_launched",
        lambda _conn, _sid: relay_launched,
    )
    monkeypatch.setattr(gate, "_emit_deferred", lambda **kw: emitted.append(kw))


@pytest.mark.parametrize(
    ("executor", "entrypoint"),
    [
        ("claude", "cli"),
        ("codex", "codex-cli"),
        ("codex", "codex-desktop"),
        ("cursor", "cursor-cli"),
    ],
)
def test_relay_worker_allows_stop_and_records_deferred_work(
    monkeypatch,
    executor: str,
    entrypoint: str,
) -> None:
    emitted: list[dict] = []
    _patch_live_claim(monkeypatch, emitted, relay_launched=True)

    decision = gate.evaluate(_context(executor, entrypoint))

    assert decision.outcome is Outcome.ALLOW
    assert emitted == [
        {
            "conn": emitted[0]["conn"],
            "session_id": "sess-1",
            "item_id": 42,
            "reason": gate.REASON_CONTINUATION_UNSUPPORTED,
            "cap_reached": False,
            "claim": {"item_id": 42, "status": "implementing"},
        }
    ]


@pytest.mark.parametrize(
    ("executor", "entrypoint"),
    [("claude", "cli"), ("codex", "codex-cli")],
)
def test_operator_opened_cli_still_denies_with_actual_check_identity(
    monkeypatch,
    executor: str,
    entrypoint: str,
) -> None:
    emitted: list[dict] = []
    _patch_live_claim(monkeypatch, emitted)
    monkeypatch.setattr(gate, "_armed_monitor_blocks_stop", lambda *_args: False)
    monkeypatch.setattr(gate, "_at_reinjection_cap", lambda *_args: False)

    decision = gate.evaluate(_context(executor, entrypoint))

    assert decision.outcome is Outcome.DENY
    assert decision.audit_fields["check_id"] == gate.CHECK_ID
    assert decision.audit_fields["denial_reason"] == gate.DIRECTIVE


def test_unsupported_continuation_event_is_warn_with_recovery(monkeypatch) -> None:
    state = ChainPendingState(False, 0, 3, False, None, None, None)
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end_chain_pending.chain_pending_state",
        lambda _conn, _sid: state,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end_chain_pending.last_released_at",
        lambda _conn, _sid: None,
    )
    emitted: list[dict] = []
    monkeypatch.setattr(
        "yoke_core.domain.scheduler_events.emit_chain_end_deferred",
        lambda **kw: emitted.append(kw),
    )

    gate._emit_deferred(
        conn=_Conn(),
        session_id="sess-1",
        item_id=42,
        reason=gate.REASON_CONTINUATION_UNSUPPORTED,
        cap_reached=False,
        claim={"item_id": 42, "status": "implementing"},
    )

    assert emitted[0]["severity"] == "WARN"
    assert emitted[0]["unfinished_work"] == gate.UNFINISHED_CLAIMED_ITEM
    assert "release the claim" in emitted[0]["recovery"]


def test_runner_carries_the_actual_denier_to_the_remote_boundary(monkeypatch) -> None:
    from yoke_core.hooks import runner

    decision = HookDecision(
        outcome=Outcome.DENY,
        message="finish the claimed work",
        next=Next.STOP,
        audit_fields={"check_id": "claimed_work_gate"},
    )
    monkeypatch.setattr(runner, "chain_for", lambda *_args: ["policy.module"])
    monkeypatch.setattr(
        runner,
        "invoke_module",
        lambda *_args, **_kwargs: (
            decision,
            "",
            None,
            ("guardrail", {"module": "policy.module"}),
        ),
    )
    monkeypatch.setattr(runner._mode_gate, "apply_mode", lambda value, *_a, **_k: value)
    monkeypatch.setattr(
        "yoke_core.hooks.run_tail.preflight_remote_registration",
        lambda **_kwargs: None,
    )
    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda _raw: {},
        decision_renderer=lambda _decisions, _event: ("denied", 2),
    )
    controls = RunControls(remote=True, flush_tail=False)

    runner.run_event(
        "PreToolUse",
        capability=capability,
        stdin_data="{}",
        controls=controls,
    )

    assert controls.denial_audit == {
        "hook": "policy.module",
        "check_id": "claimed_work_gate",
        "reason": "finish the claimed work",
    }
