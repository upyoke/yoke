"""A release by a non-holder without a seat names the holder and the release."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import session_steering_authority as authority
from yoke_core.domain import yoke_function_dispatch_claims as dispatch
from yoke_core.domain.sessions_analytics import SessionError


def _no_seat(*_args, **_kwargs):
    raise SessionError("claim_required", "no seat")


def _refusal(monkeypatch, function_id: str, holder_row):
    monkeypatch.setattr(dispatch, "_claim_row_for_id", lambda claim_id: holder_row)
    monkeypatch.setattr(authority, "require_any_steering_seat", _no_seat)
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda: nullcontext(object())
    )
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
    ("function_id", "command"),
    [
        ("claims.steering.release", "yoke claims steering release 7"),
        ("claims.work.release", "yoke claims work release --claim-id 7"),
    ],
)
def test_release_refusal_names_holder_and_release_command(
    monkeypatch, function_id, command
):
    message = _refusal(
        monkeypatch, function_id, {"id": 7, "session_id": "ended-holder"}
    )
    assert "held by session ended-holder, not caller" in message
    assert f'`{command} --reason "<why>"`' in message
    assert "terminate" not in message


def test_release_of_an_inactive_claim_says_so(monkeypatch):
    message = _refusal(monkeypatch, "claims.steering.release", None)
    assert message == "claim 7 is not an active claim; nothing to release"
