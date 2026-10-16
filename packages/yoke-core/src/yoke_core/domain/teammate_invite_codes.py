"""Atomic teammate creation and single-use machine admission."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from yoke_contracts.timestamps import parse_instant, temporal_wire, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.actor_permissions import ROLE_OPERATOR
from yoke_core.domain.actor_role_grants import grant_actor_org_role
from yoke_core.domain.actor_state import ActorDisabledError, require_actor_active
from yoke_core.domain.actors import actor_name, seed_human_actor
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.machine_credentials import register_with_credential
from yoke_core.domain.machine_registry import (
    MachineRegistryError,
    canonical_machine_id,
    get_machine,
    validate_name,
)

INVITE_TTL_SECONDS = 86400
_COLUMNS = (
    "id,actor_id,org_id,role,invited_by_actor_id,created_at,expires_at,"
    "consumed_at,consumed_machine_id,revoked_at,replaced_at"
)


class TeammateInviteError(ValueError):
    def __init__(self, code: str, detail: str, status: int = 409) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


@dataclass(frozen=True)
class CreatedInvite:
    invite: dict
    code: str = field(repr=False)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def parse_invite_code(value: str) -> str:
    code = value.strip()
    if not re.fullmatch(r"yinv_[a-z2-7]{32}", code):
        raise TeammateInviteError(
            "invite_code_invalid", "enter the complete yinv_ code your inviter sent", 404
        )
    return code


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _row(conn: Any, key: str, value: Any, *, lock: bool = False) -> dict:
    suffix = " FOR UPDATE" if lock and db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM teammate_invite_codes WHERE {key}={_p(conn)}{suffix}",
        (value,),
    ).fetchone()
    if row is None:
        raise TeammateInviteError(
            "invite_code_invalid", "invite not found; ask your inviter for a new code", 404
        )
    return dict(zip(_COLUMNS.split(","), row))


def _state(row: dict) -> str:
    if row["consumed_at"] is not None:
        return "consumed"
    if row["revoked_at"] is not None or row["replaced_at"] is not None:
        return "revoked"
    return "expired" if parse_instant(row["expires_at"]) <= utc_now() else "pending"


def _public(conn: Any, row: dict) -> dict:
    return temporal_wire({
        "invite_id": row["id"], "ref": f"code-{row['id']}", "kind": "code",
        "actor_id": row["actor_id"], "name": actor_name(conn, row["actor_id"]),
        "role": row["role"], "state": _state(row), "expires_at": row["expires_at"],
        "invited_by": actor_name(conn, row["invited_by_actor_id"]),
    })


def _request_used(conn: Any, request_id: str | None) -> bool:
    return request_id is not None and conn.execute(
        f"SELECT 1 FROM teammate_invite_codes WHERE request_id={_p(conn)}",
        (request_id,),
    ).fetchone() is not None


def _replayed() -> TeammateInviteError:
    return TeammateInviteError(
        "result_unavailable",
        "this invite result was already issued; reissue the invite to receive a new code",
    )


def _rollback(conn: Any, request_id: str | None, exc: Exception) -> None:
    conn.rollback()
    if isinstance(exc, db_backend.integrity_error_types(conn)):
        replay = _request_used(conn, request_id)
        conn.rollback()
        if replay:
            raise _replayed() from None


def _issue(conn: Any, actor_id: int, org_id: int, role: str,
           inviter_actor_id: int, request_id: str | None) -> CreatedInvite:
    now = utc_now()
    code = "yinv_" + base64.b32encode(secrets.token_bytes(20)).decode().lower()
    p = _p(conn)
    row = conn.execute(
        "INSERT INTO teammate_invite_codes "
        "(actor_id,org_id,role,code_hash,request_id,invited_by_actor_id,created_at,expires_at) "
        f"VALUES ({','.join([p] * 8)}) RETURNING id",
        (actor_id, org_id, role, _hash(code), request_id, inviter_actor_id,
         instant_parameter(conn, now),
         instant_parameter(conn, now + timedelta(seconds=INVITE_TTL_SECONDS))),
    ).fetchone()
    result = CreatedInvite(_public(conn, _row(conn, "id", row[0])), code)
    conn.commit()
    return result


def create_invite(conn: Any, *, name: str, role: str = ROLE_OPERATOR,
                  inviter_actor_id: int, request_id: str | None = None) -> CreatedInvite:
    try:
        if _request_used(conn, request_id):
            raise _replayed()
        org_id = default_org_id(conn)
        actor_id = seed_human_actor(conn, name, commit=False)
        grant_actor_org_role(
            conn, actor_id=actor_id, org_id=org_id, role_name=role,
            granted_by_actor_id=inviter_actor_id, commit=False,
        )
        return _issue(conn, actor_id, org_id, role, inviter_actor_id, request_id)
    except Exception as exc:
        _rollback(conn, request_id, exc)
        raise


def list_invites(conn: Any, *, include_used: bool = False) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM teammate_invite_codes "
        "WHERE id IN (SELECT MAX(id) FROM teammate_invite_codes GROUP BY actor_id) "
        "ORDER BY id DESC"
    ).fetchall()
    invites = [_public(conn, dict(zip(_COLUMNS.split(","), row))) for row in rows]
    return [row for row in invites if include_used or row["state"] == "pending"]


def revoke_invite(conn: Any, *, invite_id: int, actor_id: int) -> dict:
    try:
        require_actor_active(conn, actor_id)
        row = _row(conn, "id", invite_id, lock=True)
        if _state(row) == "consumed":
            raise TeammateInviteError(
                "invite_consumed", "invite already used; manage the person's machines", 410
            )
        now = utc_now()
        conn.execute(
            f"UPDATE teammate_invite_codes SET revoked_at={_p(conn)} WHERE id={_p(conn)}",
            (instant_parameter(conn, now), invite_id),
        )
        row["revoked_at"] = now
        result = _public(conn, row)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def reissue_invite(conn: Any, *, invite_id: int, actor_id: int,
                   request_id: str | None = None) -> CreatedInvite:
    try:
        if _request_used(conn, request_id):
            raise _replayed()
        row = _row(conn, "id", invite_id, lock=True)
        try:
            require_actor_active(conn, row["actor_id"], lock=True)
        except ActorDisabledError as exc:
            raise TeammateInviteError(
                "invite_reissue_disabled_actor",
                "enable the invited actor before reissuing their code",
            ) from exc
        p = _p(conn)
        conn.execute(
            f"UPDATE teammate_invite_codes SET replaced_at={p} "
            f"WHERE actor_id={p} AND consumed_at IS NULL",
            (instant_parameter(conn, utc_now()), row["actor_id"]),
        )
        return _issue(conn, row["actor_id"], row["org_id"], row["role"],
                      actor_id, request_id)
    except Exception as exc:
        _rollback(conn, request_id, exc)
        raise


def redeem_invite(conn: Any, *, code: str, machine_id: str,
                  machine_name: str, origin: str) -> dict:
    try:
        row = _row(conn, "code_hash", _hash(parse_invite_code(code)), lock=True)
        state = _state(row)
        if state != "pending":
            raise TeammateInviteError(
                f"invite_{state}", f"invite {state}; ask your inviter for a new code", 410
            )
        try:
            require_actor_active(conn, row["actor_id"], lock=True)
        except ActorDisabledError as exc:
            raise TeammateInviteError(
                "invite_actor_disabled", "ask an org admin to enable the invited actor", 403
            ) from exc
        try:
            machine_id = canonical_machine_id(machine_id)
            machine_name = validate_name(machine_name)
        except MachineRegistryError as exc:
            raise TeammateInviteError(
                "machine_identity_required",
                "restore this machine's configured UUID and name, then reconnect", 400,
            ) from exc
        machine = get_machine(conn, machine_id)
        if machine is not None and machine.owner_actor_id != row["actor_id"]:
            raise TeammateInviteError(
                "invite_machine_owned",
                "this machine belongs to another actor; reconnect with a fresh machine UUID",
            )
        p, now = _p(conn), utc_now()
        org = conn.execute(
            f"SELECT slug FROM organizations WHERE id={p}", (row["org_id"],)
        ).fetchone()[0]
        conn.execute(
            f"UPDATE teammate_invite_codes SET consumed_at={p},consumed_machine_id={p} "
            f"WHERE id={p}", (instant_parameter(conn, now), machine_id, row["id"]),
        )
        _, _, credential = register_with_credential(
            conn, machine_id=machine_id, name=machine_name,
            actor_id=row["actor_id"], now=now,
        )
        return {"api_url": origin.rstrip("/"), "org": org, "token": credential.token}
    except Exception:
        conn.rollback()
        raise
