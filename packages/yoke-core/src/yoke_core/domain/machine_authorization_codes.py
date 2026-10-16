"""Single-org device codes; approval is personal and delivery is single-use."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from yoke_contracts.machine_authorization import (
    APPROVAL_PAGE_PATH,
    CODE_TTL_SECONDS,
    POLL_INTERVAL_SECONDS,
)
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain import db_backend
from yoke_core.domain.actor_state import ActorDisabledError, require_actor_active
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.machine_credentials import register_with_credential
from yoke_core.domain.machine_authorization_limits import (
    CLIENT_PENDING_CODES,
    SERVER_PENDING_CODES,
)


class MachineAuthorizationError(ValueError):
    def __init__(self, code: str, detail: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def _now() -> datetime:
    return utc_now()


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def start(
    conn: Any,
    *,
    origin: str,
    machine_id: str,
    machine_name: str,
    platform: str,
    client_key: str,
) -> dict[str, Any]:
    try:
        machine_id = str(UUID(machine_id))
    except ValueError:
        raise MachineAuthorizationError(
            "machine_identity_required",
            "restore this machine's configured UUID, then reconnect",
        ) from None
    now, p = _now(), _p(conn)
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('machine_authorization_codes'))"
        )
    conn.execute(
        f"DELETE FROM machine_authorization_codes WHERE expires_at <= {p}",
        (instant_parameter(conn, now),),
    )
    # The same transaction lock covers both capacity checks and insertion.
    count = conn.execute(
        f"SELECT count(*) FROM machine_authorization_codes WHERE client_key={p} AND consumed_at IS NULL",
        (client_key,),
    ).fetchone()[0]
    if count >= CLIENT_PENDING_CODES:
        raise MachineAuthorizationError(
            "authorization_client_capacity",
            "this client has too many pending codes; finish an approval or retry after expiry",
            429,
        )
    count = conn.execute(
        "SELECT count(*) FROM machine_authorization_codes WHERE consumed_at IS NULL"
    ).fetchone()[0]
    if count >= SERVER_PENDING_CODES:
        raise MachineAuthorizationError(
            "authorization_capacity",
            "too many pending codes; retry after ten minutes",
            429,
        )
    device = secrets.token_urlsafe(32)
    from yoke_core.domain.machine_match_codes import allocate_match_code

    code = allocate_match_code(conn)
    expires = now + timedelta(seconds=CODE_TTL_SECONDS)
    conn.execute(
        "INSERT INTO machine_authorization_codes (device_hash,user_code,org_id,expires_at,machine_id,machine_name,platform,client_key) "
        f"VALUES ({p},{p},{p},{p},{p},{p},{p},{p})",
        (
            _hash(device),
            code,
            default_org_id(conn),
            instant_parameter(conn, expires),
            machine_id,
            machine_name,
            platform,
            client_key,
        ),
    )
    conn.commit()
    uri = origin.rstrip("/") + APPROVAL_PAGE_PATH
    return {
        "device_code": device,
        "user_code": code,
        "verification_uri": uri,
        "verification_uri_complete": uri + "/" + code,
        "expires_in": CODE_TTL_SECONDS,
        "interval": POLL_INTERVAL_SECONDS,
    }


def _row(
    conn: Any, key: str, value: str, *, lock: bool = False, inspect_closed: bool = False
) -> dict[str, Any]:
    # The key is selected by our two callers, never by request data.
    suffix = " FOR UPDATE" if lock and db_backend.connection_is_postgres(conn) else ""
    names = (
        "device_hash",
        "user_code",
        "org_id",
        "expires_at",
        "actor_id",
        "machine_id",
        "machine_name",
        "consumed_at",
        "platform",
        "decision",
        "decided_at",
    )
    row = conn.execute(
        f"SELECT {','.join(names)} FROM machine_authorization_codes WHERE {key}={_p(conn)}{suffix}",
        (value,),
    ).fetchone()
    if row is None and inspect_closed:
        raise MachineAuthorizationError(
            "authorization_unavailable",
            "check the code in your terminal and try again",
            404,
        )
    if row is None or (not inspect_closed and parse_instant(row[3]) <= _now()):
        raise MachineAuthorizationError(
            "authorization_expired", "start a fresh connection code", 410
        )
    if row[7] and not inspect_closed:
        raise MachineAuthorizationError(
            "authorization_consumed",
            "this code was already delivered; start a fresh connection",
            410,
        )
    return dict(zip(names, row))


def _require_member(conn: Any, org_id: int, actor_id: int) -> None:
    try:
        require_actor_active(conn, actor_id)
    except ActorDisabledError as exc:
        raise MachineAuthorizationError("actor_disabled", str(exc), 403) from None
    p = _p(conn)
    member = conn.execute(
        f"SELECT 1 FROM actor_org_roles WHERE actor_id={p} AND org_id={p}",
        (actor_id, org_id),
    ).fetchone()
    if not member and org_id == default_org_id(conn):
        # Domain admission creates a linked actor without a role grant. On
        # this single-org door that is membership, never project authority.
        member = conn.execute(
            f"SELECT 1 FROM actor_external_identities WHERE actor_id={p}",
            (actor_id,),
        ).fetchone()
    if not member:
        raise MachineAuthorizationError(
            "organization_membership_required",
            "ask an org admin to admit your account, then sign in again",
            403,
        )


def poll(
    conn: Any, *, device_code: str, machine_id: str, machine_name: str, origin: str
) -> dict[str, Any]:
    try:
        machine_id = str(UUID(machine_id))
    except ValueError:
        raise MachineAuthorizationError(
            "machine_identity_required",
            "restore this machine's configured UUID, then reconnect",
        ) from None
    row = _row(conn, "device_hash", _hash(device_code), lock=True)
    if row["machine_id"] and row["machine_id"] != machine_id:
        raise MachineAuthorizationError(
            "machine_identity_mismatch",
            "restart connection on the original machine",
            403,
        )
    p, now = _p(conn), _now()
    conn.execute(
        f"UPDATE machine_authorization_codes SET machine_id={p},machine_name={p} WHERE device_hash={p}",
        (machine_id, machine_name, row["device_hash"]),
    )
    decision = row["decision"]
    if decision == "deny":
        conn.commit()
        raise MachineAuthorizationError(
            "authorization_denied",
            "the browser denied this code; start a fresh connection",
            410,
        )
    if decision != "approve":
        conn.commit()
        raise MachineAuthorizationError(
            "authorization_pending", "approve your machine in the browser", 202
        )
    _require_member(conn, row["org_id"], row["actor_id"])
    # Mark consumption in the same transaction the existing credential owner
    # commits: concurrent polls cannot rotate or receive a second credential.
    conn.execute(
        f"UPDATE machine_authorization_codes SET consumed_at={p} WHERE device_hash={p}",
        (instant_parameter(conn, now), row["device_hash"]),
    )
    _, _, credential = register_with_credential(
        conn,
        machine_id=machine_id,
        name=machine_name,
        actor_id=row["actor_id"],
        now=now,
    )
    org = conn.execute(
        f"SELECT slug FROM organizations WHERE id={p}", (row["org_id"],)
    ).fetchone()[0]
    return {"api_url": origin.rstrip("/"), "org": org, "token": credential.token}
