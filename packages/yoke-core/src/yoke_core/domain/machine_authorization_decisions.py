"""Personal machine approval, bound immutably to a human organization member."""

from typing import Any

from yoke_contracts.timestamps import format_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.machine_authorization_codes import (
    MachineAuthorizationError,
    _now,
    _p,
    _require_member,
    _row,
)
from yoke_core.domain.machine_match_codes import normalize_match_code


def inspect(conn: Any, *, code: str, actor_id: int) -> dict[str, Any]:
    row = _row(conn, "user_code", normalize_match_code(code), inspect_closed=True)
    _require_member(conn, row["org_id"], actor_id)
    if row["actor_id"] and row["actor_id"] != actor_id:
        raise MachineAuthorizationError(
            "authorization_owner_mismatch",
            "this code belongs to another signed-in user; start your own connection",
            403,
        )
    return {
        "code": row["user_code"],
        "machine": row["machine_name"],
        "machine_id": row["machine_id"],
        "platform": row["platform"],
        "expires_at": format_instant(row["expires_at"]),
        "decision": row["decision"],
    }


def resolve(conn: Any, *, code: str, actor_id: int, action: str) -> dict[str, Any]:
    if action not in {"approve", "deny"}:
        raise MachineAuthorizationError(
            "authorization_action_invalid", "choose approve or deny"
        )
    row = _row(conn, "user_code", normalize_match_code(code), lock=True)
    _require_member(conn, row["org_id"], actor_id)
    if (
        conn.execute(
            f"SELECT kind FROM actors WHERE id={_p(conn)}", (actor_id,)
        ).fetchone()[0]
        != "human"
    ):
        raise MachineAuthorizationError(
            "authorization_human_required",
            "sign in as a person to approve your machine",
            403,
        )
    if row["actor_id"] and row["actor_id"] != actor_id:
        raise MachineAuthorizationError(
            "authorization_owner_mismatch", "start your own connection code", 403
        )
    if row["decision"]:
        if row["decision"] != action:
            raise MachineAuthorizationError(
                "authorization_already_decided",
                "start a fresh code to make a different decision",
                409,
            )
        conn.commit()
        return {"decision": row["decision"]}
    p = _p(conn)
    conn.execute(
        f"UPDATE machine_authorization_codes SET actor_id={p},decision={p},decided_at={p} WHERE device_hash={p}",
        (actor_id, action, instant_parameter(conn, _now()), row["device_hash"]),
    )
    conn.commit()
    return {"decision": action}
