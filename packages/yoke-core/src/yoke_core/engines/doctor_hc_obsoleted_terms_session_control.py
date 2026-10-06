"""Retired session and organization column vocabulary."""

SESSION_DISPLAY_COLUMN_PATTERN = r"\bexecutor_" + "display_name" + r"\b"
ORGANIZATION_ADMISSION_COLUMN_PATTERN = r"\bauto_" + "join_domain" + r"\b"
# Execution lanes were renamed to execution levels; "lane" now names only
# worktree lanes, so each retired spelling of the session grouping is hunted.
EXECUTION_LANE_PATTERN = r"(?i)\bexecution[ _-]" + "lanes?" + r"\b"
LANE_ROUTING_KEY_PATTERN = (
    r"\b(?:lane_" + "metadata|lane_" + "rules|executor_default_" + r"lane)"
)
LANE_SUMMARY_PATTERN = r"\blane[-_]" + "summary" + r"\b"
LANE_GLYPH_PATTERN = r"\blane_" + "glyph" + r"\b"
SESSION_LANE_MODULE_PATTERN = r"\byoke_contracts\.session_" + "lane" + r"\b"

EXECUTION_LEVEL_RETIREMENT_PATTERNS = (
    EXECUTION_LANE_PATTERN,
    LANE_ROUTING_KEY_PATTERN,
    LANE_SUMMARY_PATTERN,
    LANE_GLYPH_PATTERN,
    SESSION_LANE_MODULE_PATTERN,
)

SESSION_CONTROL_RETIREMENT_PATTERNS = (
    SESSION_DISPLAY_COLUMN_PATTERN,
    ORGANIZATION_ADMISSION_COLUMN_PATTERN,
    *EXECUTION_LEVEL_RETIREMENT_PATTERNS,
)

SESSION_CONTROL_RETIREMENT_LABELS = {
    SESSION_DISPLAY_COLUMN_PATTERN: (
        "retired harness-session display column (renamed to executor_surface)"
    ),
    ORGANIZATION_ADMISSION_COLUMN_PATTERN: (
        "retired organization admission column (renamed to domain)"
    ),
    EXECUTION_LANE_PATTERN: "retired execution lane (renamed to execution level)",
    LANE_ROUTING_KEY_PATTERN: (
        "retired session-routing lane key (renamed to level_metadata, "
        "level_rules, executor_default_levels)"
    ),
    LANE_SUMMARY_PATTERN: "retired project lane summary (renamed to level summary)",
    LANE_GLYPH_PATTERN: "retired lane glyph contract (renamed to level glyph)",
    SESSION_LANE_MODULE_PATTERN: (
        "frozen migration import surface (live code reads yoke_contracts.session_level)"
    ),
}

_RENAME_SUBJECT_PATHS = (
    "packages/yoke-core/src/yoke_core/domain/migrations/",
    "packages/yoke-core/src/yoke_core/domain/universe_portability_content_contract.py",
    "runtime/api/domain/test_session_surface_organization_domain_migration.py",
)

# Where the retired lane spellings are the subject: the frozen import surface
# applied history needs, the previous registry's served function ids, the key
# map and refusals that name the replacement, the boot DDL note, and the tests
# proving convergence and refusal.
_LEVEL_RENAME_SUBJECT_PATHS = _RENAME_SUBJECT_PATHS + (
    "packages/yoke-contracts/src/yoke_contracts/session_lane.py",
    "packages/yoke-contracts/src/yoke_contracts/session_level.py",
    "packages/yoke-contracts/src/yoke_contracts/session_control/recipient_selector.py",
    "packages/yoke-core/src/yoke_core/domain/function_serving_floor_ids.py",
    "packages/yoke-core/src/yoke_core/domain/schema_init_tables_sessions.py",
    "packages/yoke-core/src/yoke_core/domain/session_routing_rules.py",
    "packages/yoke-core/src/yoke_core/domain/session_routing_validation.py",
    "runtime/api/domain/test_migration_remove_lane_allowlists.py",
    "runtime/api/domain/test_migration_remove_process_offer_settings.py",
    "runtime/api/domain/test_migration_rename_session_lanes_to_levels.py",
    "runtime/api/domain/test_session_control_contracts.py",
    "runtime/api/test_session_routing_validation.py",
)

SESSION_CONTROL_RETIREMENT_ALLOWLIST = {
    **{
        pattern: _RENAME_SUBJECT_PATHS
        for pattern in (
            SESSION_DISPLAY_COLUMN_PATTERN,
            ORGANIZATION_ADMISSION_COLUMN_PATTERN,
        )
    },
    **{
        pattern: _LEVEL_RENAME_SUBJECT_PATHS
        for pattern in EXECUTION_LEVEL_RETIREMENT_PATTERNS
    },
}

__all__ = [
    "EXECUTION_LEVEL_RETIREMENT_PATTERNS",
    "ORGANIZATION_ADMISSION_COLUMN_PATTERN",
    "SESSION_CONTROL_RETIREMENT_ALLOWLIST",
    "SESSION_CONTROL_RETIREMENT_LABELS",
    "SESSION_CONTROL_RETIREMENT_PATTERNS",
    "SESSION_DISPLAY_COLUMN_PATTERN",
]
