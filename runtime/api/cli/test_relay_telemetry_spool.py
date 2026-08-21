"""Relay outcomes survive the outage they describe, then get sent.

A relay failure cannot be reported through the relay, so the count has to
wait on disk until a call lands. Until this existed the only evidence of how
often the relay failed was how often somebody wrote it down, which measures
diligence as much as failure.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.cli.https_relay_security_test_support import sensitive_request
from yoke_cli.transport import https_relay_outcome
from yoke_cli.transport import relay_telemetry
from yoke_contracts.api.function_call import FunctionCallResponse


@pytest.fixture(autouse=True)
def _machine_home(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    return tmp_path


def _response(*, code: str = "") -> FunctionCallResponse:
    return FunctionCallResponse(
        success=not code,
        function="items.detail.get",
        version="v1",
        request_id="relay-telemetry-request",
        error={"code": code, "message": "detail"} if code else None,
    )


def _emit_response(*, success: bool) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=success,
        function="events.emit",
        version="v1",
        request_id="emit",
        result={"emitted": True} if success else {},
        error=None if success else {"code": "payload_invalid", "message": "no"},
    )


def _spooled() -> list[dict]:
    path = relay_telemetry.spool_path()
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_a_first_try_success_records_nothing(monkeypatch) -> None:
    monkeypatch.setattr(relay_telemetry, "flush", lambda: 0)

    https_relay_outcome.record_outcome(
        sensitive_request(), _response(), env="prod", attempts=1,
    )

    assert _spooled() == []


def test_a_call_that_needed_another_attempt_is_counted(monkeypatch) -> None:
    monkeypatch.setattr(relay_telemetry, "flush", lambda: 0)

    https_relay_outcome.record_outcome(
        sensitive_request(), _response(), env="prod", attempts=3,
    )

    (entry,) = _spooled()
    assert entry["succeeded"] is True
    assert entry["attempts"] == 3
    assert entry["env"] == "prod"
    # The harness is resolved by joining this to the session row, so nothing
    # here has to know which harness it is running in.
    assert entry["session_id"] == "sensitive-relay-test"


def test_an_exhausted_call_is_counted_and_not_flushed(monkeypatch) -> None:
    flushed: list[int] = []
    monkeypatch.setattr(
        relay_telemetry, "flush", lambda: flushed.append(1) or 0,
    )

    https_relay_outcome.record_outcome(
        sensitive_request(),
        _response(code=https_relay_outcome.TRANSPORT_FAILED_CODE),
        env="prod",
        attempts=3,
    )

    (entry,) = _spooled()
    assert entry["succeeded"] is False
    assert entry["failure_class"] == https_relay_outcome.TRANSPORT_FAILED_CODE
    # Nothing can be sent through a relay that just refused to answer.
    assert flushed == []


def test_a_handler_failure_is_not_a_transport_failure(monkeypatch) -> None:
    """The relay answered; what it said is the handler's business."""
    monkeypatch.setattr(relay_telemetry, "flush", lambda: 0)

    https_relay_outcome.record_outcome(
        sensitive_request(), _response(code="item_not_found"),
        env="prod", attempts=1,
    )

    assert _spooled() == []


def test_the_next_call_that_lands_drains_the_spool(monkeypatch) -> None:
    sent: list[dict] = []

    def _capture(**kwargs):
        sent.append(kwargs)
        return FunctionCallResponse(
            success=True, function="events.emit", version="v1",
            request_id="emit", result={"emitted": True},
        )

    relay_telemetry.record(
        function_id="items.detail.get", session_id="session-a", env="prod",
        attempts=3, succeeded=True, failure_class="",
    )
    relay_telemetry.record(
        function_id="lifecycle.transition.execute", session_id="session-a",
        env="prod", attempts=3, succeeded=False,
        failure_class="https_transport_failed",
    )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher", _capture,
    )

    assert relay_telemetry.flush() == 2
    assert _spooled() == []
    names = [call["payload"]["name"] for call in sent]
    assert names == [
        relay_telemetry.EVENT_RETRIED,
        relay_telemetry.EVENT_EXHAUSTED,
    ]
    assert sent[1]["payload"]["severity"] == "WARN"
    assert sent[0]["payload"]["context"]["attempts"] == 3


