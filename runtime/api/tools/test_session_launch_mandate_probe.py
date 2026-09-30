"""The mandate acknowledgement probe ends the session it launched."""

from __future__ import annotations

from typing import Any, Sequence

import pytest

from runtime.api.tools import session_launch_mandate_probe as probe


LAUNCH_ID = "launch-1"
SESSION = "session-1"
MESSAGE = "message-1"


class FakeClient:
    def __init__(self, launches: list[dict[str, Any]], *, recipients=None) -> None:
        self.launches = list(launches)
        self.recipients = recipients
        self.calls: list[list[str]] = []

    def call(self, args: Sequence[str], *, stdin: str | None = None) -> dict[str, Any]:
        args = list(args)
        self.calls.append(args)
        head = args[:3]
        if head == ["session-control", "launch", "create"]:
            return {"launch": {"launch_id": LAUNCH_ID}}
        if head == ["session-control", "launch", "get"]:
            launch = (
                self.launches.pop(0) if len(self.launches) > 1 else self.launches[0]
            )
            return {"launch": launch}
        if args[:2] == ["messages", "get"]:
            return {"message": {"recipients": self.recipients or []}}
        if args[:2] == ["sessions", "terminate"]:
            return {}
        if head == ["session-control", "launch", "cancel"]:
            return {}
        raise AssertionError(f"unexpected call {args}")

    def terminated(self) -> list[str]:
        return [call[2] for call in self.calls if call[:2] == ["sessions", "terminate"]]


def _succeeded(result_code: str = "registered_and_acknowledged") -> dict[str, Any]:
    return {
        "state": "succeeded",
        "result_code": result_code,
        "message_id": MESSAGE,
        "registered_session_id": SESSION,
        "native_session_id": SESSION,
    }


ACKNOWLEDGED = [
    {"session_id": SESSION, "state": "acknowledged", "acknowledged_at": "now"}
]


def _run(client: FakeClient) -> str:
    return probe.run_live_probe(
        client,
        project="buzz",
        surface="codex-cli",
        machine="machine-1",
        model="model-1",
        run_id="run-1",
        member="ITEM-1",
        timeout=30,
        poll=1,
        sleep=lambda _seconds: None,
        monotonic=iter(range(1000)).__next__,
    )


def test_a_passing_verdict_ends_the_launched_session() -> None:
    client = FakeClient([_succeeded()], recipients=ACKNOWLEDGED)

    summary = _run(client)

    assert "acknowledged exact mandate message-1" in summary
    assert summary.endswith("launched session ended")
    assert client.terminated() == [SESSION]


def test_a_failing_verdict_still_ends_the_launched_session() -> None:
    client = FakeClient([_succeeded(result_code="registered")], recipients=ACKNOWLEDGED)

    with pytest.raises(probe.ProbeFailure) as failure:
        _run(client)

    assert failure.value.code == "launch_success_without_acknowledgement"
    assert client.terminated() == [SESSION]


def test_a_launch_that_never_registered_is_cancelled_instead() -> None:
    client = FakeClient([{"state": "launching"}])

    with pytest.raises(probe.ProbeFailure) as failure:
        _run(client)

    assert failure.value.code == "launch_acknowledgement_timeout"
    assert client.terminated() == []
    assert ["session-control", "launch", "cancel", LAUNCH_ID] in client.calls


def test_a_session_the_probe_cannot_end_fails_a_passing_case() -> None:
    client = FakeClient([_succeeded()], recipients=ACKNOWLEDGED)
    original = client.call

    def refuse_terminate(args, *, stdin=None):
        if list(args[:2]) == ["sessions", "terminate"]:
            raise probe.ProbeFailure("registered_command_refused", "denied")
        return original(args, stdin=stdin)

    client.call = refuse_terminate  # type: ignore[method-assign]

    with pytest.raises(probe.ProbeFailure) as failure:
        _run(client)

    assert failure.value.code == "launched_session_not_ended"
    assert "yoke sessions terminate" in failure.value.detail


def test_before_deployment_only_the_route_and_bootstrap_are_proven(capsys) -> None:
    class RouteOnly(FakeClient):
        def call(self, args, *, stdin=None):
            self.calls.append(list(args))
            return {"launchable": True, "selected_relay": {"machine_id": "machine-1"}}

    client = RouteOnly([])

    code = probe.main(
        [
            "--project",
            "buzz",
            "--surface",
            "codex-cli",
            "--machine",
            "machine-1",
            "--model",
            "model-1",
        ],
        client=client,
        environ={},
    )

    assert code == 0
    assert [call[:3] for call in client.calls] == [
        ["session-control", "launch", "preview"]
    ]
    assert "candidate bootstrap names exact receipt" in capsys.readouterr().out
