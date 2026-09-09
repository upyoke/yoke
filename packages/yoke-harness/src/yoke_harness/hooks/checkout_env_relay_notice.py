"""Explain a relayed registration denial the server could not diagnose.

The server denies a hook event that carries no project id, but the reason
it carries none lives only on this machine: the checkout→project mapping is
recorded per connection env, so switching universes leaves the mapping
behind and the client resolves nothing to send. The server sees an absent
id and says so; only the client can say which env the checkout is actually
registered under, so the client attaches that to the denial it prints.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_config.checkout_env_mismatch import (
    MISMATCH_PREFIX,
    mismatch_note,
)

from yoke_harness.hooks.denial_notice import annotate_denial
from yoke_harness.hooks.identity_relay import workspace_path_candidates


def checkout_env_mismatch_notice(payload: dict[str, Any]) -> str:
    """Diagnose the first workspace candidate that names another env."""
    for value in workspace_path_candidates(payload):
        note = mismatch_note(value)
        if note:
            return note
    return ""


def annotate_checkout_env_mismatch(
    stdout: str,
    payload: dict[str, Any],
    project_id: object,
) -> str:
    """Add the mismatch diagnosis when the relay had no project id to send."""
    if project_id is not None:
        return stdout
    return annotate_denial(
        stdout,
        checkout_env_mismatch_notice(payload),
        marker=MISMATCH_PREFIX,
    )


__all__ = ["annotate_checkout_env_mismatch", "checkout_env_mismatch_notice"]
