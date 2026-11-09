"""Explicit steering takeover requires a reason and reaches the registered handler."""

import pytest

from runtime.api.cli.test_yoke_operations_cli_steering_claims import _run, _CAPTURED
from yoke_core.domain.handlers.claims_steering import handle_acquire


def test_takeover_dispatches_explicit_intent():
    _CAPTURED.clear()
    rc, _, err = _run(
        "claims", "steering", "acquire", "--project", "alpha",
        "--take-over", "--reason", "recover stuck steering",
    )
    assert rc == 0, err
    assert _CAPTURED[-1].payload == {
        "take_over": True, "reason": "recover stuck steering",
    }


@pytest.mark.parametrize("reason", [[], ["--reason", ""], ["--reason", "   "]])
def test_takeover_without_reason_refuses_before_dispatch(reason):
    _CAPTURED.clear()
    rc, _, err = _run(
        "claims", "steering", "acquire", "--project", "alpha", "--take-over", *reason,
    )
    assert rc == 2
    assert "--take-over requires --reason TEXT" in err
    assert not _CAPTURED


def test_handler_passes_explicit_intent_to_acquire(monkeypatch):
    from contextlib import nullcontext
    from yoke_core.domain import db_helpers, steering_claims
    from runtime.api.cli.test_yoke_operations_cli_steering_claims import _claim

    _CAPTURED.clear()
    _run("claims", "steering", "acquire", "--project", "alpha",
         "--take-over", "--reason", "recover stuck steering")
    request = _CAPTURED[-1].model_copy(update={"options": {"authorized_project_id": 7}})
    observed = {}

    def acquire(conn, **kwargs):
        observed.update(kwargs)
        return _claim(41)

    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(object()))
    monkeypatch.setattr(steering_claims, "acquire", acquire)
    outcome = handle_acquire(request)
    assert outcome.primary_success
    assert observed["take_over"] is True
    assert observed["reason"] == "recover stuck steering"
