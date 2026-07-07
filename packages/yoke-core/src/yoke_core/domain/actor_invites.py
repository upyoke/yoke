"""Actor-invite lifecycle for the self-host sign-in door.

Invites are operator-authored admission records in ``actor_invites``
(created in :mod:`yoke_core.domain.external_identity_schema`). A pending
invite admits a verified email at sign-in; acceptance happens inside the
sign-in resolution ladder, which either creates a new human actor or —
when the invite carries a target ``actor_id`` (an email pre-link) —
binds the identity to that existing actor. ``role_id`` optionally grants
an org role on acceptance.

Email matching is case-insensitive throughout; the stored ``email``
keeps the operator's original casing for display.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.external_identity_events import (
    EVENT_ACTOR_INVITE_ACCEPTED,
    EVENT_ACTOR_INVITE_CREATED,
    EVENT_ACTOR_INVITE_REVOKED,
    emit_identity_event,
)


INVITE_STATUS_PENDING = "pending"
INVITE_STATUS_ACCEPTED = "accepted"
INVITE_STATUS_REVOKED = "revoked"
INVITE_STATUSES = (
    INVITE_STATUS_PENDING,
    INVITE_STATUS_ACCEPTED,
    INVITE_STATUS_REVOKED,
)


class InviteError(Exception):
    """Base class for invite-lifecycle failures."""


class InviteNotFound(InviteError):
    """No invite row matched the given id."""


class InviteNotPending(InviteError):
    """The invite is not in the pending state the operation requires."""


class DuplicatePendingInvite(InviteError):
    """A pending invite already exists for this email in this org."""


@dataclass(frozen=True)
class Invite:
    invite_id: int
    email: str
    org_id: int
    role_id: Optional[int]
    actor_id: Optional[int]
    status: str
    invited_by_actor_id: int
    created_at: str
    accepted_at: Optional[str]
    accepted_by_actor_id: Optional[int]


_INVITE_COLUMNS = (
    "id, email, org_id, role_id, actor_id, status, invited_by_actor_id, "
    "created_at, accepted_at, accepted_by_actor_id"
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_to_invite(row: Any) -> Invite:
    return Invite(
        invite_id=int(row[0]),
        email=str(row[1]),
        org_id=int(row[2]),
        role_id=int(row[3]) if row[3] is not None else None,
        actor_id=int(row[4]) if row[4] is not None else None,
        status=str(row[5]),
        invited_by_actor_id=int(row[6]),
        created_at=str(row[7]),
        accepted_at=str(row[8]) if row[8] is not None else None,
        accepted_by_actor_id=int(row[9]) if row[9] is not None else None,
    )


def create_invite(
    conn: Any,
    *,
    email: str,
    org_id: int,
    invited_by_actor_id: int,
    role_id: Optional[int] = None,
    actor_id: Optional[int] = None,
) -> Invite:
    """Create a pending invite; at most one pending per email per org."""
    cleaned = str(email or "").strip()
    if not cleaned or "@" not in cleaned:
        raise InviteError(f"invite email must be a full address, got {cleaned!r}")
    p = _p(conn)
    existing = conn.execute(
        "SELECT id FROM actor_invites "
        f"WHERE lower(email) = lower({p}) AND org_id = {p} AND status = {p}",
        (cleaned, int(org_id), INVITE_STATUS_PENDING),
    ).fetchone()
    if existing is not None:
        raise DuplicatePendingInvite(
            f"a pending invite for {cleaned!r} already exists "
            f"(invite {int(existing[0])}); revoke it first to reissue"
        )
    cur = conn.execute(
        "INSERT INTO actor_invites "
        "(email, org_id, role_id, actor_id, status, invited_by_actor_id, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
        (
            cleaned,
            int(org_id),
            role_id,
            actor_id,
            INVITE_STATUS_PENDING,
            int(invited_by_actor_id),
            _now(),
        ),
    )
    invite_id = int(cur.fetchone()[0])
    conn.commit()
    emit_identity_event(
        EVENT_ACTOR_INVITE_CREATED,
        context={
            "invite_id": invite_id,
            "email": cleaned,
            "org_id": int(org_id),
            "role_id": role_id,
            "actor_id": actor_id,
            "invited_by_actor_id": int(invited_by_actor_id),
        },
    )
    return get_invite(conn, invite_id)


def get_invite(conn: Any, invite_id: int) -> Invite:
    p = _p(conn)
    row = conn.execute(
        f"SELECT {_INVITE_COLUMNS} FROM actor_invites WHERE id = {p}",
        (int(invite_id),),
    ).fetchone()
    if row is None:
        raise InviteNotFound(f"invite {invite_id} does not exist")
    return _row_to_invite(row)


def list_invites(
    conn: Any,
    *,
    org_id: Optional[int] = None,
    status: Optional[str] = None,
) -> List[Invite]:
    p = _p(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if org_id is not None:
        clauses.append(f"org_id = {p}")
        params.append(int(org_id))
    if status is not None:
        if status not in INVITE_STATUSES:
            raise InviteError(
                f"unknown invite status {status!r}; expected one of {INVITE_STATUSES}"
            )
        clauses.append(f"status = {p}")
        params.append(status)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT {_INVITE_COLUMNS} FROM actor_invites{where} ORDER BY id",
        tuple(params),
    ).fetchall()
    return [_row_to_invite(row) for row in rows]


def pending_invite_for_email(conn: Any, *, email: str) -> Optional[Invite]:
    """Return the oldest pending invite matching ``email`` case-insensitively.

    Matches across orgs (the invite's own ``org_id`` scopes any role grant
    on acceptance); on today's single-org universes that is the default org.
    """
    p = _p(conn)
    row = conn.execute(
        f"SELECT {_INVITE_COLUMNS} FROM actor_invites "
        f"WHERE lower(email) = lower({p}) AND status = {p} "
        "ORDER BY id LIMIT 1",
        (str(email or "").strip(), INVITE_STATUS_PENDING),
    ).fetchone()
    return _row_to_invite(row) if row is not None else None


def mark_invite_accepted(
    conn: Any, *, invite_id: int, accepted_by_actor_id: int,
) -> Invite:
    """Transition a pending invite to accepted, recording who accepted it."""
    invite = get_invite(conn, invite_id)
    if invite.status != INVITE_STATUS_PENDING:
        raise InviteNotPending(
            f"invite {invite_id} is {invite.status!r}, not pending"
        )
    p = _p(conn)
    conn.execute(
        f"UPDATE actor_invites SET status = {p}, accepted_at = {p}, "
        f"accepted_by_actor_id = {p} WHERE id = {p}",
        (INVITE_STATUS_ACCEPTED, _now(), int(accepted_by_actor_id), int(invite_id)),
    )
    conn.commit()
    emit_identity_event(
        EVENT_ACTOR_INVITE_ACCEPTED,
        severity="STATUS",
        context={
            "invite_id": int(invite_id),
            "email": invite.email,
            "org_id": invite.org_id,
            "role_id": invite.role_id,
            "accepted_by_actor_id": int(accepted_by_actor_id),
        },
    )
    return get_invite(conn, invite_id)


def revoke_invite(
    conn: Any, *, invite_id: int, revoked_by_actor_id: Optional[int] = None,
) -> Invite:
    """Transition a pending invite to revoked."""
    invite = get_invite(conn, invite_id)
    if invite.status != INVITE_STATUS_PENDING:
        raise InviteNotPending(
            f"invite {invite_id} is {invite.status!r}, not pending"
        )
    p = _p(conn)
    conn.execute(
        f"UPDATE actor_invites SET status = {p} WHERE id = {p}",
        (INVITE_STATUS_REVOKED, int(invite_id)),
    )
    conn.commit()
    emit_identity_event(
        EVENT_ACTOR_INVITE_REVOKED,
        severity="STATUS",
        context={
            "invite_id": int(invite_id),
            "email": invite.email,
            "org_id": invite.org_id,
            "revoked_by_actor_id": revoked_by_actor_id,
        },
    )
    return get_invite(conn, invite_id)


__all__ = [
    "DuplicatePendingInvite",
    "INVITE_STATUSES",
    "INVITE_STATUS_ACCEPTED",
    "INVITE_STATUS_PENDING",
    "INVITE_STATUS_REVOKED",
    "Invite",
    "InviteError",
    "InviteNotFound",
    "InviteNotPending",
    "create_invite",
    "get_invite",
    "list_invites",
    "mark_invite_accepted",
    "pending_invite_for_email",
    "revoke_invite",
]
