"""Accept hosted device codes into the shared personal-approval store."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any
from uuid import UUID

from yoke_contracts.machine_authorization import CODE_TTL_SECONDS, MATCH_CODE_PATTERN
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.hosted_service_authority import hosted_service_org_ids
from yoke_core.domain.machine_authorization_codes import (
    MachineAuthorizationError,
    SERVER_PENDING_CODES,
    _now,
    _p,
    purge_cutoff,
    refuse_retired_machine,
)


def require_service_org(conn: Any, actor_id: int, org_id: int) -> None:
    orgs = hosted_service_org_ids(conn, actor_id)
    if not orgs:
        raise MachineAuthorizationError(
            "permission_denied",
            "call with this universe's hosted service identity",
            403,
        )
    if not conn.execute(
        f"SELECT 1 FROM organizations WHERE id={_p(conn)}", (org_id,)
    ).fetchone():
        raise MachineAuthorizationError(
            "authorization_org_unknown",
            "select an existing engine organization and retry",
            404,
        )
    if org_id not in orgs:
        raise MachineAuthorizationError(
            "permission_denied",
            "use the hosted service identity for the target organization",
            403,
        )


def handoff(
    conn: Any,
    *,
    device_code_sha256: str,
    user_code: str,
    machine_id: str,
    machine_name: str,
    platform: str,
    expires_at: str,
    org_id: int,
    actor_id: int,
) -> dict[str, Any]:
    require_service_org(conn, actor_id, org_id)
    try:
        machine_id = str(UUID(machine_id))
        valid = re.fullmatch(r"[0-9a-f]{64}", device_code_sha256) and re.fullmatch(
            MATCH_CODE_PATTERN, user_code
        )
        if not valid or not machine_name.strip() or not platform.strip():
            raise ValueError("invalid code or machine facts")
    except (ValueError, TypeError, AttributeError):
        raise MachineAuthorizationError(
            "authorization_handoff_invalid",
            "send the documented SHA-256 digest, four-character match code and machine UUID/name/platform",
        ) from None
    refuse_retired_machine(conn, machine_id)
    try:
        expires = parse_instant(expires_at)
    except (ValueError, TypeError):
        raise MachineAuthorizationError(
            "authorization_expiry_invalid",
            "send a qualified RFC3339 expiry within the code TTL",
        ) from None
    # Share start's lock so collision and capacity checks serialize with it.
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext('machine_authorization_codes'))"
        )
    now, p = _now(), _p(conn)
    if expires <= now:
        raise MachineAuthorizationError(
            "authorization_expired", "issue a fresh hosted connection code", 410
        )
    if expires > now + timedelta(seconds=CODE_TTL_SECONDS):
        raise MachineAuthorizationError(
            "authorization_expiry_invalid",
            "issue a code expiring within the engine code TTL",
        )
    previous = conn.execute(
        "SELECT user_code,org_id,machine_id,machine_name,platform,expires_at,actor_id,consumed_at,decision,decided_at "
        f"FROM machine_authorization_codes WHERE device_hash={p}",
        (device_code_sha256,),
    ).fetchone()
    if previous:
        same = tuple(previous[:5]) == (
            user_code,
            org_id,
            machine_id,
            machine_name,
            platform,
        )
        pending = (
            not previous[6]
            and not previous[7]
            and previous[8] is None
            and previous[9] is None
        )
        if not (same and parse_instant(previous[5]) == expires and pending):
            raise MachineAuthorizationError(
                "device_code_taken",
                "issue a new device secret and match code, then retry handoff",
                409,
            )
        conn.commit()
        return {
            "user_code": user_code,
            "expires_at": format_instant(expires),
            "state": "pending",
        }
    conn.execute(
        f"DELETE FROM machine_authorization_codes WHERE expires_at<={p}",
        (instant_parameter(conn, purge_cutoff(now)),),
    )
    if conn.execute(
        f"SELECT 1 FROM machine_authorization_codes WHERE user_code={p}", (user_code,)
    ).fetchone():
        raise MachineAuthorizationError(
            "match_code_taken",
            "issue a new device secret and match code, then retry handoff",
            409,
        )
    count = conn.execute(
        f"SELECT count(*) FROM machine_authorization_codes WHERE consumed_at IS NULL AND expires_at>{p}",
        (instant_parameter(conn, now),),
    ).fetchone()[0]
    if count >= SERVER_PENDING_CODES:
        raise MachineAuthorizationError(
            "authorization_capacity",
            "finish an approval or retry after code expiry",
            429,
        )
    conn.execute(
        "INSERT INTO machine_authorization_codes "
        "(device_hash,user_code,org_id,expires_at,machine_id,machine_name,platform) "
        f"VALUES ({p},{p},{p},{p},{p},{p},{p})",
        (
            device_code_sha256,
            user_code,
            org_id,
            instant_parameter(conn, expires),
            machine_id,
            machine_name,
            platform,
        ),
    )
    conn.commit()
    return {
        "user_code": user_code,
        "expires_at": format_instant(expires),
        "state": "pending",
    }
