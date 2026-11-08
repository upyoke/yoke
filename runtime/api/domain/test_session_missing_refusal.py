"""A missing session means two different things; the text must say which.

Inside a harness the session should have been there and reporting it is
the recovery. In a plain terminal there was never going to be one, and a
live install told its operator to file a field-note about their own
first command.
"""

from __future__ import annotations

from dataclasses import replace
from unittest import mock

import pytest

from yoke_core.domain import session_ambient_identity
from yoke_core.domain.yoke_function_actor_identity import bind_actor_identity
from yoke_core.domain.yoke_function_registry import RegistryEntry
from yoke_core.domain.session_missing_refusal import (
    TERMINAL_SUPPORTED_PATH,
    format_session_missing,
)


def _terminal_text(function_id="items.freeze.run"):
    return format_session_missing(
        function_id, channels="env:session=empty", harness_family="",
    )


def test_terminal_text_names_the_supported_path_and_never_a_field_note():
    text = _terminal_text()
    assert TERMINAL_SUPPORTED_PATH in text
    assert "field-note" not in text
    assert "harness session" in text


def test_terminal_text_still_names_the_function_and_the_channels():
    text = _terminal_text()
    assert "'items.freeze.run'" in text
    assert "env:session=empty" in text


def test_harness_text_keeps_the_infrastructure_gap_framing():
    text = format_session_missing(
        "items.freeze.run", channels="env:session=empty",
        harness_family="claude",
    )
    assert "infrastructure gap" in text
    assert "yoke feedback" in text
    assert TERMINAL_SUPPORTED_PATH in text
    assert "hooks deliberately create no session" in text


def test_contested_anchors_ride_on_the_harness_text():
    text = format_session_missing(
        "x.y.z", channels="c", contested=["a", "b"], harness_family="claude",
    )
    assert "contested_anchors=" in text


def test_the_live_formatter_picks_the_branch_from_the_process_tree():
    with (
        mock.patch.object(
            session_ambient_identity, "consult_identity_channels",
            return_value=[{"channel": "env:session", "raw": "", "resolved": ""}],
        ),
        mock.patch.object(
            session_ambient_identity, "contested_anchor_session_ids",
            return_value=[],
        ),
        mock.patch.object(
            session_ambient_identity, "nearest_harness_family", return_value="",
        ),
    ):
        text = session_ambient_identity.format_actor_session_missing("a.b.c")
    assert TERMINAL_SUPPORTED_PATH in text
    assert "field-note" not in text


def _mutating_entry() -> RegistryEntry:
    from pydantic import BaseModel

    class _Model(BaseModel):
        pass

    return RegistryEntry(
        function_id="items.freeze.run",
        handler=lambda request: None,
        request_model=_Model,
        response_model=_Model,
        stability="stable",
        owner_module="test",
        target_kinds=("item",),
        side_effects=("write",),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def test_the_binder_denial_carries_the_terminal_path_outside_a_harness():
    """The refusal a person actually receives comes through the binder."""
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )

    request = FunctionCallRequest(
        function="items.freeze.run",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="item", item_id=1),
    )
    with mock.patch.object(
        session_ambient_identity, "nearest_harness_family", return_value="",
    ):
        result = bind_actor_identity(
            _mutating_entry(), request, ambient_session_id="",
        )
    assert result.error is not None and result.error.error is not None
    message = result.error.error.message
    assert TERMINAL_SUPPORTED_PATH in message
    assert "field-note" not in message


def _session_request(session_id: str):
    from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef

    return FunctionCallRequest(
        function="sessions.touch",
        actor=ActorContext(actor_id=None, session_id=session_id),
        target=TargetRef(kind="global"),
    )


def _entry(guardrails=("active_session_required",)) -> RegistryEntry:
    return replace(_mutating_entry(), function_id="sessions.touch", guardrails=guardrails)


@pytest.mark.parametrize(
    "harness_session_id",
    [
        "0667f6fd-a90e-4351-9bdf-faebd97e277d",  # cursor conversation id
        "c86c8ecd-90c3-413e-9b53-c8e4f7ef545b",  # claude-code session id
        "01a1b7e9-dfe6-7300-b116-9e150a8a68b8",  # codex thread id
    ],
)
def test_unregistered_harness_session_is_taught_sessions_begin(harness_session_id):
    """Outside a project every harness still sends its native id; none is registered."""
    from yoke_core.domain.session_missing_refusal import unregistered_session_refusal
    from yoke_core.domain.yoke_function_actor_identity import BoundIdentity

    request = _session_request(harness_session_id)
    bound = BoundIdentity(request, harness_session_id, "", session_registered=False)
    refusal = unregistered_session_refusal(_entry(), request, bound)
    assert refusal is not None and refusal.error is not None
    assert refusal.error.code == "actor_session_missing"
    assert harness_session_id in refusal.error.message
    assert "yoke sessions begin" in refusal.error.message
    assert "not found" not in refusal.error.message


@pytest.mark.parametrize(
    ("registered", "guardrails"),
    [(True, ("active_session_required",)), (None, ("active_session_required",)), (False, ())],
)
def test_registered_or_unguarded_calls_pass_through(registered, guardrails):
    from yoke_core.domain.session_missing_refusal import unregistered_session_refusal
    from yoke_core.domain.yoke_function_actor_identity import BoundIdentity

    request = _session_request("c86c8ecd-90c3-413e-9b53-c8e4f7ef545b")
    bound = BoundIdentity(request, "", "", session_registered=registered)
    assert unregistered_session_refusal(_entry(guardrails), request, bound) is None


def test_session_scoped_writes_declare_the_guardrail():
    from yoke_core.domain.session_missing_refusal import ACTIVE_SESSION_GUARDRAIL
    from yoke_core.domain.yoke_function_dispatch import _ensure_handlers_registered
    from yoke_core.domain.yoke_function_registry import lookup

    _ensure_handlers_registered()
    for function_id in ("sessions.touch", "sessions.checkpoint", "sessions.wake.schedule"):
        assert ACTIVE_SESSION_GUARDRAIL in lookup(function_id).guardrails
