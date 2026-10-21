"""A release by a non-holder names the holder and the terminate recovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import yoke_function_dispatch_claims as dispatch
from yoke_core.domain.claim_recovery import terminate_holder_command


def _refusal(monkeypatch, function_id: str, holder_row):
    monkeypatch.setattr(dispatch, "_claim_row_for_id", lambda claim_id: holder_row)
    entry = SimpleNamespace(
        function_id=function_id, version="v1", claim_required_kind="self_only"
    )
    request = FunctionCallRequest(
        function=function_id,
        actor=ActorContext(session_id="caller"),
        target=TargetRef(kind="claim", claim_id=7),
        payload={"reason": "finished"},
    )
    response = dispatch.verify_claim(entry, request)
    assert response is not None and response.error is not None
    assert response.error.code == "claim_required"
    return response.error.message


@pytest.mark.parametrize(
    "function_id", ["claims.steering.release", "claims.work.release"]
)
def test_release_refusal_names_holder_and_terminate_command(monkeypatch, function_id):
    message = _refusal(
        monkeypatch, function_id, {"id": 7, "session_id": "ended-holder"}
    )
    assert "held by session ended-holder, not caller" in message
    assert terminate_holder_command("ended-holder") in message
    assert "YOK-<id>" not in message


def test_release_of_an_inactive_claim_says_so(monkeypatch):
    message = _refusal(monkeypatch, "claims.steering.release", None)
    assert message == "claim 7 is not an active claim; nothing to release"


def test_terminate_command_is_shell_safe():
    command = terminate_holder_command("abc")
    assert command.startswith('yoke sessions terminate abc --reason "')
    assert "--reason <" not in command
