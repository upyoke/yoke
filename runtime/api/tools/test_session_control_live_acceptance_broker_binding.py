"""Preview selects only registration-eligible broker bindings."""

from __future__ import annotations

from typing import Any

from runtime.api.tools.session_control_live_acceptance_broker_binding import (
    advertised_version_from_preview,
    preview_document,
)
from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    NO_CLAIM_FREE_PAIR_CODE,
    NO_CLAIM_FREE_PAIR_RECOVERY,
    BrokerBinding,
    decide_broker_binding,
)

ADVERTISED = "0.150.0-alpha.8"
STALE_VERSION = "0.149.0-alpha.4.3"
SURFACE = "codex-cli"
MACHINE = "machine-one"


def _binding() -> BrokerBinding:
    return BrokerBinding("01a039e7-ended-target", MACHINE, "01a039f1-ended-peer")


def _row(
    session_id: str,
    *,
    liveness: str,
    version: str,
    machine_id: str = MACHINE,
    terminated_at: str | None = None,
    claims: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "project": "yoke",
        "executor_surface": SURFACE,
        "executor_version": version,
        "machine_id": machine_id,
        "liveness": liveness,
        "terminated_at": terminated_at,
        "mode": "wait",
        "claims": [] if claims is None else claims,
        "current_item": None,
        "messageability": {"hook_injection": True},
    }


def test_ended_stale_version_preview_shape_is_not_ready() -> None:
    """Reproduce the ready-over-ended stale-version pair that failed run -12."""
    binding = _binding()
    target = _row(binding.target_session_id, liveness="ended", version=STALE_VERSION)
    peer = _row(binding.peer_session_id, liveness="ended", version=STALE_VERSION)

    decision = decide_broker_binding(
        binding,
        project="yoke",
        surface=SURFACE,
        advertised_version=ADVERTISED,
        target=target,
        peer=peer,
    )

    assert decision.status == "not_ready"
    assert decision.failure_code == NO_CLAIM_FREE_PAIR_CODE
    assert decision.recovery == NO_CLAIM_FREE_PAIR_RECOVERY
    assert decision.binding == binding
    report = preview_document(
        run_id="fleet-live-acceptance-20260827-12",
        release_sha="a" * 40,
        project="yoke",
        cells=[{"session_id": binding.target_session_id}],
        decision=decision,
    )
    assert report["status"] == "not_ready"
    assert report["failure_code"] == NO_CLAIM_FREE_PAIR_CODE


def test_active_stale_version_pair_is_not_ready() -> None:
    binding = _binding()
    decision = decide_broker_binding(
        binding,
        project="yoke",
        surface=SURFACE,
        advertised_version=ADVERTISED,
        target=_row(
            binding.target_session_id, liveness="active", version=STALE_VERSION
        ),
        peer=_row(binding.peer_session_id, liveness="active", version=STALE_VERSION),
    )

    assert decision.status == "not_ready"
    assert decision.failure_code == NO_CLAIM_FREE_PAIR_CODE


def test_claim_holding_run_thirteen_shape_is_not_ready() -> None:
    binding = _binding()
    claimed = [{"target": "YOK-2540"}]
    decision = decide_broker_binding(
        binding,
        project="yoke",
        surface=SURFACE,
        advertised_version=ADVERTISED,
        target=_row(
            binding.target_session_id,
            liveness="active",
            version=ADVERTISED,
            claims=claimed,
        ),
        peer=_row(
            binding.peer_session_id,
            liveness="active",
            version=ADVERTISED,
            claims=[{"target": "YOK-2473"}],
        ),
    )

    assert decision.status == "not_ready"
    assert decision.failure_code == NO_CLAIM_FREE_PAIR_CODE
    assert "--prepare-broker" in str(decision.recovery)


def test_selection_prefers_live_current_pair_and_does_not_reuse_stale() -> None:
    binding = _binding()
    live_target = _row("live-target", liveness="active", version=ADVERTISED)
    live_peer = _row("live-peer", liveness="active", version=ADVERTISED)

    decision = decide_broker_binding(
        binding,
        project="yoke",
        surface=SURFACE,
        advertised_version=ADVERTISED,
        target=_row(binding.target_session_id, liveness="ended", version=STALE_VERSION),
        peer=_row(binding.peer_session_id, liveness="ended", version=STALE_VERSION),
        candidates=(live_target, live_peer),
    )

    assert decision.status == "ready"
    assert {decision.binding.target_session_id, decision.binding.peer_session_id} == {
        "live-target",
        "live-peer",
    }
    assert decision.binding.target_session_id != decision.binding.peer_session_id
    assert binding.target_session_id not in {
        decision.binding.target_session_id,
        decision.binding.peer_session_id,
    }


def test_preview_selected_relay_version_is_the_advertised_authority() -> None:
    assert (
        advertised_version_from_preview(
            {"selected_relay": {"version": ADVERTISED}},
            STALE_VERSION,
        )
        == ADVERTISED
    )
    assert advertised_version_from_preview({}, STALE_VERSION) == STALE_VERSION
