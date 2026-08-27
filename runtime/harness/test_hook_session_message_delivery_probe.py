"""What a declining hook evaluation records, and what a resume still gets.

The two halves belong together: a resumed Cursor session takes delivery on
exactly the path a fresh one does, and when some path does decline it says
which one rather than leaving an operator to infer a mechanism from an
``injection_count`` that never moved.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.session_message_delivery_probe import (
    PROBE_LEASE_FAILED,
    PROBE_NO_LEASABLE_RECEIPT,
    PROBE_SESSION_NOT_DELIVERABLE,
)
from yoke_core.hooks import session_message_delivery as delivery
from yoke_core.hooks.types import Outcome
from runtime.harness.session_message_delivery_test_helpers import (
    MESSAGE_ID,
    FakePort,
    hook_context,
)


CURSOR_START = {"family": "cursor", "surface": "cursor-cli"}


def _port(monkeypatch: pytest.MonkeyPatch, **kwargs) -> FakePort:
    port = FakePort(**kwargs)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    return port


def test_a_resumed_cursor_start_takes_delivery_on_the_fresh_start_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resume has no delivery path of its own — there is only one.

    The evaluator is told the event and the session, never whether the
    session is opening for the first time or reopening, so a woken turn
    reaches the same lease a first turn does.
    """
    port = _port(monkeypatch)

    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert port.leased == [("session-top", "SessionStart", 10)]
    assert port.probed == []
    rendered = decision.audit_fields["additionalContext"]
    assert f"BEGIN YOKE SESSION MESSAGE {MESSAGE_ID}" in rendered
    assert f"yoke messages acknowledge {MESSAGE_ID}" in rendered


def test_a_resumed_cursor_start_settles_injected_once_its_reply_carries_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch)
    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))
    token = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]["render_token"]

    delivery.settle_after_render(
        [decision],
        rendered_text='{"additional_context": "' + token + '"}',
        denied=False,
        port=port,
    )

    assert port.completed == [("lease-1", True, "injected")]


def test_an_undeliverable_session_records_that_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch, acknowledged=True)

    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert decision.outcome is Outcome.NOOP
    assert port.probed == [
        ("session-top", "SessionStart", PROBE_SESSION_NOT_DELIVERABLE, "")
    ]


def test_a_failing_lease_records_its_class_and_never_its_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(
        monkeypatch,
        lease_error=TimeoutError("canceling statement due to lock timeout"),
    )

    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert decision.outcome is Outcome.NOOP
    assert port.probed == [
        ("session-top", "SessionStart", PROBE_LEASE_FAILED, "TimeoutError")
    ]


def test_a_lease_that_carried_nothing_is_released_and_then_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch, empty_lease=True)

    decision = delivery.evaluate(hook_context("SessionStart", **CURSOR_START))

    assert decision.outcome is Outcome.NOOP
    assert port.completed == [("lease-1", False, "empty_lease")]
    assert port.probed == [
        ("session-top", "SessionStart", PROBE_NO_LEASABLE_RECEIPT, "")
    ]


def test_a_failing_probe_never_turns_a_quiet_miss_into_a_failing_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch, acknowledged=True)

    def refuse(**_kwargs: object) -> int:
        raise RuntimeError("control plane unreachable")

    monkeypatch.setattr(port, "probe_undelivered", refuse)

    assert delivery.evaluate(hook_context("SessionStart", **CURSOR_START)).outcome is (
        Outcome.NOOP
    )


def test_a_session_this_process_cannot_name_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port(monkeypatch)

    decision = delivery.evaluate(hook_context("SessionStart", session_id=None))

    assert decision.outcome is Outcome.NOOP
    assert port.leased == []
    assert port.probed == []


def test_an_event_the_surface_cannot_inject_on_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a fact of the moment — the capability table already answers it."""
    port = _port(monkeypatch)

    decision = delivery.evaluate(
        hook_context("PreToolUse", family="cursor", surface="cursor-cli")
    )

    assert decision.outcome is Outcome.NOOP
    assert port.leased == []
    assert port.probed == []
