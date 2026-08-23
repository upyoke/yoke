"""Reinjection proof for the first Fleet acceptance receipt."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)


class _PrematureAckClient(_ScenarioClient):
    def _message(self, message_id: str) -> dict[str, Any]:
        result = super()._message(message_id)
        if message_id == "initial-message":
            recipient = result["message"]["recipients"][0]
            recipient.update(
                state="acknowledged",
                injection_count=1,
                acknowledged_at="2026-08-23T12:00:00Z",
            )
        return result


def test_live_initial_delivery_requires_reinjection_before_ack() -> None:
    cell = AcceptanceCell(
        "codex-cli",
        "0.149.0-alpha.4",
        "identify",
        session_id="reinjection-target",
    )
    client = _ScenarioClient(cell)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="reinjection-proof",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    assert report["status"] == "passed"
    assert client.message_reads["initial-message"] == 2
    assert report["initial_message"]["injection_count"] == 2
    assert report["wake_message"]["injection_count"] == 1
    bodies = [body for argv, body in client.calls if argv[:2] == ["say", "--stdin"]]
    assert "do not acknowledge" in str(bodies[0])
    assert "Only on reinjection" in str(bodies[0])
    assert "do not acknowledge" not in str(bodies[-1])

    with pytest.raises(AcceptanceContractError) as captured:
        _driver(_PrematureAckClient(cell))._run_cell(
            "yoke",
            cell,
            run_id="premature-ack",
            timeout=10,
            poll=1,
            unsupported_observation=2,
        )
    assert captured.value.code == "ack_evidence_invalid"
