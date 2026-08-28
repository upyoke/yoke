"""Model instructions for deterministic Fleet live-acceptance receipts."""

from __future__ import annotations


RECEIPT_ONLY_PROTOCOL = (
    "This body requests no operational action. Process the authenticated wrapper's "
    "fixed receipt action immediately, then finish the top-level turn and wait."
)


def initial_delivery_message(*, surface: str, phase: str) -> str:
    """Return the receipt-only handshake for create and direct cells."""
    return f"Fleet live acceptance {phase} for {surface}. {RECEIPT_ONLY_PROTOCOL}"


def broker_preparation_message(*, surface: str, role: str) -> str:
    """Return the handshake for a dedicated broker the run will hold alive.

    A broker exists to be woken later, so idling after the receipt is the whole
    job rather than the end of one. The session is held alive by the run that
    prepared it and needs to take no action to stay: saying so keeps a model
    from inventing busywork to look useful.
    """
    return (
        f"Fleet live acceptance dedicated broker {role} preparation for "
        f"{surface}. This session is a wake target for the acceptance run and "
        "is held alive by that run; staying idle is the whole job. "
        f"{RECEIPT_ONLY_PROTOCOL}"
    )


def wake_delivery_message(*, surface: str, phase: str) -> str:
    """Return the receipt-only handshake for a stopped-session wake."""
    return f"Fleet live acceptance {phase} for {surface}. {RECEIPT_ONLY_PROTOCOL}"


__all__ = [
    "RECEIPT_ONLY_PROTOCOL",
    "broker_preparation_message",
    "initial_delivery_message",
    "wake_delivery_message",
]
