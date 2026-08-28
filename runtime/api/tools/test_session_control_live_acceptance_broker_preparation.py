"""Dedicated broker preparation recovers a busy acceptance machine."""

from __future__ import annotations

from typing import Any

from runtime.api.tools.session_control_live_acceptance_broker_binding import (
    preview_document,
)
from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    NO_CLAIM_FREE_PAIR_CODE,
    PREPARED_SESSIONS_ENDED_CODE,
    BrokerBinding,
)
from runtime.api.tools.session_control_live_acceptance_broker_preparation import (
    BROKER_KEEPALIVE_SECONDS,
    resolve_or_prepare_broker_binding,
)
from runtime.api.tools.session_control_live_acceptance_protocol import (
    RECEIPT_ONLY_PROTOCOL,
)


PROJECT = "yoke"
SURFACE = "codex-cli"
VERSION = "0.150.0-alpha.8"
MACHINE = "machine-one"
RUN_ID = "fleet-live-acceptance-20260827-14"


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
    """A machine whose idle cleanup ends any registered session nothing holds.

    That is the live behavior a prepared broker has to survive: the session
    registers, its receipt-only turn ends, and the harness stop hook reaps it
    because it holds no claim. Here the reap is applied at the roster read, so
    a preparation that never takes the hold sees exactly what the live run saw.
    """

    #: When False the hold is accepted and recorded but does not actually keep
    #: the session, standing in for a hold that reported success and did not
    #: land.
    keepalive_prevents_reap = True

    def __init__(self) -> None:
        self.rows = {
            "busy-target": _row("busy-target", claims=[{"target": "YOK-2540"}]),
            "busy-peer": _row("busy-peer", claims=[{"target": "YOK-2473"}]),
        }
        self.create_calls: list[tuple[list[str], str]] = []
        self.keepalive_calls: list[list[str]] = []
        self.held: set[str] = set()

    def _visible(self, session_id: str) -> dict[str, Any] | None:
        row = self.rows.get(session_id)
        if row is None:
            return None
        reaped = session_id.startswith("dedicated-") and not (
            self.keepalive_prevents_reap and session_id in self.held
        )
        if reaped:
            return {**row, "liveness": "ended"}
        return row

    def call(self, args: list[str], *, stdin: str | None = None) -> dict[str, Any]:
        if args[:2] == ["sessions", "list"]:
            if "--session" in args:
                selected = self._visible(args[args.index("--session") + 1])
                return {"rows": [selected] if selected is not None else []}
            return {
                "rows": [
                    row
                    for row in (self._visible(key) for key in self.rows)
                    if row is not None and row["liveness"] == "active"
                ]
            }
        if args[:3] == ["sessions", "keepalive", "hold"]:
            self.keepalive_calls.append(list(args))
            self.held.add(args[3])
            return {"session_id": args[3], "held": True}
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


class _UnheldClient(_RecoveryClient):
    keepalive_prevents_reap = False


def _prepare(client: _RecoveryClient, *, prepare: bool = True):
    return resolve_or_prepare_broker_binding(
        client,
        project=PROJECT,
        surface=SURFACE,
        binding=BrokerBinding("busy-target", MACHINE, "busy-peer"),
        expected_version=VERSION,
        run_id=RUN_ID,
        prepare=prepare,
        timeout=10,
        poll=1,
        sleep=lambda _seconds: None,
        monotonic=lambda: 0,
    )


def test_preview_without_preparation_remains_read_only() -> None:
    client = _RecoveryClient()
    decision = _prepare(client, prepare=False)

    assert decision.status == "not_ready"
    assert decision.failure_code == NO_CLAIM_FREE_PAIR_CODE
    assert client.create_calls == []
    assert client.keepalive_calls == []


def test_preparation_launches_itemless_pair_then_repreviews_ready() -> None:
    client = _RecoveryClient()
    decision = _prepare(client)

    assert decision.status == "ready"
    assert decision.binding == BrokerBinding(
        "dedicated-target", MACHINE, "dedicated-peer"
    )
    report = preview_document(
        run_id=RUN_ID,
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

    repeated = _prepare(client)
    assert repeated.status == "ready"
    assert len(client.create_calls) == 2


def test_preparation_holds_each_prepared_session_alive_before_repreview() -> None:
    client = _RecoveryClient()
    decision = _prepare(client)

    assert decision.status == "ready"
    assert client.held == {"dedicated-target", "dedicated-peer"}
    assert [args[3] for args in client.keepalive_calls] == [
        "dedicated-target",
        "dedicated-peer",
    ]
    for args in client.keepalive_calls:
        assert args[args.index("--seconds") + 1] == str(BROKER_KEEPALIVE_SECONDS)
        assert RUN_ID in args[args.index("--reason") + 1]


def test_ended_prepared_pair_reports_its_own_failure_code() -> None:
    client = _UnheldClient()
    decision = _prepare(client)

    assert decision.status == "not_ready"
    assert decision.failure_code == PREPARED_SESSIONS_ENDED_CODE
    assert decision.failure_code != NO_CLAIM_FREE_PAIR_CODE
    assert "dedicated-target" in decision.recovery
    assert "dedicated-peer" in decision.recovery
    assert "keepalive hold" in decision.recovery
