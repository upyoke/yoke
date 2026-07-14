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
    assert_connection_rejected,
    connection_or_none,
    database_identity,
    load_bundle,
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
    conn = connection_or_none(bundle.cutover_dsn)
    if conn is None:
        restored = connection_or_none(original_dsn)
        if restored is None:
            raise SourceAuthorityCutoverError(
                "neither cutover nor original credential authenticates"
            )
        try:
            if connect_fence.fence_state(restored) is not None:
                raise SourceAuthorityCutoverError(
                    "original credential authenticates while fence state remains"
                )
        finally:
            restored.close()
        source_credentials.delete_bundle(bundle)
        return {"operation": "abort", "quiesced": False, "recovered": True}
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
    conn = connection_or_none(bundle.cutover_dsn)
    if conn is None:
        assert_connection_rejected(
            original_dsn,
            message="original credential authenticates after retirement",
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
            or role_credentials.role_login_state(conn, bundle.admin_role)
        ):
            raise SourceAuthorityCutoverError(
                "source retirement evidence did not validate"
            )
        assert_connection_rejected(
            bundle.cutover_dsn,
            message="cutover credential still authenticates after retirement",
        )
        assert_connection_rejected(
            original_dsn,
            message="original credential still authenticates after retirement",
        )
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
