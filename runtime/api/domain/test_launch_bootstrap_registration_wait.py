"""``launch get`` separates registration in flight from a bound launch.

A worker waits while the launch shows no Registered session and refuses only
when it names another session, so an unbound launch must project an in-flight
correlation and a bound one must not.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.session_launch_visibility import launch_visibility

LAUNCH_REGISTRATION_IN_FLIGHT = ("pending", "awaiting_registration")


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


def test_a_recheck_that_reads_bound_to_you_proceeds() -> None:
    own = "own-session"
    correlation = _correlation("succeeded", native=own, registered=own)

    assert correlation == "matched"
    assert correlation not in LAUNCH_REGISTRATION_IN_FLIGHT


def test_only_the_id_comparison_tells_you_from_another_bound_session() -> None:
    own, other = "own-session", "other-session"
    yours = _correlation("succeeded", native=own, registered=own)
    theirs = _correlation("succeeded", native=other, registered=other)

    assert yours == theirs == "matched", (
        "correlation alone cannot separate the two; the mandate compares ids"
    )
    assert theirs not in LAUNCH_REGISTRATION_IN_FLIGHT
    assert other != own
    assert (
        _correlation("failed", native=None, registered=None)
        not in LAUNCH_REGISTRATION_IN_FLIGHT
    )

