"""Opaque native launch bootstrap shared by the launch store and relays.

The sentence a freshly spawned native reads is the only instruction it has
before it knows who it is, so it has to be safe when the rest of the
handshake does not happen.  A bootstrap that says only "register, pull your
message, act" reads, to a native whose registration silently failed, as
permission to find its own work: observed natives went on to read the
backlog, adopt briefs they were never assigned, and write code straight into
the shared checkout with no claim, no lane, and none of the hook guards that
a registered session runs behind.  The refusal clause below is therefore
part of the instruction rather than a nicety — it names stopping as the
outcome when registration does not succeed.

One builder, so the store that persists the prompt and the adapters that
refuse anything else cannot drift apart into two sentences that no longer
compare equal.
"""

from __future__ import annotations

import hashlib


LAUNCH_BOOTSTRAP_REFUSAL = (
    "If registration does not succeed, stop: take no repository, worktree, "
    "or backlog action, and claim no work."
)


def native_launch_bootstrap(launch_id: str) -> str:
    """Return the launch sentence, including its fail-safe refusal clause."""
    return (
        f"Yoke launch `{launch_id}`: register, pull your message, act. "
        f"{LAUNCH_BOOTSTRAP_REFUSAL}"
    )


def native_launch_bootstrap_sha256(launch_id: str) -> str:
    return hashlib.sha256(
        native_launch_bootstrap(launch_id).encode("utf-8")
    ).hexdigest()


__all__ = [
    "LAUNCH_BOOTSTRAP_REFUSAL",
    "native_launch_bootstrap",
    "native_launch_bootstrap_sha256",
]
