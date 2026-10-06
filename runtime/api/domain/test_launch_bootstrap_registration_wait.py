"""The launch mandate's registration check agrees with ``launch get``.

A worker decides between proceeding, waiting, and refusing from the
``identity_correlation`` value ``launch get`` projects. The mandate names the
in-flight values it waits on, so those names must be exactly what the
projection emits for a launch that has not bound yet, and never what it emits
for a launch bound to someone else.
"""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.launch_bootstrap import (
    LAUNCH_REGISTRATION_IN_FLIGHT,
    LAUNCH_REGISTRATION_RECHECK_LIMIT,
    native_launch_bootstrap,
)
from yoke_core.domain.session_launch_visibility import launch_visibility


def _correlation(state: str, *, native: str | None, registered: str | None) -> str:
    return launch_visibility(
        state=state,
        result_code=None,
        native_session_id=native,
        registered_session_id=registered,
    )["identity_correlation"]


@pytest.mark.parametrize(
    ("state", "native"),
    [
        ("launching", None),
        ("awaiting_registration", None),
        ("awaiting_registration", "native-1"),
    ],
)
def test_an_unbound_in_flight_launch_reads_as_registration_in_flight(
    state: str, native: str | None
) -> None:
    assert _correlation(state, native=native, registered=None) in (
        LAUNCH_REGISTRATION_IN_FLIGHT
    )


def test_a_launch_bound_to_another_session_never_reads_as_in_flight() -> None:
    assert (
        _correlation("succeeded", native="other-session", registered="other-session")
        not in LAUNCH_REGISTRATION_IN_FLIGHT
    )
    assert (
        _correlation("failed", native=None, registered=None)
        not in LAUNCH_REGISTRATION_IN_FLIGHT
    )


def test_the_mandate_waits_while_registration_is_in_flight() -> None:
    bootstrap = native_launch_bootstrap("launch-example")

    for value in LAUNCH_REGISTRATION_IN_FLIGHT:
        assert value in bootstrap
    assert "registration is still in flight" in bootstrap
    assert f"at most {LAUNCH_REGISTRATION_RECHECK_LIMIT} times" in bootstrap
    assert (
        "stop and report launch_registration_pending with the launch id "
        "to the requester"
    ) in bootstrap


def test_the_mandate_refuses_only_another_session_as_a_mismatch() -> None:
    bootstrap = native_launch_bootstrap("launch-example")

    assert (
        "If registered_session_id names a different session, or the launch "
        "closed without binding you, stop and report "
        "launch_registration_mismatch to the requester."
    ) in bootstrap
    assert "If it does not, stop and report launch_registration_mismatch" not in (
        bootstrap
    )
