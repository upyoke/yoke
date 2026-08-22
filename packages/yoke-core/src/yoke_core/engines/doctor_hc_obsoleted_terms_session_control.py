"""Retired session and organization column vocabulary."""

SESSION_DISPLAY_COLUMN_PATTERN = r"\bexecutor_" + "display_name" + r"\b"
ORGANIZATION_ADMISSION_COLUMN_PATTERN = r"\bauto_" + "join_domain" + r"\b"

SESSION_CONTROL_RETIREMENT_PATTERNS = (
    SESSION_DISPLAY_COLUMN_PATTERN,
    ORGANIZATION_ADMISSION_COLUMN_PATTERN,
)

SESSION_CONTROL_RETIREMENT_LABELS = {
    SESSION_DISPLAY_COLUMN_PATTERN: (
        "retired harness-session display column (renamed to executor_surface)"
    ),
    ORGANIZATION_ADMISSION_COLUMN_PATTERN: (
        "retired organization admission column (renamed to domain)"
    ),
}

_RENAME_SUBJECT_PATHS = (
    "packages/yoke-core/src/yoke_core/domain/migrations/",
    "packages/yoke-core/src/yoke_core/domain/universe_portability_content_contract.py",
    "runtime/api/domain/test_session_surface_organization_domain_migration.py",
)

SESSION_CONTROL_RETIREMENT_ALLOWLIST = {
    pattern: _RENAME_SUBJECT_PATHS for pattern in SESSION_CONTROL_RETIREMENT_PATTERNS
}

__all__ = [
    "ORGANIZATION_ADMISSION_COLUMN_PATTERN",
    "SESSION_CONTROL_RETIREMENT_ALLOWLIST",
    "SESSION_CONTROL_RETIREMENT_LABELS",
    "SESSION_CONTROL_RETIREMENT_PATTERNS",
    "SESSION_DISPLAY_COLUMN_PATTERN",
]
