"""A missing session means two different things; the text must say which.

Inside a harness the session should have been there and reporting it is
the recovery. In a plain terminal there was never going to be one, and a
live install told its operator to file a field-note about their own
first command.
"""

from __future__ import annotations

from unittest import mock

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
    assert "field-note" in text
    assert TERMINAL_SUPPORTED_PATH not in text


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
