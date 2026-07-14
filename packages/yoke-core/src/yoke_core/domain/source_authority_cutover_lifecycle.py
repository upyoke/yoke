"""Abort and retirement lifecycle for an old source authority."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import source_authority_connect_fence as connect_fence
from yoke_core.domain import source_authority_credentials as source_credentials
from yoke_core.domain import source_authority_role_credentials as role_credentials
from yoke_core.domain.source_authority_connect_policy import mark_source_retired
from yoke_core.domain.source_authority_cutover_support import (
    SourceAuthorityCutoverError,
    connection_or_none,
    database_identity,
    load_bundle,
    retirement_connection_or_none,
    validate_bundle_authority,
    validated_receipt,
)
from yoke_core.domain.source_authority_receipts import authority_receipt


def abort(
    *, credential_file: str | Path, dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Abort migration and atomically restore credential plus CONNECT policy."""
    bundle = load_bundle(credential_file, original_dsn=dsn)
    original_dsn = bundle.original_dsn
    cutover_probe_inconclusive = False
    try:
        conn = connection_or_none(bundle.cutover_dsn)
    except Exception as exc:
        from psycopg import Error as PsycopgError

        if not isinstance(exc, PsycopgError) or getattr(exc, "sqlstate", None):
            raise
        # A text-only cutover failure is not rejection evidence.  The restored
        # original authority and absent fence can independently prove that an
        # earlier abort committed before local bundle cleanup.
        conn = None
        cutover_probe_inconclusive = True
    if conn is None:
        restored = connection_or_none(original_dsn)
        if restored is None:
            raise SourceAuthorityCutoverError(
                "neither cutover nor original credential authenticates"
            )
        try:
            identity = database_identity(restored)
            current_role = str(
                restored.execute("SELECT current_user").fetchone()[0]
            )
            if (
                identity["database"] != bundle.database
                or identity["database_oid"] != bundle.database_oid
                or current_role != bundle.admin_role
                or connect_fence.fence_state(restored) is not None
            ):
                raise SourceAuthorityCutoverError(
                    "original credential does not prove a completed abort"
                )
        finally:
            restored.close()
        source_credentials.delete_bundle(bundle)
        return {
            "operation": "abort", "quiesced": False, "recovered": True,
            "cutover_connection_rejection": (
                "not-used-as-evidence"
                if cutover_probe_inconclusive else "authentication-sqlstate"
            ),
        }
    try:
        validate_bundle_authority(conn, bundle)
        database = database_identity(conn)
        before = authority_receipt(conn)
        restored = connect_fence.restore_connect_fence(conn)
        role_credentials.restore_role_credential(conn, bundle)
        conn.commit()
    except connect_fence.SourceConnectFenceError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        conn.close()
    proof = connection_or_none(original_dsn)
    if proof is None:
        raise SourceAuthorityCutoverError(
            "original source credential did not recover after abort"
        )
    proof.close()
    source_credentials.delete_bundle(bundle)
    return {
        "operation": "abort", "quiesced": False, "database": database,
        "admin_fence": restored, "authority": before,
        "original_credential_recovered": True,
    }


def retire(
    *, credential_file: str | Path, retirement_receipt: str,
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Permanently disable the source login while preserving fence evidence."""
    receipt = validated_receipt(retirement_receipt, label="retirement receipt")
    bundle = load_bundle(credential_file, original_dsn=dsn)
    original_dsn = bundle.original_dsn
    chosen_retired_at = (
        bundle.retired_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    try:
        bundle = source_credentials.prepare_retirement(
            bundle, retirement_receipt=receipt,
            retired_at=chosen_retired_at,
        )
    except source_credentials.SourceCredentialError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    if bundle.retirement_phase == "transaction_started":
        conn = retirement_connection_or_none(
            bundle.cutover_dsn, role=bundle.admin_role,
        )
    else:
        conn = connection_or_none(bundle.cutover_dsn)
    if conn is None:
        original = retirement_connection_or_none(
            original_dsn, role=bundle.admin_role,
        )
        if original is not None:
            original.close()
            raise SourceAuthorityCutoverError(
                "original credential authenticates after retirement"
            )
        if bundle.retirement_phase != "transaction_started":
            raise SourceAuthorityCutoverError(
                "both source credentials are rejected before a validated "
                "retirement transaction; retirement is indeterminate"
            )
        source_credentials.delete_bundle(bundle)
        return {
            "operation": "retire", "quiesced": True, "retired": True,
            "retired_at": bundle.retired_at,
            "retirement_receipt": bundle.retirement_receipt,
            "login_disabled": True, "password_cleared": True,
            "recovered_after_commit": True,
        }
    try:
        validate_bundle_authority(conn, bundle)
        try:
            bundle = source_credentials.mark_retirement_transaction_started(
                bundle
            )
        except source_credentials.SourceCredentialError as exc:
            raise SourceAuthorityCutoverError(str(exc)) from exc
        database = database_identity(conn)
        before = authority_receipt(conn)
        mark_source_retired(
            conn, retired_at=chosen_retired_at, retirement_receipt=receipt,
        )
        role_credentials.retire_role_credential(conn, bundle)
        conn.commit()
        state = connect_fence.fence_state(conn)
        if (
            state is None or state["retired_at"] != chosen_retired_at
            or state["retirement_receipt"] != receipt
        ):
            raise SourceAuthorityCutoverError(
                "source retirement evidence did not validate"
            )
        try:
            role_credentials.prove_role_retired(conn, bundle)
        except source_credentials.SourceCredentialError as exc:
            raise SourceAuthorityCutoverError(str(exc)) from exc
        source_credentials.delete_bundle(bundle)
        return {
            "operation": "retire", "quiesced": True, "retired": True,
            "database": database, "retired_at": chosen_retired_at,
            "retirement_receipt": receipt, "login_disabled": True,
            "password_cleared": True, "authority": before,
        }
    finally:
        conn.close()


__all__ = ["abort", "retire"]
