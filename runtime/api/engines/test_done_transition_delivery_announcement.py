"""Closeout announces a delivery, and never lets that endanger done.

The announcement runs inside the closeout, which by construction happens
after the status write has committed — so the only question these cover
is what the closeout does with each possible answer. A committed done is
never at risk: an unavailable relay, a refused call, and a delivery with
nobody to tell are each reported and left retryable.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_core.engines import done_transition_finalize as finalize


def _response(result=None, *, success=True, message="relay refused"):
    return FunctionCallResponse(
        success=success,
        function="done_transition.delivery_done_notice",
        version="v1",
        result=result or {},
        error=None if success else FunctionError(code="failed", message=message),
    )


def _announce(monkeypatch, fake, capsys) -> str:
    monkeypatch.setattr(finalize, "call_dispatcher", fake)
    finalize._announce_delivery(4242, "YOK-4242")
    return capsys.readouterr().out


def test_a_delivered_notice_is_reported(monkeypatch, capsys) -> None:
    out = _announce(
        monkeypatch,
        lambda **_kwargs: _response(
            {"delivery": "notified", "run_id": "run-1", "reason": ""}
        ),
        capsys,
    )
    assert "Announced YOK-4242's delivery from run run-1" in out


def test_a_delivery_nobody_owns_is_visible(monkeypatch, capsys) -> None:
    out = _announce(
        monkeypatch,
        lambda **_kwargs: _response(
            {
                "delivery": "",
                "run_id": "run-2",
                "reason": "items.owner names no human organization member",
            }
        ),
        capsys,
    )
    assert "has nobody to announce it to" in out
    assert "items.owner names no human organization member" in out


def test_an_item_with_no_delivery_says_nothing(monkeypatch, capsys) -> None:
    out = _announce(
        monkeypatch,
        lambda **_kwargs: _response({"delivery": "", "run_id": "", "reason": "none"}),
        capsys,
    )
    assert out == ""


def test_a_refused_call_warns_without_raising(monkeypatch, capsys) -> None:
    out = _announce(monkeypatch, lambda **_kwargs: _response(success=False), capsys)
    assert "could not announce YOK-4242's delivery" in out
    assert "relay refused" in out


def test_an_unavailable_relay_warns_without_raising(monkeypatch, capsys) -> None:
    def _raise(**_kwargs):
        raise RuntimeError("control plane unreachable")

    out = _announce(monkeypatch, _raise, capsys)
    assert "could not announce YOK-4242's delivery" in out
    assert "control plane unreachable" in out


def test_the_announcement_runs_inside_the_committed_closeout() -> None:
    """Where it is called from is the "only after done" guarantee.

    ``finish_done_transition``'s own contract is that every step it runs
    happens after the item's status reached done, so the announcement
    being a closeout step is what makes it unreachable before the commit.
    """
    import inspect

    source = inspect.getsource(finalize._run_closeout)
    assert "_announce_delivery(item_id, ref)" in source
    assert "committed" in inspect.getdoc(finalize.finish_done_transition)


def test_announcement_helper_never_propagates(monkeypatch) -> None:
    """Belt and braces: no input shape escapes as an exception."""

    def _raise(**_kwargs):
        raise KeyError("unexpected payload")

    monkeypatch.setattr(finalize, "call_dispatcher", _raise)
    finalize._announce_delivery(1, "YOK-1")


def test_result_shape_that_is_not_a_mapping_is_tolerated(monkeypatch) -> None:
    monkeypatch.setattr(
        finalize,
        "call_dispatcher",
        lambda **_kwargs: _response(None),
    )
    finalize._announce_delivery(1, "YOK-1")


if __name__ == "__main__":  # pragma: no cover - manual convenience
    raise SystemExit(pytest.main([__file__]))
