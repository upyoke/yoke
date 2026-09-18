"""The merge close-out stamps the park its retention depends on.

The claim was already kept at a release wait; what was missing was any
record that the quiet which follows is a declared wait. These cover the one
write that produces it, including the two ways it must decline: a caller who
is not the item's owner, and a control plane that could not be reached.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yoke_core.domain import release_wait_park as park
from yoke_core.domain.release_wait_ownership import (
    HOLDER_FUNCTION,
    TOUCH_FUNCTION,
    park_reason,
)
from yoke_core.domain.session_mode import SESSION_MODE_PARKED

SESSION = "session-under-test"


class _NullAuthority:
    def __enter__(self) -> "_NullAuthority":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


def _wire(monkeypatch, dispatch) -> list[tuple[str, dict]]:
    monkeypatch.setattr(park, "connected_control_plane", lambda: _NullAuthority())
    monkeypatch.setattr(park, "call_dispatcher", dispatch)
    monkeypatch.setattr(park, "build_actor", lambda **kw: kw)
    return []


def _dispatch(calls, *, holder_session, touch_success=True, touch_error=""):
    def dispatch(*, function_id, target=None, payload=None, **_kw):
        calls.append((function_id, dict(payload or {})))
        if function_id == HOLDER_FUNCTION:
            holder = {"session_id": holder_session} if holder_session else None
            return SimpleNamespace(success=True, result={"holder": holder}, error=None)
        error = None if touch_success else SimpleNamespace(message=touch_error)
        return SimpleNamespace(success=touch_success, result={}, error=error)

    return dispatch


def _retain(monkeypatch, dispatch) -> dict:
    envelope: dict = {}
    _wire(monkeypatch, dispatch)
    park.retain_for_delivery(
        envelope, item_id=7, public_ref="ITEM-7", session_id=SESSION
    )
    return envelope["release_wait"]


def test_the_owner_is_parked_with_the_wait_named(monkeypatch) -> None:
    calls: list = []
    block = _retain(monkeypatch, _dispatch(calls, holder_session=SESSION))

    assert block["parked"] == "yes"
    assert block["session_mode"] == SESSION_MODE_PARKED
    assert block["work_claim"] == "retained"
    assert block["park_reason"] == park_reason("ITEM-7")
    assert "yoke merge item ITEM-7" in block["next_step"]
    assert calls[-1] == (
        TOUCH_FUNCTION,
        {"mode": SESSION_MODE_PARKED, "reason": park_reason("ITEM-7")},
    )


def test_a_caller_that_does_not_own_the_item_is_not_parked(monkeypatch) -> None:
    """An operator closing out somebody else's item is not the owner of this
    wait, so parking their session on it would be a lie about who holds it."""
    calls: list = []
    block = _retain(monkeypatch, _dispatch(calls, holder_session="another-session"))

    assert block["parked"] == (
        "skipped: this session does not hold the item's work claim"
    )
    assert block["session_mode"] == ""
    assert [function_id for function_id, _ in calls] == [HOLDER_FUNCTION]


def test_an_unreadable_holder_declines_rather_than_guessing(monkeypatch) -> None:
    calls: list = []
    block = _retain(monkeypatch, _dispatch(calls, holder_session=None))

    assert block["parked"].startswith("skipped:")


def test_a_refused_touch_is_reported_unconfirmed(monkeypatch) -> None:
    calls: list = []
    block = _retain(
        monkeypatch,
        _dispatch(
            calls,
            holder_session=SESSION,
            touch_success=False,
            touch_error="relay unavailable",
        ),
    )

    assert block["parked"] == "unconfirmed (relay unavailable)"
    assert block["session_mode"] == ""


def test_an_unreachable_control_plane_never_fails_the_merge(monkeypatch) -> None:
    def raising(**_kw):
        raise RuntimeError("transport closed")

    block = _retain(monkeypatch, raising)

    assert block["parked"] == "unconfirmed (transport closed)"
    assert block["work_claim"] == "retained"


def test_a_run_with_no_session_identity_says_so(monkeypatch) -> None:
    envelope: dict = {}
    _wire(monkeypatch, _dispatch([], holder_session=SESSION))
    park.retain_for_delivery(
        envelope, item_id=7, public_ref="ITEM-7", session_id=""
    )

    assert envelope["release_wait"]["parked"] == (
        "skipped: this run carries no session identity"
    )
