"""What a spooled relay outcome actually sends, and who accepts it.

The spool tests prove a record survives; these prove the record can land.
Both defects that kept every record out of the ledger were payload defects
that a stub returning unconditional success could not see, so the payload
here meets the real ``events.emit`` handler and the real project-scoping
rule instead.
"""

from __future__ import annotations

import json

import pytest

from yoke_cli.transport import relay_telemetry
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain.handlers.events_emit import handle_events_emit


@pytest.fixture(autouse=True)
def _machine_home(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    return tmp_path


def _capture_emits(monkeypatch) -> list[dict]:
    """Accept every emit, keeping the call kwargs for inspection."""
    sent: list[dict] = []

    def _capture(**kwargs):
        sent.append(kwargs)
        return FunctionCallResponse(
            success=True, function="events.emit", version="v1",
            request_id="emit", result={"emitted": True},
        )

    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher", _capture,
    )
    return sent


def _project_context_is(monkeypatch, answer) -> None:
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.client_project_context",
        lambda explicit=None: answer,
    )


def _record(*, succeeded: bool) -> None:
    relay_telemetry.record(
        function_id="items.detail.get", session_id="session-a", env="prod",
        attempts=3, succeeded=succeeded,
        failure_class="" if succeeded else "https_transport_failed",
    )


@pytest.mark.parametrize("succeeded", [True, False])
def test_the_emitted_payload_is_one_the_real_handler_accepts(
    monkeypatch, tmp_path, succeeded,
) -> None:
    """``events.emit`` checks kind, source type, and severity against closed
    vocabularies, so the payload goes in front of that handler rather than
    in front of a stub with no opinion about any of them."""
    sent = _capture_emits(monkeypatch)
    _record(succeeded=succeeded)
    assert relay_telemetry.flush() == 1

    captured = tmp_path / "events.ndjson"
    monkeypatch.setenv("YOKE_EVENTS_CAPTURE", "1")
    monkeypatch.setenv("YOKE_EVENTS_FILE", str(captured))
    outcome = handle_events_emit(
        FunctionCallRequest(
            function="events.emit",
            actor=ActorContext(session_id="session-a"),
            target=TargetRef(kind="global"),
            payload=sent[0]["payload"],
        )
    )

    assert outcome.error is None
    envelope = json.loads(captured.read_text(encoding="utf-8").strip())
    assert envelope["event_name"] == (
        relay_telemetry.EVENT_RETRIED
        if succeeded
        else relay_telemetry.EVENT_EXHAUSTED
    )
    assert envelope["severity"] == ("INFO" if succeeded else "WARN")
    assert envelope["source_type"] == "system"


def test_the_project_named_is_the_one_the_record_is_sent_to(
    monkeypatch,
) -> None:
    """Project ids are per-universe, and a record is delivered to whichever
    universe the machine next reaches — routinely not the one that failed.
    Naming the project observed at failure time would name a stranger."""
    _project_context_is(monkeypatch, "universe-that-failed")
    _record(succeeded=False)

    sent = _capture_emits(monkeypatch)
    _project_context_is(monkeypatch, "universe-receiving-it")
    assert relay_telemetry.flush() == 1

    assert sent[0]["payload"]["project"] == "universe-receiving-it"


def test_an_unnameable_project_is_left_out_rather_than_guessed(
    monkeypatch,
) -> None:
    """The server denies a project-scoped call it cannot place instead of
    falling back to a default, so a guess here would only mislabel the row
    of whichever project the guess happened to name."""
    sent = _capture_emits(monkeypatch)
    _project_context_is(monkeypatch, None)
    _record(succeeded=False)

    assert relay_telemetry.flush() == 1
    assert "project" not in sent[0]["payload"]
