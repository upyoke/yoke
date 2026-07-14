"""Attended production source-authority cutover operations.

The cutover boundary is a durable database CONNECT ACL owned by the attended
database administrator. Ordinary roles cannot override it per session. Export
uses one read-only REPEATABLE READ snapshot for both receipts and ``pg_dump``.
All public receipts omit connection strings and credentials.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain import source_authority_connect_fence as connect_fence
from yoke_core.domain import source_authority_credentials as source_credentials
from yoke_core.domain import source_authority_role_credentials as role_credentials
from yoke_core.domain.source_authority_cutover_support import (
    SourceAuthorityCutoverError,
    admin_connection as _admin_connection,
    assert_connection_rejected as _assert_connection_rejected,
    connection_or_none as _connection_or_none,
    database_identity as _database_identity,
    load_bundle as _load_bundle,
    validate_bundle_authority as _validate_bundle_authority,
    validated_receipt as _validated_receipt,
)
from yoke_core.domain.source_authority_receipts import authority_receipt
from yoke_core.domain.source_freeze_intent import freeze_intent


_DATABASE_FAILURE = (
    "source authority database operation failed; inspect the PostgreSQL "
    "service and selected prod-db-admin connection"
)


def _translate_database_errors(operation: Callable[..., dict[str, Any]]):
    """Keep psycopg and its diagnostics behind the source-dev boundary."""
    @wraps(operation)
    def wrapped(*args: object, **kwargs: object) -> dict[str, Any]:
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            from psycopg import Error as PsycopgError

            if isinstance(exc, PsycopgError):
                raise SourceAuthorityCutoverError(_DATABASE_FAILURE) from exc
            raise
    return wrapped


def resolve_prod_admin_dsn() -> str:
    """Resolve the configured ``*-db-admin`` authority without exposing it."""
    from yoke_contracts.machine_config.schema import connection_is_prod
    from yoke_core.domain import yoke_connected_env

    env = yoke_connected_env.load_active()
    if env is None:
        raise SourceAuthorityCutoverError("no machine connection is selected")
    if (
        env.backend != "postgres"
        or not env.environment.endswith("-db-admin")
        or not connection_is_prod(env.config)
    ):
        raise SourceAuthorityCutoverError(
            "source cutover requires an explicitly selected prod-db-admin "
            "Postgres connection"
        )
    try:
        return yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        ).dsn
    except yoke_connected_env.ConnectedEnvError as exc:
        raise SourceAuthorityCutoverError(
            f"prod-db-admin authority could not be resolved: {exc}"
        ) from exc


@_translate_database_errors
def begin(
    *, service_stop_receipt: str, credential_file: str | Path,
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Rotate the shared credential, install the fence, drain, and prove."""
    stop_receipt = _validated_receipt(
        service_stop_receipt,
        label="old-service stop receipt",
    )
    original_dsn = dsn or resolve_prod_admin_dsn()
    existing = Path(credential_file).expanduser()
    if existing.exists() or existing.is_symlink():
        bundle = _load_bundle(
            credential_file, original_dsn=original_dsn,
            service_stop_receipt=stop_receipt,
        )
        resumed = _connection_or_none(bundle.cutover_dsn)
        if resumed is not None:
            try:
                _validate_bundle_authority(resumed, bundle)
                return _complete_begin(
                    resumed, bundle=bundle, resumed_after_commit=True,
                )
            finally:
                resumed.close()
    conn = _admin_connection(original_dsn)
    try:
        database = _database_identity(conn)
        admin_role = str(conn.execute("SELECT current_user").fetchone()[0])
        rolcanlogin = role_credentials.role_login_state(conn, admin_role)
        if not rolcanlogin:
            raise SourceAuthorityCutoverError(
                "source administrator must originally permit login"
            )
        bundle = source_credentials.prepare_or_load(
            credential_file,
            original_dsn=original_dsn,
            database=database["database"],
            database_oid=database["database_oid"],
            admin_role=admin_role,
            service_stop_receipt=stop_receipt,
            original_rolcanlogin=rolcanlogin,
        )
        frozen_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        connect_fence.install_connect_fence(
            conn, frozen_at=frozen_at, service_stop_receipt=stop_receipt,
        )
        role_credentials.rotate_role_password(conn, bundle)
        # Password cutoff and CONNECT policy become visible in one commit.
        # Any pre-cutoff session is drained through the new credential below.
        conn.commit()
    except connect_fence.SourceConnectFenceError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    except source_credentials.SourceCredentialError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        conn.close()
    cutover = _admin_connection(bundle.cutover_dsn)
    try:
        _validate_bundle_authority(cutover, bundle)
        return _complete_begin(
            cutover, bundle=bundle, resumed_after_commit=False,
        )
    finally:
        cutover.close()


