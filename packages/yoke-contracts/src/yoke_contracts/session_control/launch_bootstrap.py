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

Registration is two steps on every surface: the opening hook registers the
session, then the launch binds to it.  Where the harness names the session
before it starts (Claude, Codex) both happen in that one hook; where the
vendor assigns the id (Cursor) the relay binds the launch moments later, by
machine, surface, and workspace.  A worker that reads the launch inside that
gap sees an empty ``registered_session_id`` with ``identity_correlation``
still ``pending`` or ``awaiting_registration``.  That is registration in
flight, not a mismatch, so the check below waits a bounded number of re-reads
before it refuses; only a registered id naming another session is a mismatch.

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
    "Launch registration is automatic: your opening hook registers this "
    "session and the launch binds to it, which can finish a few seconds after "
    "you start; do not run a session registration command."
)
#: How many fresh ``launch get`` reads a worker spends on a launch whose
#: registration is still in flight before it refuses as unregistered.
LAUNCH_REGISTRATION_RECHECK_LIMIT = 10
#: ``identity_correlation`` values that mean registration is still in flight.
LAUNCH_REGISTRATION_IN_FLIGHT = ("pending", "awaiting_registration")
LAUNCH_BOOTSTRAP_MESSAGE_READ = (
    "Read `yoke sessions identity --json` and "
    "`yoke session-control launch get LAUNCH-ID --json`. Proceed only when "
    "the launch's registered_session_id matches your session id. If "
    "registered_session_id is empty and identity_correlation is "
    f"{' or '.join(LAUNCH_REGISTRATION_IN_FLIGHT)}, registration is still in "
    "flight: re-read the launch, at most "
    f"{LAUNCH_REGISTRATION_RECHECK_LIMIT} times; if it is still unbound after "
    "that, stop and report launch_registration_pending with the launch id "
    "to the requester. If "
    "registered_session_id names a different session, or the launch closed "
    "without binding you, stop and report launch_registration_mismatch to the "
    "requester. "
    "The launch's message_id names your exact mandate. Read that message with "
    "`yoke messages get MESSAGE-ID`, then acknowledge it with "
    "`yoke messages acknowledge MESSAGE-ID`. An injected receipt is absent "
    "from `yoke messages list --state pending`. If the launch has no message_id "
    "or the message cannot be read, stop and report launch_message_unavailable "
    "with the launch id; do not infer an assignment."
)
LAUNCH_BOOTSTRAP_CLAIM_FIRST = (
    "If your message assigns you a work item, acquire that item's work claim "
    "as your first work action after this handoff, before any item survey or "
    "repository reading: `yoke claims work acquire --item PREFIX-N --reason "
    '"<why you are claiming it>"`, with the assigned ref in place of '
    "PREFIX-N. That exact command is the claim surface; a spelling built "
    "from the noun phrase is not registered and the claim does not happen."
)


def native_launch_bootstrap(launch_id: str) -> str:
    """Return the launch sentence: act, claim first, and stop if unregistered."""
    return (
        f"Yoke launch `{launch_id}`: {AUTOMATIC_LAUNCH_REGISTRATION_TEACHING} "
        f"{LAUNCH_BOOTSTRAP_MESSAGE_READ.replace('LAUNCH-ID', launch_id)} "
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
    "LAUNCH_REGISTRATION_IN_FLIGHT",
    "LAUNCH_REGISTRATION_RECHECK_LIMIT",
    "native_launch_bootstrap",
    "native_launch_bootstrap_sha256",
]
