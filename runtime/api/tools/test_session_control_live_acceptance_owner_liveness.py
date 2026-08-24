"""Top-level owner liveness during bounded Fleet acceptance waits."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.tools import session_control_live_acceptance as acceptance
from runtime.api.tools.session_control_live_acceptance_client import (
    AcceptanceOwnerKeepalive,
)
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    AcceptanceMatrix,
)
from runtime.api.tools.session_control_live_acceptance_driver import (
    LiveAcceptanceDriver,
)
from runtime.api.tools.test_session_control_live_acceptance_clock import (
    AcceptanceClock,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
)


OWNER_SESSION_ID = "top-level-owner"
RELEASE_SHA = "a" * 40


class _OwnerClient(_ScenarioClient):
    def call(self, args, *, stdin: str | None = None) -> dict[str, Any]:
        argv = list(args)
        if argv == ["sessions", "touch"]:
            self.calls.append((argv, stdin))
            return {"session": {"session_id": OWNER_SESSION_ID}}
        return super().call(argv, stdin=stdin)


class _Qualification:
    def __init__(self, client: _OwnerClient) -> None:
        self.client = client
        self.open_call_counts: list[int] = []

    def open(self, _cell: AcceptanceCell, operation: str) -> str | None:
        self.open_call_counts.append(len(self.client.calls))
        return operation if operation == "message_stopped" else None

    def verify(self, _grant: str | None) -> None:
        return None


def test_long_create_wait_touches_repeatedly_and_immediately_before_grant() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.241", "create")
    client = _OwnerClient(cell)
    clock = AcceptanceClock(client.simulate_target_tool_hook)
    qualification = _Qualification(client)
    driver = LiveAcceptanceDriver(client, sleep=clock.sleep, monotonic=clock.monotonic)

    report = driver.run(
        AcceptanceMatrix("yoke", (cell,)),
        run_id="owner-liveness",
        release_sha=RELEASE_SHA,
        server_build=RELEASE_SHA,
        engine_version="0.1.1+launch.284",
        caller_session_id=OWNER_SESSION_ID,
        timeout_seconds=300,
        poll_seconds=61,
        unsupported_observation_seconds=0,
        qualification=qualification,
    )

    assert report["status"] == "passed"
    assert driver.client is client
    assert driver.sleep == clock.sleep
    touches = [call for call in client.calls if call[0] == ["sessions", "touch"]]
    assert len(touches) >= 3
    assert all(stdin is None and "--session-id" not in argv for argv, stdin in touches)
    assert len(qualification.open_call_counts) == 1
    before_open = qualification.open_call_counts[0]
    assert client.calls[before_open - 1] == (["sessions", "touch"], None)


def test_owner_touch_mismatch_fails_closed() -> None:
    class _MismatchClient:
        def call(self, _args, *, stdin=None):
            return {"session": {"session_id": "different-session"}}

    owner = AcceptanceOwnerKeepalive(
        _MismatchClient(), owner_session_id=OWNER_SESSION_ID
    )

    with pytest.raises(AcceptanceContractError) as failure:
        owner.touch()

    assert failure.value.code == "acceptance_owner_touch_mismatch"


def test_subagent_refusal_performs_no_owner_touch(
    monkeypatch, tmp_path, capsys
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: True)
    monkeypatch.setattr(
        acceptance,
        "YokeCliClient",
        lambda **_kwargs: calls.append("client-created"),
    )

    code = acceptance.main(
        [
            "--matrix",
            str(tmp_path / "unused.json"),
            "--run-id",
            "subagent-refusal",
            "--release-sha",
            RELEASE_SHA,
        ]
    )

    assert code == 2
    assert calls == []
    report = json.loads(capsys.readouterr().out)
    assert report["failure_code"] == "top_level_session_required"