def test_a_refused_emit_leaves_the_record_spooled(monkeypatch) -> None:
    """The spool is worth having exactly when delivery is not working."""
    relay_telemetry.record(
        function_id="items.detail.get", session_id="session-a", env="prod",
        attempts=3, succeeded=False, failure_class="https_transport_failed",
    )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_kwargs: _emit_response(success=False),
    )

    assert relay_telemetry.flush() == 0

    (entry,) = _spooled()
    assert entry["function"] == "items.detail.get"
    assert entry["failure_class"] == "https_transport_failed"


def test_a_flush_that_starts_refusing_keeps_what_it_did_not_send(
    monkeypatch,
) -> None:
    """Only a delivered record leaves the spool; the rest waits."""
    for name in ("first", "second", "third"):
        relay_telemetry.record(
            function_id=name, session_id="session-a", env="prod",
            attempts=3, succeeded=True, failure_class="",
        )
    calls = {"count": 0}

    def _one_then_refuse(**_kwargs):
        calls["count"] += 1
        return _emit_response(success=calls["count"] == 1)

    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher", _one_then_refuse,
    )

    assert relay_telemetry.flush() == 1
    assert [entry["function"] for entry in _spooled()] == ["second", "third"]
    # This runs inline on a real caller's call, so the queue behind a
    # refusal is not spent on a relay that has just refused.
    assert calls["count"] == 2


def test_flushing_does_not_flush_itself(monkeypatch) -> None:
    """Emitting goes back through the relay whose success triggered this."""
    depth = {"max": 0, "now": 0}

    def _reentrant(**_kwargs):
        depth["now"] += 1
        depth["max"] = max(depth["max"], depth["now"])
        relay_telemetry.flush()
        depth["now"] -= 1
        return FunctionCallResponse(
            success=True, function="events.emit", version="v1",
            request_id="emit", result={"emitted": True},
        )

    relay_telemetry.record(
        function_id="items.detail.get", session_id="session-a", env="prod",
        attempts=2, succeeded=True, failure_class="",
    )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher", _reentrant,
    )

    assert relay_telemetry.flush() == 1
    assert depth["max"] == 1


def test_the_spool_stops_growing_when_nothing_ever_lands() -> None:
    """A machine that never reconnects keeps a bounded file, not a leak."""
    for index in range(relay_telemetry.SPOOL_MAX_RECORDS + 25):
        relay_telemetry.record(
            function_id=f"items.get.{index}", session_id="session-a",
            env="prod", attempts=3, succeeded=False,
            failure_class="https_transport_failed",
        )

    assert len(_spooled()) == relay_telemetry.SPOOL_MAX_RECORDS


def test_records_coming_back_from_a_refused_flush_stay_bounded(
    monkeypatch,
) -> None:
    """Returning records to the spool is capped like writing new ones."""
    for index in range(relay_telemetry.SPOOL_MAX_RECORDS):
        relay_telemetry.record(
            function_id=f"items.get.{index}", session_id="session-a",
            env="prod", attempts=3, succeeded=False,
            failure_class="https_transport_failed",
        )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_kwargs: _emit_response(success=False),
    )

    assert relay_telemetry.flush() == 0
    assert len(_spooled()) == relay_telemetry.SPOOL_MAX_RECORDS


def test_an_unreadable_spool_never_breaks_the_call(monkeypatch) -> None:
    def _explode():
        raise OSError("no such machine home")

    monkeypatch.setattr(relay_telemetry, "spool_path", _explode)

    relay_telemetry.record(
        function_id="items.detail.get", session_id="session-a", env="prod",
        attempts=3, succeeded=True, failure_class="",
    )
    assert relay_telemetry.drain() == []
    assert relay_telemetry.flush() == 0
