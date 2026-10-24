"""HTTP bearer-to-machine binding for relay-owned function calls."""

from __future__ import annotations

from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal

MACHINE_CREDENTIAL_FUNCTIONS = frozenset(
    {
        "session_control.relay.claim",
        "session_control.relay.idle_hosts",
        "session_control.relay.liveness",
        "session_control.relay.report",
        "session_control.relay.turn_end",
    }
)


def machine_credential_refusal(
    envelope: dict[str, Any], machine_id: str | None
) -> tuple[str, str] | None:
    """Return a typed refusal when a relay call lacks its machine credential."""
    function_id = str(envelope.get("function") or "")
    if function_id not in MACHINE_CREDENTIAL_FUNCTIONS:
        return None
    if not machine_id:
        return (
            "machine_credential_required",
            compose_refusal(
                "This relay credential predates machine binding.",
                recovery="run the installer again to reconnect this machine.",
            ),
        )
    payload = envelope.get("payload")
    claimed = payload.get("machine_id") if isinstance(payload, dict) else None
    if not claimed or str(claimed).strip() != machine_id:
        return (
            "machine_credential_mismatch",
            compose_refusal(
                "The relay request must name the machine authenticated by its credential.",
                recovery="reconnect this machine with the installer.",
            ),
        )
    return None


__all__ = ["MACHINE_CREDENTIAL_FUNCTIONS", "machine_credential_refusal"]