@_translate_database_errors
def status(
    *, credential_file: str | Path, dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Return source state after canonical machine authority has switched."""
    bundle = _load_bundle(credential_file, original_dsn=dsn)
    conn = _admin_connection(bundle.cutover_dsn)
    try:
        state = _validate_bundle_authority(conn, bundle)
        fence = connect_fence.connect_fence_status(conn)
        quiesced = bool(fence["active"])
        return {
            "operation": "status",
            "quiesced": quiesced,
            "database": _database_identity(conn),
            "frozen_at": state["frozen_at"],
            "service_stop_receipt": state["service_stop_receipt"],
            "zero_writable_app_sessions": bool(
                quiesced and state["service_stop_receipt"]
            ),
            "unauthorized_sessions": fence.get("unauthorized_sessions", []),
            "admin_fence": fence,
            "authority": authority_receipt(conn),
        }
    except connect_fence.SourceConnectFenceError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        conn.close()


@_translate_database_errors
def abort(
    *, credential_file: str | Path, dsn: Optional[str] = None,
) -> dict[str, Any]:
    from yoke_core.domain.source_authority_cutover_lifecycle import abort as impl

    return impl(credential_file=credential_file, dsn=dsn)


@_translate_database_errors
def retire(
    *, credential_file: str | Path, retirement_receipt: str,
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    from yoke_core.domain.source_authority_cutover_lifecycle import retire as impl

    return impl(
        credential_file=credential_file, retirement_receipt=retirement_receipt,
        dsn=dsn,
    )


@_translate_database_errors
def export_quiesced(
    *, out: str | Path, credential_file: str | Path,
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Export prod through the bundle's rotated cutover authority."""
    from yoke_core.domain.source_authority_export_cutover import (
        export_quiesced as export_impl,
    )

    return export_impl(out=out, credential_file=credential_file, dsn=dsn)


def _complete_begin(
    conn: object, *, bundle: source_credentials.SourceCredentialBundle,
    resumed_after_commit: bool,
) -> dict[str, Any]:
    _assert_connection_rejected(
        bundle.original_dsn,
        message="old source credential still authenticates after rotation",
    )
    fence = connect_fence.drain_and_prove_connect_fence(conn)
    state = _validate_bundle_authority(conn, bundle)
    first = authority_receipt(conn)
    second = authority_receipt(conn)
    if first["receipt_digest"] != second["receipt_digest"]:
        raise SourceAuthorityCutoverError(
            "source watermarks changed while establishing quiescence"
        )
    return {
        "operation": "begin", "quiesced": True,
        "database": _database_identity(conn),
        "terminated_connections": fence["terminated_other_sessions"],
        "stable_watermarks": True, "frozen_at": state["frozen_at"],
        "service_stop_receipt": state["service_stop_receipt"],
        "zero_writable_app_sessions": True, "admin_fence": fence,
        "credential_fence": {
            "old_credential_rejected": True,
            "cutover_credential_active": True,
            "rotation_committed_before_drain": True,
            "resumed_after_commit": resumed_after_commit,
        },
        "authority": second,
    }


__all__ = [
    "SourceAuthorityCutoverError", "abort", "authority_receipt", "begin",
    "export_quiesced", "freeze_intent", "resolve_prod_admin_dsn", "retire",
    "status",
]
