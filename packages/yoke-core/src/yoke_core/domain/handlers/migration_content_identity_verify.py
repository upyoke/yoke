"""Narrow control-plane migration-content identity verification handler."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.migration_content_identity import (
    MigrationContentIdentityVerifyRequest,
    MigrationContentIdentityVerifyResponse,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.migration_content_identity import read_content_identity_status
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT


def verify_migration_content_identity(
    conn: Any,
    spec: MigrationContentIdentityVerifyRequest,
) -> MigrationContentIdentityVerifyResponse:
    """Compare a candidate with the fixed Yoke ledger without exposing digests."""
    status = read_content_identity_status(
        conn,
        spec.entries,
        YOKE_LEDGER_CONTRACT,
    )
    mismatched = [item.entry_name for item in status.mismatches]
    return MigrationContentIdentityVerifyResponse(
        status="mismatch" if mismatched else "verified",
        verified_count=len(status.verified),
        mismatched_entries=mismatched,
    )


def handle_migration_content_identity_verify(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Verify caller-supplied candidate digests through one fixed ledger read."""
    try:
        spec = MigrationContentIdentityVerifyRequest.model_validate(
            request.payload or {}
        )
    except ValidationError:
        return _error(
            "payload_invalid",
            "candidate migration entries must carry unique names and SHA256 digests",
            jsonpath="$.payload.entries",
        )

    try:
        with db_helpers.connect() as conn:
            result = verify_migration_content_identity(conn, spec)
    except Exception:  # noqa: BLE001 - availability is typed; DB detail stays server-side
        return _error(
            "migration_identity_verification_unavailable",
            "migration content identity could not be verified",
        )
    return HandlerOutcome(result_payload=result.model_dump(), primary_success=True)


def _error(code: str, message: str, *, jsonpath: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "handle_migration_content_identity_verify",
    "verify_migration_content_identity",
]
