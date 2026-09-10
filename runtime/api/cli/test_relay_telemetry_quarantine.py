"""A permanent refusal is evidence, not a retry — and never a guessed label.

The spool exists for outcomes the relay could not send. A record the server
HAS reached and definitively refused (bad authorization, a malformed
payload) is a different failure entirely: retrying it repeats the identical
refusal on every later successful call, turning one bad record into a
standing tax. These tests prove that refusal is quarantined once instead,
and that a record's project attribution is fixed at the moment it was
observed rather than guessed from whatever project the eventual flush
happens to be running under.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.cli.test_relay_telemetry_spool import (
    _emit_response,
    _record_telemetry,
    _spooled,
)
from yoke_cli.transport import relay_telemetry
from yoke_contracts.api.function_call import FunctionCallResponse


@pytest.fixture(autouse=True)
def _machine_home(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    return tmp_path


def _quarantined() -> list[dict]:
    path = relay_telemetry.quarantine_path()
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_a_permanently_refused_record_is_quarantined_not_retried(
    monkeypatch,
) -> None:
    """A definitive authorization/payload refusal never goes back on the
    spool — retrying it would only repeat the identical refusal forever."""
    _record_telemetry(
        transport_delivered=False,
        application_succeeded=None,
    )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_kwargs: _emit_response(success=False, code="permission_denied"),
    )

    assert relay_telemetry.flush() == 0
    assert _spooled() == []
    (quarantined,) = _quarantined()
    assert quarantined["function"] == "items.detail.get"


def test_a_permanent_refusal_does_not_stop_the_rest_of_the_pass(
    monkeypatch,
) -> None:
    """The relay is healthy; only the refused record was bad, so the pass
    keeps going instead of requeueing records behind it."""
    for name in ("first", "second"):
        _record_telemetry(
            function_id=name,
            transport_delivered=True,
            application_succeeded=True,
        )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_kwargs: _emit_response(success=False, code="payload_invalid"),
    )

    assert relay_telemetry.flush() == 0
    assert _spooled() == []
    assert [entry["function"] for entry in _quarantined()] == ["first", "second"]


def test_quarantine_stays_bounded_like_the_spool(monkeypatch) -> None:
    """A machine whose credential is permanently wrong keeps a bounded
    evidence file, not a leak."""
    for index in range(relay_telemetry.QUARANTINE_MAX_RECORDS + 10):
        _record_telemetry(
            function_id=f"items.get.{index}",
            transport_delivered=False,
            application_succeeded=None,
        )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_kwargs: _emit_response(success=False, code="permission_denied"),
    )

    assert relay_telemetry.flush() == 0
    assert len(_quarantined()) == relay_telemetry.QUARANTINE_MAX_RECORDS
    assert _spooled() == []


def test_project_attribution_is_fixed_at_observation_not_at_flush(
    monkeypatch,
) -> None:
    """A record's project is the one the failing call itself belonged to —
    never whichever project the eventual flush happens to be running under."""
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.client_project_context",
        lambda explicit=None: "universe-that-failed",
    )
    _record_telemetry(transport_delivered=False, application_succeeded=None)

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
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.client_project_context",
        lambda explicit=None: "universe-receiving-it",
    )

    assert relay_telemetry.flush() == 1
    assert sent[0]["payload"]["project"] == "universe-that-failed"


def test_an_unnameable_project_at_observation_time_is_left_out(
    monkeypatch,
) -> None:
    """The server denies a project-scoped call it cannot place instead of
    defaulting, so a guess here would only mislabel a stranger's row."""
    monkeypatch.setattr(
        "yoke_cli.commands._helpers.client_project_context",
        lambda explicit=None: None,
    )
    _record_telemetry(transport_delivered=False, application_succeeded=None)

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

    assert relay_telemetry.flush() == 1
    assert "project" not in sent[0]["payload"]
