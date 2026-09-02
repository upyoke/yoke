"""Close an item out on the control plane the session is connected to.

The standalone merge selects the same-universe local Postgres connection
before it loads the engine, because merge admission needs a database this
process can lock. That override also decides *which build* executes every
control-plane write the close-out then makes: a non-https connection
dispatches in-process, so the evidence record and the terminal transition
are resolved by whatever engine this process imported — for a source lane,
the code as of the branch's base commit; for an installed client, whatever
wheel the machine happens to carry.

That is how a shipped gate can be inert. A contract that tightened the
done obligations landed on trunk, deployed to the fleet, and changed
nothing about the close-out every item actually runs: the next item's lane
had branched before it, so its own engine closed the item out under the
older contract, and neither the new stamp nor the new refusal ever ran.
Nothing reported a problem, because the code that would have noticed was
the code that was missing.

So the three writes that carry an item's terminal semantics — merge-queue
CI proof, execution evidence, and the transition it authorizes — go back to
the connected control plane, whose build is the one the fleet governs.
Everything the merge itself needs (admission, git, GitHub) keeps the local
authority the merge runtime bound for it.

The connected env is *bound* by that runtime rather than re-derived here,
because the override it installs replaces an explicit ``--env`` the
operator may have passed; re-reading the machine config would silently
answer with the default connection and close the item out in the wrong
universe. With no binding — a direct engine call, or a universe that never
switched — these context managers do nothing and the caller's connection
stands.
"""

from __future__ import annotations

import contextlib
import os
from contextvars import ContextVar
from typing import Any, Iterator, Optional, Sequence

from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import merge_queue_batch_receipt as queue_ci
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_terminal as terminal
from yoke_core.domain.standalone_item_merge_landed import LandedLane

_CONNECTED_ENV: ContextVar[str] = ContextVar(
    "yoke_close_out_connected_env", default=""
)


@contextlib.contextmanager
def bind_connected_control_plane(env_name: str) -> Iterator[str]:
    """Name the connection the caller selected before any merge override."""
    clean = str(env_name or "").strip()
    token = _CONNECTED_ENV.set(clean)
    try:
        yield clean
    finally:
        _CONNECTED_ENV.reset(token)


@contextlib.contextmanager
def connected_control_plane() -> Iterator[str]:
    """Select the bound connection for the duration, if one differs."""
    bound = _CONNECTED_ENV.get()
    current = os.environ.get(ENV_OVERRIDE, "").strip()
    if not bound or bound == current:
        yield current
        return
    os.environ[ENV_OVERRIDE] = bound
    try:
        yield bound
    finally:
        if current:
            os.environ[ENV_OVERRIDE] = current
        else:
            os.environ.pop(ENV_OVERRIDE, None)


def record_merge_queue_ci_evidence(
    item_id: int,
    receipt: queue_ci.BatchReceipt,
) -> Optional[str]:
    """Record one landed queue run where the terminal gate will read it."""
    with connected_control_plane():
        return queue_ci.record_batch_evidence(item_id, receipt)


def record_execution_evidence(
    *,
    item_id: int,
    outcome: Any,
    result_summary: str,
    verification_summary: str,
    verification_status: str,
    no_changes: bool,
    tree_root: str,
) -> tuple[str, str]:
    """Write the item's evidence. Returns ``(refusal, warning)``.

    A refused attempt may still have landed the row — a relayed write that
    succeeds on retry reports the failed try — so the record's own state
    answers for this merge rather than the attempt's return.
    """
    with connected_control_plane():
        write_error = evidence.record(
            item_id=item_id,
            outcome=outcome,
            result_summary=result_summary,
            verification_summary=verification_summary,
            verification_status=verification_status,
            no_changes=no_changes,
            tree_root=tree_root,
        )
        if not write_error:
            return "", ""
        if not evidence.recorded_covers_merge(item_id, outcome.merge_sha):
            return write_error, ""
    return "", (
        f"evidence write reported {write_error!r}, but the record covers "
        "this merge; close-out continued"
    )


def transition_to_done(
    *,
    item_id: int,
    source_status: str,
    repo_root: str,
    lane: LandedLane,
    session_id: str = "",
) -> str:
    """Close the item out. Returns the refusal, or empty on success."""
    with connected_control_plane():
        return terminal.transition_to_done(
            item_id=item_id,
            source_status=source_status,
            repo_root=repo_root,
            lane=lane,
            session_id=session_id,
        )


def bound_connected_env() -> Optional[str]:
    """The bound connection name, or ``None`` when nothing bound one."""
    return _CONNECTED_ENV.get() or None


__all__: Sequence[str] = (
    "bind_connected_control_plane",
    "bound_connected_env",
    "connected_control_plane",
    "record_execution_evidence",
    "record_merge_queue_ci_evidence",
    "transition_to_done",
)
