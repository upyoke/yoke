"""Durable database CONNECT fence for attended source-authority cutover."""

from __future__ import annotations

import time
from typing import Any

from psycopg import errors
from yoke_core.domain.source_authority_connect_policy import (
    FENCE_POLICY_SCHEMA,
    FENCE_STATE_SCHEMA,
    FENCE_STATE_TABLE,
    SourceConnectFenceError,
    admin_memberships,
    clear_connect_grants as _clear_connect_grants,
    connect_policy,
    create_fence_state as _create_fence_state,
    decode_policy as _decode_policy,
    drop_fence_state as _drop_fence_state,
    fence_state,
    grant_connect as _grant_connect,
    login_role_access,
)


PROVIDER_SUPERUSER_BYPASS_ROLES = frozenset({"rdsadmin"})


def install_connect_fence(
    conn: object, *, frozen_at: str, service_stop_receipt: str,
) -> dict[str, Any]:
    """Install an owner-only CONNECT fence inside the caller's transaction."""
    if fence_state(conn) is not None:
        raise SourceConnectFenceError("source authority is already quiesced")
    original = connect_policy(conn)
    admin_role = str(original["admin_role"])
    owner_role = str(original["owner_role"])
    if admin_role != owner_role:
        raise SourceConnectFenceError(
            "source fence requires current admin to own the database"
        )
    unsupported_grantors = sorted({
        str(entry["grantor"])
        for entry in original["connect_entries"]
        if entry["grantor"] != admin_role
    })
    if unsupported_grantors:
        raise SourceConnectFenceError(
            "source CONNECT policy has grantors the database owner cannot "
            f"replay exactly: {unsupported_grantors}"
        )
    memberships = admin_memberships(conn)
    required_memberships = {"pg_read_all_stats", "pg_signal_backend"}
    missing_memberships = sorted(required_memberships - set(memberships))
    if missing_memberships:
        raise SourceConnectFenceError(
            "source admin lacks required fence memberships: "
            + ", ".join(missing_memberships)
        )

    database = str(original["database"])
    _create_fence_state(
        conn, original=original, frozen_at=frozen_at,
        service_stop_receipt=service_stop_receipt,
    )
    _clear_connect_grants(conn, database)
    _grant_connect(
        conn, database=database, grantee=admin_role, grantable=True,
    )
    access = login_role_access(conn, admin_role=admin_role)
    _validate_privileged_role_shape(access, admin_role=admin_role)
    blocked = _ordinary_bypass_roles(access, admin_role=admin_role)
    if blocked:
        raise SourceConnectFenceError(
            "CONNECT fence left ordinary login roles with effective access: "
            + ", ".join(blocked)
        )
    return {
        "schema": FENCE_POLICY_SCHEMA,
        "active": False,
        "staged": True,
        "database": database,
        "database_oid": int(original["database_oid"]),
        "admin_role": admin_role,
        "original_datacl_was_null": bool(original["datacl_was_null"]),
        "original_connect_entries": original["connect_entries"],
        "login_role_access": access,
        "admin_memberships": memberships,
        "admin_can_signal_backends": True,
        "admin_can_observe_all_sessions": True,
        "provider_superuser_bypass_roles": _superuser_roles(access),
    }


