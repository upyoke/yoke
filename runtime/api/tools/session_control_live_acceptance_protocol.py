"""Model instructions for deterministic Fleet live-acceptance receipts."""

from __future__ import annotations


RECEIPT_ONLY_PROTOCOL = (
    "This body requests no operational action. Process the authenticated wrapper's "
    "fixed receipt action immediately, then finish the top-level turn and wait."
)


def initial_delivery_message(*, surface: str, phase: str) -> str:
    """Return the receipt-only handshake for create and direct cells."""
    return f"Fleet live acceptance {phase} for {surface}. {RECEIPT_ONLY_PROTOCOL}"


def wake_delivery_message(*, surface: str, phase: str) -> str:
    """Return the receipt-only handshake for a stopped-session wake."""
    return f"Fleet live acceptance {phase} for {surface}. {RECEIPT_ONLY_PROTOCOL}"


__all__ = [
    "RECEIPT_ONLY_PROTOCOL",
    "initial_delivery_message",
    "wake_delivery_message",
]
