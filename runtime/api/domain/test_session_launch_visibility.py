"""Instruction delivery survives the launch outcome that follows acknowledgement."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_launch_visibility import launch_visibility


@pytest.mark.parametrize(
    ("state", "result_code", "phase", "expected"),
    [
        ("failed", "abandoned_without_claim", "registered_and_acknowledged", "delivered"),
        ("failed", "abandoned_without_claim", "awaiting_registration", "not_delivered"),
        ("failed", "launch_work_claim_missing", None, "delivered"),
        ("cancelled", "cancelled_session_ended", None, "not_delivered"),
        (
            "awaiting_registration",
            "injected_awaiting_acknowledgement",
            None,
            "awaiting_acknowledgement",
        ),
        ("awaiting_registration", "launch_work_claim_pending", None, "delivered"),
    ],
)
def test_instruction_delivery_reads_the_acknowledgement_evidence(
    state: str, result_code: str, phase: str | None, expected: str
) -> None:
    visibility = launch_visibility(
        state=state,
        result_code=result_code,
        native_session_id="worker",
        registered_session_id="worker",
        launch_phase_reached=phase,
    )

    assert visibility["instruction_delivery"] == expected