def drain_and_prove_connect_fence(conn: object) -> dict[str, Any]:
    """Drain only after the ACL commit, then prove the durable boundary."""
    state = fence_state(conn)
    if state is None:
        raise SourceConnectFenceError("source CONNECT fence is not durable")
    original = _decode_policy(state["policy"])
    admin_role = str(original["admin_role"])
    access = login_role_access(conn, admin_role=admin_role)
    _validate_privileged_role_shape(access, admin_role=admin_role)
    blocked = _ordinary_bypass_roles(access, admin_role=admin_role)
    if blocked:
        raise SourceConnectFenceError(
            "durable CONNECT fence permits ordinary roles: " + ", ".join(blocked)
        )
    memberships = admin_memberships(conn)
    required_memberships = {"pg_read_all_stats", "pg_signal_backend"}
    missing_memberships = sorted(required_memberships - set(memberships))
    if missing_memberships:
        raise SourceConnectFenceError(
            "source admin lost required drain memberships: "
            + ", ".join(missing_memberships)
        )
    terminated = terminate_unauthorized_sessions(conn, admin_role=admin_role)
    sessions = _wait_for_session_drain(conn, admin_role=admin_role)
    if sessions:
        provider = [entry["role"] for entry in sessions if entry["superuser"]]
        if provider:
            raise SourceConnectFenceError(
                "provider-superuser sessions require attended external drain: "
                + ", ".join(provider)
            )
        raise SourceConnectFenceError(
            "CONNECT fence could not drain other sessions: "
            + ", ".join(entry["role"] for entry in sessions)
        )
    status = connect_fence_status(conn)
    if not status["active"]:
        raise SourceConnectFenceError("durable CONNECT fence proof failed")
    return {
        **status,
        "terminated_other_sessions": terminated,
    }


def connect_fence_status(conn: object) -> dict[str, Any]:
    """Prove the durable fence, effective memberships, and live sessions."""
    state = fence_state(conn)
    if state is None:
        return {"schema": FENCE_POLICY_SCHEMA, "active": False}
    original = _decode_policy(state["policy"])
    current = connect_policy(conn)
    if (
        int(current["database_oid"]) != int(original["database_oid"])
        or current["admin_role"] != original["admin_role"]
    ):
        raise SourceConnectFenceError(
            "stored CONNECT fence belongs to a different database authority"
        )
    admin_role = str(original["admin_role"])
    access = login_role_access(conn, admin_role=admin_role)
    _validate_privileged_role_shape(access, admin_role=admin_role)
    blocked = _ordinary_bypass_roles(access, admin_role=admin_role)
    sessions = unauthorized_sessions(conn, admin_role=admin_role)
    memberships = admin_memberships(conn)
    required_memberships = {"pg_read_all_stats", "pg_signal_backend"}
    missing_memberships = sorted(required_memberships - set(memberships))
    active = not blocked and not sessions and not missing_memberships
    return {
        "schema": FENCE_POLICY_SCHEMA,
        "active": active,
        "database": current["database"],
        "database_oid": int(current["database_oid"]),
        "admin_role": admin_role,
        "original_datacl_was_null": bool(original["datacl_was_null"]),
        "original_connect_entries": original["connect_entries"],
        "login_role_access": access,
        "admin_memberships": memberships,
        "admin_can_signal_backends": "pg_signal_backend" in memberships,
        "admin_can_observe_all_sessions": "pg_read_all_stats" in memberships,
        "missing_admin_memberships": missing_memberships,
        "ordinary_bypass_roles": blocked,
        "provider_superuser_bypass_roles": _superuser_roles(access),
        "unauthorized_sessions": sessions,
    }


def restore_connect_fence(conn: object) -> dict[str, Any]:
    """Replay the exact saved effective CONNECT policy transactionally."""
    state = fence_state(conn)
    if state is None:
        raise SourceConnectFenceError("source authority is not quiesced")
    original = _decode_policy(state["policy"])
    current = connect_policy(conn)
    if (
        int(current["database_oid"]) != int(original["database_oid"])
        or current["admin_role"] != original["admin_role"]
    ):
        raise SourceConnectFenceError(
            "stored CONNECT policy cannot be restored by this authority"
        )
    database = str(original["database"])
    _clear_connect_grants(conn, database)
    for entry in original["connect_entries"]:
        _grant_connect(
            conn, database=database, grantee=str(entry["grantee"]),
            grantable=bool(entry["is_grantable"]),
        )
    restored = connect_policy(conn)
    if restored["connect_entries"] != original["connect_entries"]:
        raise SourceConnectFenceError(
            "restored CONNECT policy does not match the saved policy"
        )
    _drop_fence_state(conn)
    return {
        "schema": FENCE_POLICY_SCHEMA,
        "active": False,
        "database": database,
        "database_oid": int(original["database_oid"]),
        "admin_role": original["admin_role"],
        "original_datacl_was_null": bool(original["datacl_was_null"]),
        "effective_connect_policy_restored": True,
        "connect_entries": restored["connect_entries"],
    }


