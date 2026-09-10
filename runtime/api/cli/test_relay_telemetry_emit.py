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
            success=True,
            function="events.emit",
            version="v1",
            request_id="emit",
            result={"emitted": True},
        )

    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        _capture,
    )
    return sent


def _project_context_is(monkeypatch, answer) -> None:
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.client_project_context",
        lambda explicit=None: answer,
    )


def _record(
    *,
    transport_delivered: bool,
    application_succeeded: bool | None,
) -> None:
    """Record with no explicit *project* — resolves via ``_project_context()``
    at call time, i.e. whatever ``client_project_context`` currently answers.
    Callers that care about project attribution set it with
    :func:`_project_context_is` before calling this."""
    relay_telemetry.record(
        function_id="items.detail.get",
        session_id="session-a",
        env="prod",
        attempts=3,
        transport_delivered=transport_delivered,
        application_succeeded=application_succeeded,
        failure_class=(
            ""
            if application_succeeded is True
            else "item_not_found"
            if transport_delivered
            else "https_transport_failed"
        ),
    )


@pytest.mark.parametrize(
    ("transport_delivered", "application_succeeded"),
    [(True, True), (True, False), (False, None)],
)
def test_the_emitted_payload_is_one_the_real_handler_accepts(
    monkeypatch,
    tmp_path,
    transport_delivered,
    application_succeeded,
) -> None:
    """``events.emit`` checks kind, source type, and severity against closed
    vocabularies, so the payload goes in front of that handler rather than
    in front of a stub with no opinion about any of them."""
    _project_context_is(monkeypatch, "yoke")
    sent = _capture_emits(monkeypatch)
    _record(
        transport_delivered=transport_delivered,
        application_succeeded=application_succeeded,
    )
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
        if transport_delivered
        else relay_telemetry.EVENT_EXHAUSTED
    )
    assert envelope["severity"] == ("INFO" if transport_delivered else "WARN")
    assert envelope["source_type"] == "system"
    context = envelope["context"]
    assert context["transport_outcome"] == (
        "delivered" if transport_delivered else "exhausted"
    )
    assert context["application_outcome"] == (
        "succeeded"
        if application_succeeded is True
        else "failed"
        if application_succeeded is False
        else "not_reached"
    )


def test_the_project_named_is_the_one_the_call_actually_failed_under(
    monkeypatch,
) -> None:
    """Project ids are per-universe, and a record is often flushed by a LATER
    call under a different universe entirely. Naming the project observed at
    failure time — not the one the eventual flush happens to run under — is
    what keeps the row from relabeling the failure into a stranger."""
    _project_context_is(monkeypatch, "universe-that-failed")
    _record(transport_delivered=False, application_succeeded=None)

    sent = _capture_emits(monkeypatch)
    _project_context_is(monkeypatch, "universe-receiving-it")
    assert relay_telemetry.flush() == 1

    assert sent[0]["payload"]["project"] == "universe-that-failed"


def test_an_unnameable_project_is_never_dispatched_rather_than_guessed(
    monkeypatch,
) -> None:
    """The dispatcher denies ANY project-scoped call naming no project — a
    known outcome — so a record with no defensible attribution is retained
    locally instead of spending a call on an answer already decided, and
    never guesses a default that would mislabel a stranger's row."""
    _project_context_is(monkeypatch, None)
    _record(transport_delivered=False, application_succeeded=None)

    sent = _capture_emits(monkeypatch)
    assert relay_telemetry.flush() == 0
    assert sent == []
