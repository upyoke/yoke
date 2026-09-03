"""What one starved-delivery row tells the seat to do about it.

Four shapes reach this section and each asks for something different: a
resume already in flight, a chat only its operator can open, a receipt the
plane never attempted, and an attempt that failed for a nameable reason.
The line has to separate them, because before it did a seat watching a
machine where every wake refused saw only a worker that had gone quiet.
"""

from __future__ import annotations

from dataclasses import replace

from runtime.api.domain.test_steering_fleet_report_populated_body import (
    _populated_report,
    report_body,
)
from yoke_core.domain.steering_fleet_report_starvation import StarvedDelivery


def test_a_starved_row_says_who_owes_the_next_move():
    """A CLI row names its escalation; a desktop row names its operator.

    They are different asks: one is a resume already in flight, the other
    a chat only the person reading it can open.
    """

    def row(operator_wake: bool) -> str:
        entry = StarvedDelivery(
            session_id="starved-session",
            envelope_count=2,
            oldest_seconds=2400,
            wake_escalation="starved_hook_route",
            operator_wake=operator_wake,
        )
        body = report_body(replace(_populated_report(), starved=(entry,)))
        return next(line for line in body.splitlines() if "starved-session" in line)

    assert "wake escalated (starved_hook_route)" in row(False)
    assert "waiting for the operator to wake it" in row(True)
    assert "wake escalated" not in row(True)


def test_a_starved_row_says_what_was_tried_and_how_it_ended():
    """`never injected` alone cannot separate no attempt from a failed one.

    Those need opposite moves — one says the plane skipped the receipt, the
    other names a refusal to go fix — and for two hours a seat watching a
    machine where every wake refused for one nameable reason saw neither.
    """

    def row(**overrides) -> str:
        entry = StarvedDelivery(
            session_id="starved-session",
            envelope_count=1,
            oldest_seconds=600,
            **overrides,
        )
        body = report_body(replace(_populated_report(), starved=(entry,)))
        return next(line for line in body.splitlines() if "starved-session" in line)

    assert "no delivery attempted" in row(attempt_count=0)
    assert "last attempt failed (instruction_invalid)" in row(
        attempt_count=1, diagnostic="instruction_invalid"
    )