def terminate_unauthorized_sessions(conn: object, *, admin_role: str) -> int:
    terminated = 0
    for session in unauthorized_sessions(conn, admin_role=admin_role):
        if session["superuser"]:
            continue
        try:
            stopped = conn.execute(
                "SELECT pg_terminate_backend(%s, %s)",
                (session["pid"], 5000),
            ).fetchone()[0]
        except errors.InsufficientPrivilege as exc:
            raise SourceConnectFenceError(
                "source admin lacks pg_signal_backend authority required to "
                f"terminate role {session['role']!r}"
            ) from exc
        if not stopped:
            raise SourceConnectFenceError(
                "PostgreSQL did not terminate unauthorized session "
                f"pid={session['pid']} role={session['role']!r}"
            )
        terminated += 1
    return terminated


def unauthorized_sessions(
    conn: object, *, admin_role: str,
) -> list[dict[str, Any]]:
    # PostgreSQL caches statistics views for the current transaction.  Drain
    # proof must observe backend termination, not the pre-termination snapshot.
    conn.execute("SELECT pg_stat_clear_snapshot()")
    return [
        {"pid": int(row[0]), "role": str(row[1]), "superuser": bool(row[2])}
        for row in conn.execute(
            "SELECT a.pid, COALESCE(a.usename, '<unknown>'), "
            "COALESCE(r.rolsuper, false) FROM pg_stat_activity a "
            "LEFT JOIN pg_roles r ON r.rolname=a.usename "
            "WHERE a.datname=current_database() "
            "AND a.backend_type='client backend' "
            "AND a.pid<>pg_backend_pid() "
            "ORDER BY a.pid",
        ).fetchall()
    ]


def _wait_for_session_drain(
    conn: object, *, admin_role: str, timeout_seconds: float = 5.0,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        sessions = unauthorized_sessions(conn, admin_role=admin_role)
        if not sessions or any(entry["superuser"] for entry in sessions):
            return sessions
        if time.monotonic() >= deadline:
            return sessions
        time.sleep(0.05)


def _ordinary_bypass_roles(
    access: list[dict[str, Any]], *, admin_role: str,
) -> list[str]:
    return [
        str(entry["role"]) for entry in access
        if entry["role"] != admin_role
        and not entry["superuser"]
        and entry["effective_connect"]
    ]


def _superuser_roles(access: list[dict[str, Any]]) -> list[str]:
    return [str(entry["role"]) for entry in access if entry["superuser"]]


def _validate_privileged_role_shape(
    access: list[dict[str, Any]], *, admin_role: str,
) -> None:
    superusers = set(_superuser_roles(access))
    unexpected_superusers = sorted(superusers - PROVIDER_SUPERUSER_BYPASS_ROLES)
    allowed_members = {admin_role} | PROVIDER_SUPERUSER_BYPASS_ROLES
    unexpected_members = sorted(
        str(entry["role"]) for entry in access
        if entry["inherits_admin"] and entry["role"] not in allowed_members
    )
    if unexpected_superusers or unexpected_members:
        raise SourceConnectFenceError(
            "source privileged role shape is not approved "
            f"(unexpected_superusers={unexpected_superusers}, "
            f"unexpected_admin_members={unexpected_members})"
        )


__all__ = [
    "FENCE_POLICY_SCHEMA", "FENCE_STATE_SCHEMA", "FENCE_STATE_TABLE",
    "PROVIDER_SUPERUSER_BYPASS_ROLES",
    "SourceConnectFenceError", "admin_memberships", "connect_fence_status", "connect_policy",
    "fence_state", "install_connect_fence", "login_role_access",
    "drain_and_prove_connect_fence",
    "restore_connect_fence",
    "terminate_unauthorized_sessions", "unauthorized_sessions",
]
