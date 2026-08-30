"""Retired database authority helpers and schema surfaces."""

DB_PATH_HELPER_PATTERN = r"\bresolve" + r"_db_path\b"
ITEM_REWORK_COUNTER_PATTERN = r"\b" + "rework" + r"_count\b"
STRATEGY_DOC_CLAIM_PAIR_PATTERN = r"\b" + "paired" + r"_work_claim_id\b"

DB_AUTHORITY_RETIREMENT_PATTERNS = (
    DB_PATH_HELPER_PATTERN,
    ITEM_REWORK_COUNTER_PATTERN,
    STRATEGY_DOC_CLAIM_PAIR_PATTERN,
)

DB_AUTHORITY_RETIREMENT_LABELS = {
    DB_PATH_HELPER_PATTERN: (
        "retired SQLite path-resolution helper "
        "(Postgres authority uses YOKE_PG_DSN / connect())"
    ),
    ITEM_REWORK_COUNTER_PATTERN: "retired items rework counter column",
    STRATEGY_DOC_CLAIM_PAIR_PATTERN: (
        "retired strategy-document steering-seat stored pair column"
    ),
}

_PACKET_TEACHING_PATHS = (
    "packages/yoke-core/src/yoke_core/domain/"
    "schema_api_context_tables_python_helpers.py",
)

_STRATEGY_DOC_CLAIM_PAIR_HISTORY = (
    "packages/yoke-core/src/yoke_core/domain/migrations/"
    "0027_pair_steering_document_claims.py",
    "packages/yoke-core/src/yoke_core/domain/migrations/"
    "0028_remove_strategy_doc_claim_pair.py",
    "runtime/api/domain/test_steering_document_pairing_migration.py",
)

DB_AUTHORITY_RETIREMENT_ALLOWLIST = {
    DB_PATH_HELPER_PATTERN: _PACKET_TEACHING_PATHS,
    ITEM_REWORK_COUNTER_PATTERN: (
        "packages/yoke-core/src/yoke_core/domain/migrations/"
        "0026_remove_item_rework_counter.py",
    ),
    STRATEGY_DOC_CLAIM_PAIR_PATTERN: _STRATEGY_DOC_CLAIM_PAIR_HISTORY,
}

__all__ = [
    "DB_AUTHORITY_RETIREMENT_ALLOWLIST",
    "DB_AUTHORITY_RETIREMENT_LABELS",
    "DB_AUTHORITY_RETIREMENT_PATTERNS",
    "DB_PATH_HELPER_PATTERN",
    "ITEM_REWORK_COUNTER_PATTERN",
    "STRATEGY_DOC_CLAIM_PAIR_PATTERN",
]
