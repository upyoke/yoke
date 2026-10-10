"""Owned acceptance clock projection preserves precision and body-free refusals."""

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_evidence import wait_for_ack
from runtime.api.tools.test_session_control_live_acceptance_clock import AcceptanceClock
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)
from runtime.api.tools.test_session_control_live_acceptance_retry_evidence import (
    MESSAGE_ID,
    _acknowledged,
    _attempt,
    _parse,
)
from yoke_contracts.session_control.wake_delivery import WAKE_DELIVERED_RESULT


CELL = AcceptanceCell("claude-cli", "2.1.245", "identify", wake_route="direct")
CANONICAL = "1969-12-31T23:59:59.999999Z"
INPUTS = (
    CANONICAL,
    "1970-01-01T05:44:59.999999+05:45",
    datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc),
)
INVALID = (
    "",
    "1969-12-31T23:59:59",
    "1969-12-31",
    0,
    False,
    datetime(1969, 12, 31, 23, 59, 59),
    "1970-01-01T00:00:00-00:00",
)


@pytest.mark.parametrize("value", (*INPUTS, None))
def test_driver_receipt_clock_owner_preserves_command_evidence(value) -> None:
    client = _ScenarioClient(CELL)
    client.message_states[MESSAGE_ID] = (True, 1)
    message = client._message(MESSAGE_ID)["message"]
    row = message["recipients"][0]
    row.update(acknowledged_at=value, last_wake_at=value)
    original = deepcopy(message)
    client.call = lambda *_args, **_kwargs: {"message": message}

    receipt = _driver(client)._receipt(CELL, client.session_id, MESSAGE_ID)

    expected = None if value is None else CANONICAL
    assert receipt["acknowledged_at"] == expected
    assert receipt["last_wake_at"] == expected
    assert receipt["injection_count"] == receipt["wake_attempt_count"] == 1
    assert receipt["attempt_evidence"]["attempts"] == original["attempts"]
    assert message == original
    json.dumps(receipt)


@pytest.mark.parametrize("key", ("acknowledged_at", "last_wake_at"))
@pytest.mark.parametrize("value", INVALID)
def test_driver_refuses_ambiguous_receipt_clocks(key, value) -> None:
    client = _ScenarioClient(CELL)
    client.message_states[MESSAGE_ID] = (True, 1)
    message = client._message(MESSAGE_ID)["message"]
    message["recipients"][0][key] = value
    client.call = lambda *_args, **_kwargs: {"message": message}
    with pytest.raises(AcceptanceContractError) as failure:
        _driver(client)._receipt(CELL, client.session_id, MESSAGE_ID)
    assert failure.value.code == "receipt_clock_invalid"
    assert failure.value.surface == CELL.surface


@pytest.mark.parametrize("value", INPUTS)
def test_native_wake_summary_formats_only_owned_clocks(value) -> None:
    attempt = _attempt("native-attempt", WAKE_DELIVERED_RESULT)
    attempt.update(started_at=value, completed_at=value)
    original = deepcopy(attempt)
    summary = _parse(CELL, [attempt])["attempts"][0]
    assert summary == {
        "attempt_id": "native-attempt",
        "attempt_kind": "wake_relay",
        "result_code": WAKE_DELIVERED_RESULT,
        "started_at": CANONICAL,
        "completed_at": CANONICAL,
    }
    assert attempt == original
    json.dumps(summary)


@pytest.mark.parametrize("key", ("started_at", "completed_at"))
@pytest.mark.parametrize("value", INVALID)
def test_invalid_attempt_clock_retains_settlement_refusal_and_null_diagnostic(
    key, value
) -> None:
    attempt = _attempt("native-attempt", WAKE_DELIVERED_RESULT)
    attempt[key] = value
    clock = AcceptanceClock()
    with pytest.raises(AcceptanceContractError) as failure:
        wait_for_ack(
            lambda *_args: _acknowledged(attempt),
            cell=CELL,
            session_id="target-session",
            message_id=MESSAGE_ID,
            timeout=1,
            poll=1,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            expected_route="direct",
            require_wake=True,
        )
    assert failure.value.code == "wake_attempt_settlement_invalid"
    evidence = failure.value.evidence
    assert evidence["native_wake_attempts"]["attempts"][0][key] is None
    assert evidence["acknowledged_at"] == "2026-08-25T18:00:02.000000Z"
    assert evidence["last_wake_at"] == "2026-08-25T18:00:00.000000Z"
    assert "native_instruction_sha256" not in json.dumps(evidence)
    assert attempt[key] == value
