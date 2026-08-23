"""Model instructions for deterministic Fleet live-acceptance receipts."""

from __future__ import annotations


INITIAL_REINJECTION_PROTOCOL = (
    "On the first receipt wrapper, do not acknowledge. In this registered "
    "top-level session, run exactly `pwd` once through the native shell tool; "
    "do not delegate. When the same receipt wrapper reappears after that probe, "
    "acknowledge it with that wrapper's command. Then finish the top-level turn "
    "and wait."
)
IMMEDIATE_ACK_PROTOCOL = (
    "Acknowledge this receipt with its wrapper command, then finish the top-level "
    "turn and wait."
)


def initial_delivery_message(*, surface: str, phase: str) -> str:
    """Return one shared first-delivery handshake for create and direct cells."""
    return (
        f"Fleet live acceptance {phase} for {surface}. {INITIAL_REINJECTION_PROTOCOL}"
    )


def wake_delivery_message(*, surface: str, phase: str) -> str:
    """Return the immediate-ack instruction for a stopped-session wake receipt."""
    return f"Fleet live acceptance {phase} for {surface}. {IMMEDIATE_ACK_PROTOCOL}"


__all__ = [
    "IMMEDIATE_ACK_PROTOCOL",
    "INITIAL_REINJECTION_PROTOCOL",
    "initial_delivery_message",
    "wake_delivery_message",
]
