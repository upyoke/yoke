"""Naming the authority a deploy reads GitHub Actions status through.

A stalled poll is unreadable without this. Status is read through a peer
HTTPS control plane that must fail independently of the environment under
deploy — never through the same-base sibling of an owner-only connection
(``prod-db-admin`` → ``prod``), which is the circular path that left a run
unable to observe a workflow while replacing the plane it asked.

Riding the stage's timeout budget through a transient peer outage is
deliberate — see the retry-limit comment in the poll loop — but restating
the same sentence once per retry is not. One real outage produced 37
identical lines whose only difference was a counter, and the operator
learned the outcome by reading GitHub directly. That surface is what these
messages name.
"""

from __future__ import annotations

import os
from typing import Mapping, Tuple

from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
)

GITHUB_ACTIONS_RELAY_ENV = "YOKE_GITHUB_ACTIONS_RELAY_ENV"
GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV = "YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY"

#: Independently deployed HTTPS peers for GitHub Actions status authority.
#: Same-base sibling derivation is intentionally absent.
HOSTED_STATUS_PEERS: Mapping[str, str] = {
    "prod": "stage",
    "stage": "prod",
}

#: Consecutive transport failures before the log stops repeating itself.
ESCALATE_AFTER = 3
#: How often to restate afterwards, so a long wait still shows progress.
RESTATE_EVERY = 10


def resolve_status_relay_env() -> Tuple[str | None, str]:
    """Return ``(relay_env, source_label)`` for GitHub Actions status.

    Explicit ``YOKE_GITHUB_ACTIONS_RELAY_ENV`` always wins. Otherwise an
    owner-only ``*-db-admin`` connection derives its known peer (not its
    same-base HTTPS sibling). No known peer means the caller must set the
    relay explicitly or use attended local authority.
    """
    explicit = os.environ.get(GITHUB_ACTIONS_RELAY_ENV, "").strip()
    if explicit:
        return explicit, GITHUB_ACTIONS_RELAY_ENV
    active = os.environ.get(ENV_OVERRIDE, "").strip()
    if active.endswith(DB_ADMIN_ENV_SUFFIX):
        base = active[: -len(DB_ADMIN_ENV_SUFFIX)]
        peer = HOSTED_STATUS_PEERS.get(base)
        if peer:
            return peer, f"peer of {active}"
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
            f"relay through the {relay_env!r} peer control plane "
            f"({source})"
        )
    return "relay through the connected control plane"


def should_report(consecutive: int) -> bool:
    """Whether this consecutive-failure count is worth printing."""
    if consecutive < ESCALATE_AFTER:
        return True
    return consecutive == ESCALATE_AFTER or consecutive % RESTATE_EVERY == 0


def stall_message(run_id: str, consecutive: int) -> str:
    """Explain a persistent peer-relay failure rather than restating it.

    Names the independent-failure contract and the surface that answers
    while the peer cannot.
    """
    return (
        f"  GitHub Actions status unreadable after {consecutive} consecutive "
        f"attempts via {authority_label()}. Status is read through a peer "
        "control plane that must fail independently of the environment under "
        "deploy; the run is still progressing on GitHub regardless. Check it "
        f"directly with `gh run view {run_id}`. This poll keeps retrying "
        "within its stage budget."
    )


__all__ = [
    "ESCALATE_AFTER",
    "GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV",
    "GITHUB_ACTIONS_RELAY_ENV",
    "HOSTED_STATUS_PEERS",
    "RESTATE_EVERY",
    "authority_label",
    "resolve_status_relay_env",
    "should_report",
    "stall_message",
]
