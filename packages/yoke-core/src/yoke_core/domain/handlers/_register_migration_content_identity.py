"""Register the semantic migration-content identity verifier."""

from yoke_contracts.migration_content_identity import (
    FUNCTION_ID,
    MigrationContentIdentityVerifyRequest,
    MigrationContentIdentityVerifyResponse,
)
from yoke_core.domain.handlers import migration_content_identity_verify as _verify


def register(registry) -> None:
    registry.register(
        FUNCTION_ID,
        _verify.handle_migration_content_identity_verify,
        MigrationContentIdentityVerifyRequest,
        MigrationContentIdentityVerifyResponse,
        stability="stable",
        owner_module=("yoke_core.domain.handlers.migration_content_identity_verify"),
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "fixed_control_plane_ledger",
            "candidate_digest_validation",
            "ledger_digest_redaction",
        ],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
