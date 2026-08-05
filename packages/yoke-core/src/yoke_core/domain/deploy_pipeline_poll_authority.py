"""Naming the authority a deploy reads GitHub Actions status through.

A stalled poll is unreadable without this. The status path can be a relay
through a control plane or a local App authority, the two fail for entirely
different reasons, and neither announces itself. Worse, the relay target can
be the very thing the deployment is replacing: a deploy whose own target is
the control plane it asks for status cannot observe itself until it finishes,
so the failure is self-sustaining rather than transient.

Riding the stage's timeout budget through that window is deliberate — see the
retry-limit comment in the poll loop — but restating the same sentence once
per retry is not. One real outage produced 37 identical lines whose only
difference was a counter, and the operator learned the outcome by reading
GitHub directly. That surface is what these messages name.
"""

from __future__ import annotations

import os

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


def authority_label() -> str:
    """Name the path GitHub status is being read through."""
    if os.environ.get(GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, "").strip() == "1":
        return "local GitHub App authority (attended)"
    relay_env = os.environ.get(GITHUB_ACTIONS_RELAY_ENV, "").strip()
    if not relay_env:
        active_env = os.environ.get(ENV_OVERRIDE, "").strip()
        if active_env.endswith(DB_ADMIN_ENV_SUFFIX):
            relay_env = active_env[: -len(DB_ADMIN_ENV_SUFFIX)]
    if relay_env:
        return f"relay through the {relay_env!r} control plane"
    return "relay through the connected control plane"


def should_report(consecutive: int) -> bool:
    """Whether this consecutive-failure count is worth printing."""
    if consecutive < ESCALATE_AFTER:
        return True
    return consecutive == ESCALATE_AFTER or consecutive % RESTATE_EVERY == 0


def stall_message(run_id: str, consecutive: int) -> str:
    """Explain a persistent relay failure rather than restating it.

    Names the dependency that makes the failure self-sustaining, and the
    surface that answers independently — which is what an operator actually
    needs while waiting.
    """
    return (
        f"  GitHub Actions status unreadable after {consecutive} consecutive "
        f"attempts via {authority_label()}. Status is read through the "
        "control plane, so a deployment targeting that same control plane "
        "cannot observe itself until it completes; the run is still "
        f"progressing on GitHub regardless. Check it directly with `gh run "
        f"view {run_id}`. This poll keeps retrying within its stage budget."
    )


__all__ = [
    "ESCALATE_AFTER",
    "GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV",
    "GITHUB_ACTIONS_RELAY_ENV",
    "RESTATE_EVERY",
    "authority_label",
    "should_report",
    "stall_message",
]
