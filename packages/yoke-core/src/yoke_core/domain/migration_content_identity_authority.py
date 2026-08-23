"""Least-privilege authority names for migration-content verification."""

from yoke_contracts.migration_content_identity import FUNCTION_ID


ROLE_MIGRATION_VERIFICATION_CI = "migration_verification_ci"
PERM_MIGRATION_CONTENT_IDENTITY_VERIFY = FUNCTION_ID


__all__ = [
    "PERM_MIGRATION_CONTENT_IDENTITY_VERIFY",
    "ROLE_MIGRATION_VERIFICATION_CI",
]
