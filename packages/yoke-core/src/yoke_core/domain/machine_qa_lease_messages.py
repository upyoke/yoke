"""Explain host lease admission failures without suggesting a safety bypass."""

from __future__ import annotations

from typing import Any


ACQUIRE_HOST = (
    "Declare method_config.test_machine on your QA case and run its scoped plan "
    "to acquire the host lease before retrying the operation"
)


def invalid_lease(lease_id: int, reason: str) -> str:
    return f"You hold no usable Test Machine lease {lease_id}: {reason}. {ACQUIRE_HOST}"


def conflicting_lease(lease: Any, test_machine: str, reason: str) -> str:
    state = "active" if lease.is_active else "released or expired"
    return (
        f"You do not hold a usable lease on {test_machine}: {reason}. "
        f"Lease {lease.id} is {state}, assigned to session {lease.session_id} "
        f"and actor {lease.actor_id}. {ACQUIRE_HOST}"
    )


def held_host(lease: Any, test_machine: str) -> str:
    return (
        f"Test Machine {test_machine} is in use by another execution: lease {lease.id} "
        f"is held by session {lease.session_id} and actor {lease.actor_id}. "
        "Wait for that execution to finish before retrying this operation"
    )


def released_without_receipt(lease: Any) -> str:
    return (
        f"The lease on {lease.target.test_machine} (lease {lease.id}, session "
        f"{lease.session_id}) is released or expired, and this operation has no "
        "recorded receipt. Inspect the owning execution's capture and recover "
        "its receipt before retrying submission; do not repeat the host action"
    )
