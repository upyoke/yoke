"""Naming the authority a deploy reads GitHub Actions status through.

Live delivery reads GitHub through the project's own control plane — the
https sibling of an owner-only ``*-db-admin`` connection — never through
an independently deployed peer. Stage is a test environment for the live
plane, not part of live topology.

A same-plane restart is survived by the poll loop's transport retries;
GitHub itself remains the independent failure surface. Check the Actions
UI while the plane is coming back.
"""

from __future__ import annotations

import os
from typing import Tuple

from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
)

GITHUB_ACTIONS_RELAY_ENV = "YOKE_GITHUB_ACTIONS_RELAY_ENV"
GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV = "YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY"

#: Consecutive transport failures before the log stops repeating itself.
ESCALATE_AFTER = 3
#: How often to restate afterwards, so a long wait still shows progress.
RESTATE_EVERY = 10


def resolve_status_relay_env() -> Tuple[str | None, str]:
    """Return ``(relay_env, source_label)`` for GitHub Actions status.

    Explicit ``YOKE_GITHUB_ACTIONS_RELAY_ENV`` always wins. Otherwise an
    owner-only ``*-db-admin`` connection relays through its own https
    sibling (the plane that holds the project's App binding), not a peer.
    No sibling means the caller must set the relay explicitly or use
    attended local authority.
    """
    explicit = os.environ.get(GITHUB_ACTIONS_RELAY_ENV, "").strip()
    if explicit:
        return explicit, GITHUB_ACTIONS_RELAY_ENV
    active = os.environ.get(ENV_OVERRIDE, "").strip()
    if active.endswith(DB_ADMIN_ENV_SUFFIX):
        base = active[: -len(DB_ADMIN_ENV_SUFFIX)]
        if base:
            return base, f"owning plane of {active}"
    return None, ""


def authority_label() -> str:
    """Name the path GitHub status is being read through."""
    if os.environ.get(GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, "").strip() == "1":
        return "local GitHub App authority (attended)"
    relay_env, source = resolve_status_relay_env()
    if relay_env:
        if source == GITHUB_ACTIONS_RELAY_ENV:
            return f"relay through the {relay_env!r} control plane"
        return (
            f"relay through the {relay_env!r} owning control plane "
            f"({source})"
        )
    return "relay through the connected control plane"


def should_report(consecutive: int) -> bool:
    """Whether this consecutive-failure count is worth printing."""
    if consecutive < ESCALATE_AFTER:
        return True
    return consecutive == ESCALATE_AFTER or consecutive % RESTATE_EVERY == 0


def stall_message(run_id: str, consecutive: int) -> str:
    """Explain a persistent owning-plane failure rather than restating it.

    Names the own-plane contract and the surface that answers while the
    plane cannot (a restart, not a test-environment peer).
    """
    return (
        f"  GitHub Actions status unreadable after {consecutive} consecutive "
        f"attempts via {authority_label()}. Status is read through the "
        "project's own control plane; the run is still progressing on "
        f"GitHub regardless. Check it directly in the GitHub Actions UI "
        f"for run {run_id}. This poll keeps retrying within its stage "
        "budget."
    )


__all__ = [
    "ESCALATE_AFTER",
    "GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV",
    "GITHUB_ACTIONS_RELAY_ENV",
    "RESTATE_EVERY",
    "authority_label",
    "resolve_status_relay_env",
    "should_report",
    "stall_message",
]
