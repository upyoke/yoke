"""Ambient item-ownership guard for retained path-claim mutations.

Every mutating ``path-claims`` subcommand (``register``, ``activate``,
``widen``, ``narrow``, ``cancel-amendment``, ``release``, ``cancel``)
calls :func:`deny_if_not_owner` before reaching the resolver or
domain mutation. The guard reads the ambient harness session from the
canonical env-var chain (never from ``--session-id``, ``path_claims.
session_id``, or a function-call payload actor), looks up the active
``work_claims`` row for the parent item, and refuses the call unless
the caller holds it.

Read-only subcommands (``get``, ``list``, ``conflicts``, ``boundary``)
do not call this guard. The legacy override surface
(``path-claims override``) is operator-only and routed through its
own audit gate — ownership is intentionally not enforced there because
override is the documented escape hatch for cross-cutting ambiguity.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_dispatch_io import print_error
from yoke_core.api.service_client_shared_session_resolver import (
    current_session_id as _current_session_id,
)


class OwnershipDenial(Exception):
    """Raised when the ambient session does not own the parent item."""

    def __init__(
        self,
        *,
        action: str,
        item_id: int,
        claim_id: Optional[int],
        caller_session_id: str,
        holder_session_id: Optional[str],
    ) -> None:
        self.action = action
        self.item_id = int(item_id)
        self.claim_id = int(claim_id) if claim_id is not None else None
        self.caller_session_id = caller_session_id or ""
        self.holder_session_id = holder_session_id or None
        super().__init__(self.message)

    @property
    def message(self) -> str:
        """Build the operator-readable denial message body."""
        caller = self.caller_session_id or "<no session in env>"
        if self.holder_session_id:
            who = f"; active claim held by session {self.holder_session_id!r}"
        else:
            who = "; no active work claim exists on this item"
        recovery = (
            "acquire the work claim first: "
            "python3 -m yoke_core.api.service_client claim-work "
            f"--item YOK-{self.item_id} --reason <intent>"
        )
        inspect = (
            "python3 -m runtime.harness.harness_sessions "
            f"who-claims {self.item_id}"
        )
        return (
            f"path-claims {self.action} requires the ambient session to "
            f"hold item YOK-{self.item_id}'s work claim. "
            f"caller={caller}{who}. Recovery: {recovery}. Inspect: {inspect}."
        )

    def context(self) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {
            "action": self.action,
            "item_id": self.item_id,
            "caller_session_id": self.caller_session_id,
            "holder_session_id": self.holder_session_id,
            "recovery": (
                "python3 -m yoke_core.api.service_client claim-work "
                f"--item YOK-{self.item_id} --reason <intent>"
            ),
        }
        if self.claim_id is not None:
            ctx["claim_id"] = self.claim_id
        return ctx


def _row_value(row: Any, key: str) -> Any:
    if row is None:
        return None
    if hasattr(row, "keys"):
        return row[key]
    return row[0]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_id_for_claim(
    conn: Any, claim_id: int
) -> Optional[int]:
    p = _p(conn)
    row = conn.execute(
        f"SELECT item_id FROM path_claims WHERE id = {p}",
        (int(claim_id),),
    ).fetchone()
    value = _row_value(row, "item_id")
    if value is None:
        return None
    return int(value)


def _active_holder_session_id(
    conn: Any, item_id: int
) -> Optional[str]:
    p = _p(conn)
    row = conn.execute(
        "SELECT session_id FROM work_claims "
        f"WHERE target_kind = 'item' AND item_id = {p} "
        "AND released_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    value = _row_value(row, "session_id")
    return str(value) if value else None


def require_item_ownership(
    conn: Any,
    *,
    action: str,
    item_id: Optional[int] = None,
    claim_id: Optional[int] = None,
) -> Optional[int]:
    """Verify the ambient session holds the item's active work claim.

    Returns the resolved ``item_id`` on success. Returns ``None`` when
    *claim_id* was supplied but no such claim exists — let the calling
    handler surface its own ``NOT_FOUND`` instead of fabricating an
    ownership denial for a row that does not exist.

    Raises :class:`OwnershipDenial` when the ambient caller does not
    match the active holder (or no holder exists).
    """
    if item_id is None:
        if claim_id is None:
            raise ValueError(
                "require_item_ownership needs item_id or claim_id"
            )
        resolved = _item_id_for_claim(conn, int(claim_id))
        if resolved is None:
            return None
        item_id = resolved
    caller = _current_session_id()
    holder = _active_holder_session_id(conn, int(item_id))
    if not caller or holder != caller:
        raise OwnershipDenial(
            action=action,
            item_id=int(item_id),
            claim_id=claim_id,
            caller_session_id=caller,
            holder_session_id=holder,
        )
    return int(item_id)


def emit_denial(denial: OwnershipDenial) -> None:
    """Print the ``OWNERSHIP_DENIED`` structured error payload for *denial*."""
    print_error("OWNERSHIP_DENIED", denial.message, **denial.context())


def deny_if_not_owner(
    conn: Any,
    *,
    action: str,
    item_id: Optional[int] = None,
    claim_id: Optional[int] = None,
) -> bool:
    """Return ``True`` when the call must be refused, ``False`` to proceed.

    Combines :func:`require_item_ownership` with :func:`emit_denial`
    so every mutating handler reduces the guard to a one-liner.
    """
    try:
        require_item_ownership(
            conn, action=action, item_id=item_id, claim_id=claim_id,
        )
    except OwnershipDenial as exc:
        emit_denial(exc)
        return True
    return False


__all__ = [
    "OwnershipDenial",
    "deny_if_not_owner",
    "emit_denial",
    "require_item_ownership",
]
