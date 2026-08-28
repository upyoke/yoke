"""Opaque native launch bootstrap shared by the launch store and relays.

The sentence a freshly spawned native reads is the only instruction it has
before it knows who it is, so it has to distinguish automatic opening-hook
registration from an action the worker must take.  A bare instruction to
"register" makes a nonexistent self-registration command an obvious guess.
It also has to be safe when the handshake does not happen: a native whose
registration silently failed must not find its own work, adopt a brief it was
never assigned, or write into a shared checkout with none of the hook guards
that a registered session runs behind.  The automatic-registration and
refusal clauses below are therefore part of the instruction, not niceties.

The claim-first clause is the other half of the same lesson.  A worker that
surveys before it claims holds nothing, and a session holding nothing is
exactly what the non-destructive session end reaps as idle: one launched
worker spent 79 tool calls reading the codebase, was auto-ended claim-free
mid-mandate, and left its item looking untouched.  Claiming first makes that
reaping structurally impossible for a worker that is actually working.

One builder, so the store that persists the prompt and the adapters that
refuse anything else cannot drift apart into two sentences that no longer
compare equal.
"""

from __future__ import annotations

import hashlib


LAUNCH_BOOTSTRAP_REFUSAL = (
    "If automatic registration does not succeed, stop: take no repository, worktree, "
    "or backlog action, and claim no work."
)
AUTOMATIC_LAUNCH_REGISTRATION_TEACHING = (
    "Launch registration is automatic in the opening hook; do not run a session "
    "registration command."
)
LAUNCH_BOOTSTRAP_CLAIM_FIRST = (
    "If your message assigns you a work item, acquire that item's work claim "
    "as your first action, before any survey or reading."
)


def native_launch_bootstrap(launch_id: str) -> str:
    """Return the launch sentence: act, claim first, and stop if unregistered."""
    return (
        f"Yoke launch `{launch_id}`: {AUTOMATIC_LAUNCH_REGISTRATION_TEACHING} "
        "Pull your message, then act. "
        f"{LAUNCH_BOOTSTRAP_CLAIM_FIRST} {LAUNCH_BOOTSTRAP_REFUSAL}"
    )


def native_launch_bootstrap_sha256(launch_id: str) -> str:
    return hashlib.sha256(
        native_launch_bootstrap(launch_id).encode("utf-8")
    ).hexdigest()


__all__ = [
    "AUTOMATIC_LAUNCH_REGISTRATION_TEACHING",
    "LAUNCH_BOOTSTRAP_CLAIM_FIRST",
    "LAUNCH_BOOTSTRAP_REFUSAL",
    "native_launch_bootstrap",
    "native_launch_bootstrap_sha256",
]
