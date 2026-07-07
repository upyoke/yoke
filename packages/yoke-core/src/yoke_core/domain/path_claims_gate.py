"""Activation-gate check for upstream consumers of path claims.

The lifecycle module in :mod:`path_claims` owns boundary transitions;
this small companion exposes the question consumer surfaces (the
worktree creator, the scheduler, future executor pre-flight steps)
need to ask before opening a write surface against an item:

    Has every path claim attached to this item reached ``active``
    (or terminated cleanly), or is there still a ``planned`` /
    ``blocked`` claim that has not acquired the door lock?

:func:`check_worktree_create_gate` is wired into
``yoke_core.domain.worktree_create.create_worktree`` so a worktree
cannot be created for an item whose path claim is not yet activated.

The check is fail-open against environments without the
``path_claims`` table — the actor / path-claim substrate ships in
the schema but minimal-fixture tests and freshly-cloned-without-init
checkouts may not have it yet. Production paths always go through
``schema_init.cmd_init`` which creates the tables, so the fail-open
branch is for tooling robustness rather than a production guarantee.
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_core.domain import db_backend


class PathClaimGateBlocked(Exception):
    """A path claim attached to the item is not yet activated.

    Raised by :func:`check_worktree_create_gate` so the worktree
    creator can surface a structured ``CreateWorktreeResult.error``
    rather than letting a ``planned`` claim quietly let the worktree
    open. The exception message names the offending claim ids and
    states so the operator can route to ``activate`` (or cancel and
    re-register).
    """


_NON_ACTIVE_NON_TERMINAL = ("planned", "blocked")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def gate_state_for_item(
    conn: Any,
    item_id: int,
) -> Optional[List[tuple[int, str]]]:
    """Return the non-active, non-terminal claims for an item, or ``None``.

    ``None`` indicates the gate cannot be evaluated — typically the
    ``path_claims`` table is absent on a minimal test fixture. An
    empty list indicates the gate is clear (no claims exist for the
    item, or every claim is ``active`` / ``released`` / ``cancelled``).
    A non-empty list of ``(claim_id, state)`` pairs is what blocks the
    consumer.
    """
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT id, state FROM path_claims "
            f"WHERE item_id = {p} AND state IN ('planned', 'blocked')",
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types():
        # ``path_claims`` absent (minimal fixture / fresh checkout). On
        # Postgres the UndefinedTable aborts the transaction, so roll back
        # to leave the connection usable for any caller that shares it.
        try:
            conn.rollback()
        except db_backend.operational_error_types():
            pass
        return None
    return [(int(row[0]), str(row[1])) for row in rows]


def check_worktree_create_gate(
    conn: Any,
    item_id: int,
) -> None:
    """Raise :class:`PathClaimGateBlocked` when worktree creation is gated.

    Consumers (worktree-create, scheduler) call this before opening a
    write surface against the item. The gate is silent when no claims
    exist, when every claim is ``active`` / ``released`` /
    ``cancelled``, or when the ``path_claims`` table itself is absent
    (minimal-fixture tooling). Otherwise the exception names the
    offending claim ids and states so the operator can route to
    ``activate``.
    """
    pending = gate_state_for_item(conn, item_id)
    if not pending:
        return
    summary = ", ".join(f"id={cid} state={state}" for cid, state in pending)
    raise PathClaimGateBlocked(
        f"item {item_id} has unreleased path claim(s) that have not "
        f"acquired the door lock: {summary}. Activate or cancel before "
        "opening a worktree."
    )


__all__ = [
    "PathClaimGateBlocked",
    "check_worktree_create_gate",
    "gate_state_for_item",
]
