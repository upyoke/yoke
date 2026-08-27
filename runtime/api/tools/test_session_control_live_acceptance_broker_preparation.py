"""Dedicated broker preparation recovers a busy acceptance machine."""

from __future__ import annotations

from typing import Any

from runtime.api.tools.session_control_live_acceptance_broker_binding import (
    preview_document,
)
from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    BrokerBinding,
)
from runtime.api.tools.session_control_live_acceptance_broker_preparation import (
    resolve_or_prepare_broker_binding,
)
from runtime.api.tools.session_control_live_acceptance_protocol import (
    RECEIPT_ONLY_PROTOCOL,
)


PROJECT = "yoke"
SURFACE = "codex-cli"
VERSION = "0.150.0-alpha.8"
MACHINE = "machine-one"


def _row(session_id: str, *, claims: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "project": PROJECT,
        "executor_surface": SURFACE,
        "executor_version": VERSION,
        "machine_id": MACHINE,
        "mode": "wait",
        "claims": claims,
        "current_item": None,
        "liveness": "active",
        "terminated_at": None,
        "messageability": {"hook_injection": True},
    }


class _RecoveryClient:
    def __init__(self) -> None:
        self.rows = {
            "busy-target": _row("busy-target", claims=[{"target": "YOK-2540"}]),
            "busy-peer": _row("busy-peer", claims=[{"target": "YOK-2473"}]),
        }
        self.create_calls: list[tuple[list[str], str]] = []

    def call(self, args: list[str], *, stdin: str | None = None) -> dict[str, Any]:
        if args[:2] == ["sessions", "list"]:
            if "--session" in args:
                selected = self.rows.get(args[args.index("--session") + 1])
                return {"rows": [selected] if selected is not None else []}
            return {"rows": list(self.rows.values())}
        if args[:2] == ["sessions", "create"] and "--preview" in args:
            return {
                "launchable": True,
                "selected_relay": {"version": VERSION},
            }
        if args[:2] == ["sessions", "create"]:
            assert stdin is not None
            key = args[args.index("--idempotency-key") + 1]
            role = key.rsplit("broker-", 1)[1]
            self.create_calls.append((list(args), stdin))
            return {
                "launch": {
                    "launch_id": f"launch-{role}",
                    "state": "queued",
                    "requested_surface": SURFACE,
                },
                "deduplicated": False,
            }
        if args[:3] == ["session-control", "launch", "get"]:
            role = args[3].removeprefix("launch-")
            session_id = f"dedicated-{role}"
            self.rows[session_id] = _row(session_id, claims=[])
            return {
                "launch": {
                    "launch_id": args[3],
                    "state": "succeeded",
                    "result_code": "registered_and_injected",
                    "requested_surface": SURFACE,
                    "registered_session_id": session_id,
                    "native_session_id": session_id,
                }
            }
        raise AssertionError(f"unexpected call: {args!r}")


def test_preview_without_preparation_remains_read_only() -> None:
    client = _RecoveryClient()
    decision = resolve_or_prepare_broker_binding(
        client,
        project=PROJECT,
        surface=SURFACE,
        binding=BrokerBinding("busy-target", MACHINE, "busy-peer"),
        expected_version=VERSION,
        run_id="fleet-live-acceptance-20260827-14",
        prepare=False,
    )

    assert decision.status == "not_ready"
    assert client.create_calls == []


def test_preparation_launches_itemless_pair_then_repreviews_ready() -> None:
    client = _RecoveryClient()
    original = BrokerBinding("busy-target", MACHINE, "busy-peer")
    decision = resolve_or_prepare_broker_binding(
        client,
        project=PROJECT,
        surface=SURFACE,
        binding=original,
        expected_version=VERSION,
        run_id="fleet-live-acceptance-20260827-14",
        prepare=True,
        timeout=10,
        poll=1,
        sleep=lambda _seconds: None,
        monotonic=lambda: 0,
    )

    assert decision.status == "ready"
    assert decision.binding == BrokerBinding(
        "dedicated-target", MACHINE, "dedicated-peer"
    )
    report = preview_document(
        run_id="fleet-live-acceptance-20260827-14",
        release_sha="a" * 40,
        project=PROJECT,
        cells=[{"session_id": decision.binding.target_session_id}],
        decision=decision,
    )
    assert report["status"] == "ready"
    assert len(client.create_calls) == 2
    keys = {
        args[args.index("--idempotency-key") + 1]
        for args, _stdin in client.create_calls
    }
    assert len(keys) == 2
    assert all(
        args[args.index("--surface") + 1] == SURFACE for args, _ in client.create_calls
    )
    assert all(
        args[args.index("--machine") + 1] == MACHINE for args, _ in client.create_calls
    )
    assert all(RECEIPT_ONLY_PROTOCOL in stdin for _args, stdin in client.create_calls)
    assert all("YOK-" not in stdin for _args, stdin in client.create_calls)

    repeated = resolve_or_prepare_broker_binding(
        client,
        project=PROJECT,
        surface=SURFACE,
        binding=original,
        expected_version=VERSION,
        run_id="fleet-live-acceptance-20260827-14",
        prepare=True,
    )
    assert repeated.status == "ready"
    assert len(client.create_calls) == 2
