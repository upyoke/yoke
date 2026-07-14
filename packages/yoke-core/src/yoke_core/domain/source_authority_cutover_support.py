"""Shared non-secret validation and connection helpers for source cutover."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain import source_authority_connect_fence as connect_fence
from yoke_core.domain import source_authority_credentials as source_credentials


class SourceAuthorityCutoverError(RuntimeError):
    """The attended source-authority operation was refused safely."""


_AUTHENTICATION_REJECTION_SQLSTATES = frozenset({"28000", "28P01"})
_LIBPQ_LOGIN_REFUSAL = re.compile(
    r'FATAL:\s+(?:password authentication failed for user "[^"]+"|'
    r'role "[^"]+" is not permitted to log in)(?:\n|$)'
)


def admin_connection(dsn: str) -> object:
    return db_backend.connect_psycopg(dsn)


def database_identity(conn: object) -> dict[str, Any]:
    row = conn.execute(
        "SELECT current_database(), oid FROM pg_database "
        "WHERE datname = current_database()"
    ).fetchone()
    org = conn.execute(
        "SELECT slug FROM organizations ORDER BY id LIMIT 1"
    ).fetchone()
    return {"database": str(row[0]), "database_oid": int(row[1]), "org": str(org[0])}


def load_bundle(
    path: str | Path, *, original_dsn: str | None = None,
    service_stop_receipt: str | None = None,
) -> source_credentials.SourceCredentialBundle:
    try:
        return source_credentials.load_bound(
            path, original_dsn=original_dsn,
            service_stop_receipt=service_stop_receipt,
        )
    except source_credentials.SourceCredentialError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc


def validate_bundle_authority(
    conn: object, bundle: source_credentials.SourceCredentialBundle,
) -> dict[str, Any]:
    database = database_identity(conn)
    admin_role = str(conn.execute("SELECT current_user").fetchone()[0])
    state = connect_fence.fence_state(conn)
    if state is None:
        raise SourceAuthorityCutoverError("source authority is not quiesced")
    policy = state.get("policy")
    if not isinstance(policy, dict):
        raise SourceAuthorityCutoverError("source fence policy is invalid")
    if (
        database["database"] != bundle.database
        or database["database_oid"] != bundle.database_oid
        or admin_role != bundle.admin_role
        or int(policy.get("database_oid", -1)) != bundle.database_oid
        or str(policy.get("admin_role") or "") != bundle.admin_role
        or state["service_stop_receipt"] != bundle.service_stop_receipt
    ):
        raise SourceAuthorityCutoverError(
            "cutover credential binding does not match the live source fence"
        )
    return state


def connection_or_none(dsn: str) -> object | None:
    """Connect, returning ``None`` only for an explicit login rejection.

    Availability, routing, TLS, and timeout failures are not evidence that a
    credential was disabled and must remain visible to the operator.
    """
    try:
        return admin_connection(dsn)
    except Exception as exc:
        from psycopg import Error as PsycopgError

        if (
            isinstance(exc, PsycopgError)
            and (
                getattr(exc, "sqlstate", None)
                in _AUTHENTICATION_REJECTION_SQLSTATES
                or (
                    getattr(exc, "sqlstate", None) is None
                    and _LIBPQ_LOGIN_REFUSAL.search(str(exc)) is not None
                )
            )
        ):
            return None
        raise


def assert_connection_rejected(dsn: str, *, message: str) -> None:
    probe = connection_or_none(dsn)
    if probe is None:
        return
    probe.close()
    raise SourceAuthorityCutoverError(message)


def validated_receipt(value: str, *, label: str) -> str:
    selected = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", selected) is None:
        raise SourceAuthorityCutoverError(
            f"{label} must be a non-secret identifier"
        )
    return selected


__all__ = [
    "SourceAuthorityCutoverError", "admin_connection",
    "assert_connection_rejected", "connection_or_none", "database_identity",
    "load_bundle", "validate_bundle_authority", "validated_receipt",
]
