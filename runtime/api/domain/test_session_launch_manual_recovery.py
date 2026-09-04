"""Launch refusal points to the already-supported manual session path."""

from __future__ import annotations

from runtime.api.domain.session_launch_test_support import relay_connection
from yoke_core.domain.session_launch_types import LaunchPreview
from yoke_core.domain.session_surface_policy import launch_refusal_message


def test_no_eligible_relay_names_manual_registration_and_claim_recovery() -> None:
    message = launch_refusal_message(
        relay_connection(),
        LaunchPreview(
            outcome="no_eligible_relay",
            requested_surface="codex-cli",
            eligible_relays=(),
            rejection_codes=("liveness_expired",),
        ),
    )

    assert "yoke relay status" in message
    assert "start a normal harness session by hand" in message
    assert "yoke sessions touch --mode MODE" in message
    assert "yoke claims work acquire --item PREFIX-N" in message
    assert "no launch record is expected" in message
