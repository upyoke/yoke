"""What a landing that exhausted its poll budget tells the operator.

Running out of poll budget is not a failure: the queue may still merge the
pull request, and re-running the landing converges on whatever happened
meanwhile. What made the printed retry unusable was the item work claim.
A landing polls for tens of minutes without emitting a line, so the
stale-session sweep saw a session with no activity, reclaimed it, and
released the claim the retry needs — then the timeout text said "re-run
the landing" without mentioning that the retry would now refuse for want
of a claim, and the operator had to discover an undocumented re-acquire.

Two things keep that from repeating. The poll loop refreshes the session
heartbeat while it waits (:mod:`yoke_core.domain.session_liveness_pump`),
so the claim survives a wait that is doing exactly what it was asked to
do; and the message built here reads the claim as it actually is at the
moment of the timeout, then prints a command that runs as-is from that
state — naming the re-acquire step only when the claim is genuinely gone.
"""

from __future__ import annotations

import shlex
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef

# Said when the caller passed no command of its own: the landing is
# reachable from more than one operator surface, and inventing a command
# the caller never ran is worse than naming the one they did.
GENERIC_RESUME = "the landing command you ran"


def merge_item_resume_command(item_ref: str, args: Any) -> str:
    """The exact ``yoke merge item`` command that resumes this landing.

    Built from the arguments the caller actually ran, because the
    close-out flags are part of what makes a retry succeed: an item whose
    terminal transition is evidence-gated refuses a retry that dropped
    ``--result`` or ``--verification``. ``args`` is the parsed
    ``yoke merge item`` namespace, read by attribute so the builder stays
    indifferent to flags it does not reproduce.
    """
    parts = ["yoke", "merge", "item", str(item_ref)]
    for flag, attr in (
        ("--project", "project"),
        ("--target", "target"),
        ("--result", "result"),
        ("--verification", "verification"),
    ):
        value = str(getattr(args, attr, "") or "")
        if value:
            parts.extend([flag, shlex.quote(value)])
    status = str(getattr(args, "verification_status", "") or "")
    if status and status != "passed":
        parts.extend(["--verification-status", shlex.quote(status)])
    for flag, attr in (
        ("--no-changes", "no_changes"),
        ("--skip-status", "skip_status"),
        ("--pr", "pr"),
        ("--json", "json"),
    ):
        if bool(getattr(args, attr, False)):
            parts.append(flag)
    return " ".join(parts)


def _holder(
    item_id: int, dispatch: Callable[..., Any]
) -> tuple[Optional[dict], str]:
    """Read the item's live work-claim holder, or why it could not be read."""
    try:
        response = dispatch(
            function_id="claims.work.holder_get",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={},
        )
    except Exception as exc:  # noqa: BLE001 - a read failure is reportable
        return None, str(exc)
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        return None, (
            getattr(error, "message", None) or "work-claim lookup failed"
        )
    holder = (getattr(response, "result", None) or {}).get("holder")
    return (holder or None), ""


def _ambient_session_id() -> str:
    """The session this landing runs under, or empty when it has none."""
    try:
        from yoke_contracts.session_identity import resolve_ambient_session_id

        return str(resolve_ambient_session_id() or "")
    except Exception:  # noqa: BLE001 - identity is evidence, never a failure
        return ""


def claim_state_clause(
    *,
    item_id: int,
    item_ref: str,
    dispatch: Callable[..., Any],
) -> str:
    """One sentence naming the claim state and what it means for the retry.

    Ends on the transition into the resume command, so the caller can
    print the command straight after it.
    """
    holder, error = _holder(item_id, dispatch)
    if error:
        return (
            f"the item work claim could not be read ({error}) — confirm it "
            f"with `yoke claims work holder-get {item_ref}`, then run"
        )
    if holder is None:
        return (
            "the item work claim is no longer held — re-acquire it with "
            f"`yoke claims work acquire --item {item_ref} --reason "
            '"resume landing"`, then run'
        )
    holder_session = str(holder.get("session_id") or "")
    ambient = _ambient_session_id()
    # Only a resolved, differing identity proves the claim belongs to
    # someone else; an unresolvable one means the message cannot tell, and
    # guessing "another session" would send the operator coordinating with
    # a session that is in fact itself.
    if ambient and holder_session and holder_session != ambient:
        return (
            f"the item work claim is held by another session "
            f"({holder_session}) — coordinate with it before running"
        )
    return (
        f"the item work claim is still held (claim {holder.get('claim_id')}), "
        "so nothing needs re-acquiring — run"
    )


def timeout_message(
    *,
    pr_num: str,
    deadline_seconds: float,
    item_id: int,
    item_ref: str,
    resume_command: str,
    dispatch: Callable[..., Any],
    last_observed: str = "",
) -> str:
    """The operator-facing text for one poll-budget timeout.

    ``last_observed`` is the poll's final reading of the pull request. It
    is what separates a wait worth resuming from one that could never have
    merged, so the message states it rather than sending the operator to
    GitHub to find out whether re-running is the right move at all.
    """
    clause = claim_state_clause(
        item_id=item_id, item_ref=item_ref, dispatch=dispatch,
    )
    observed = (
        f"last observed {last_observed}. " if last_observed
        else "The poll read nothing conclusive. "
    )
    return (
        f"pull request {pr_num} did not merge within "
        f"{int(deadline_seconds)}s; {observed}The queue may still merge it, "
        "and re-running the landing converges on the merge if it does. "
        f"Address what that reading reports, then {clause}: "
        f"{resume_command or GENERIC_RESUME}"
    )


__all__ = [
    "GENERIC_RESUME",
    "claim_state_clause",
    "merge_item_resume_command",
    "timeout_message",
]
