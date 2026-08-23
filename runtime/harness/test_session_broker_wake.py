"""Broker hook rendering, settlement, and forced relay execution tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from yoke_core.hooks import session_broker_wake
from yoke_core.hooks.decision_render import render_codex_decision
from yoke_core.hooks.session_broker_wake_port import BrokerWakeLease
from yoke_core.hooks.types import HookContext, HookDecision, Outcome
from yoke_harness import session_relay
from yoke_harness.session_relay_inventory import RelayInventory
from yoke_harness.session_relay_runtime import RelayAdapterResult


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


@dataclass
class FakePort:
    leases: list[tuple[str, str]] = field(default_factory=list)
    completed: list[tuple[str, bool, str]] = field(default_factory=list)

    def lease_for_hook(
        self, *, broker_session_id: str, hook_event: str
    ) -> BrokerWakeLease | None:
        self.leases.append((broker_session_id, hook_event))
        return BrokerWakeLease(
            attempt_id="attempt-1",
            lease_id="lease-1",
            command="yoke relay serve-once --broker",
        )

    def complete_hook_lease(
        self, *, lease_id: str, delivered: bool, result: str
    ) -> None:
        self.completed.append((lease_id, delivered, result))


def _context(event_name: str = "PreToolUse") -> HookContext:
    return HookContext(
        event_name=event_name,
        executor_family="codex",
        executor_surface="codex-desktop",
        payload={},
        session_id="broker-a",
    )


def test_hook_renders_only_the_one_hop_command_and_settles_after_output(
    monkeypatch,
) -> None:
    port = FakePort()
    monkeypatch.setattr(session_broker_wake, "_broker_port", lambda: port)

    decision = session_broker_wake.evaluate(_context())
    rendered, code = render_codex_decision([decision], "PreToolUse")
    session_broker_wake.settle_after_render(
        [decision], rendered_text=rendered, denied=False, port=port
    )

    assert code == 0
    assert "yoke relay serve-once --broker" in rendered
    assert "Do not forward or broker" in rendered
    assert "message body" in rendered
    assert "target_session_id" not in rendered
    assert port.leases == [("broker-a", "PreToolUse")]
    assert port.completed == [("lease-1", True, "injected")]


def test_stop_event_never_creates_a_broker_job(monkeypatch) -> None:
    port = FakePort()
    monkeypatch.setattr(session_broker_wake, "_broker_port", lambda: port)

    decision = session_broker_wake.evaluate(_context("Stop"))

    assert decision.outcome is Outcome.NOOP
    assert port.leases == []


def test_subagent_hook_never_creates_a_broker_job(monkeypatch) -> None:
    port = FakePort()
    monkeypatch.setattr(session_broker_wake, "_broker_port", lambda: port)
    context = _context()
    context = HookContext(
        event_name=context.event_name,
        executor_family=context.executor_family,
        executor_surface=context.executor_surface,
        payload={"agent_type": "yoke-engineer"},
        session_id=context.session_id,
    )

    decision = session_broker_wake.evaluate(context)

    assert decision.outcome is Outcome.NOOP
    assert port.leases == []


def test_sibling_denial_reports_dropped_broker_instruction(monkeypatch) -> None:
    port = FakePort()
    monkeypatch.setattr(session_broker_wake, "_broker_port", lambda: port)
    broker = session_broker_wake.evaluate(_context())
    denial = HookDecision(
        outcome=Outcome.DENY,
        message="guard denied the tool call",
        block=True,
    )
    rendered, _code = render_codex_decision([broker, denial], "PreToolUse")

    session_broker_wake.settle_after_render(
        [broker, denial], rendered_text=rendered, denied=True, port=port
    )

    assert "YOKE_BROKER_WAKE_LEASE" not in rendered
    assert port.completed == [("lease-1", False, "dropped_by_sibling_denial")]


def _inventory() -> RelayInventory:
    return RelayInventory(
        relay_id=f"machine:{MACHINE_ID}",
        machine_id=MACHINE_ID,
        hostname="broker-host",
        relay_version="0.1.1",
        project_ids=(1,),
        surface_versions={"codex-cli": "0.148.0a15"},
    )


def test_broker_relay_bypasses_backoff_and_claims_only_reserved_work(
    monkeypatch, tmp_path: Path
) -> None:
    calls = []
    cadence_writes = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            result={"state": "active", "next_poll_seconds": 60, "job": None},
        )

    monkeypatch.setattr(session_relay, "poll_is_due", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        session_relay,
        "record_next_poll",
        lambda *_args, **kwargs: cadence_writes.append(kwargs),
    )
    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=_inventory,
        dispatcher=dispatch,
        runner=lambda _job: RelayAdapterResult("accepted"),
        broker_only=True,
    )

    assert outcome.state == "active"
    payload = calls[0]["payload"]
    assert payload["broker_only"] is True
    assert payload["wait_seconds"] == 0
    assert cadence_writes == []
