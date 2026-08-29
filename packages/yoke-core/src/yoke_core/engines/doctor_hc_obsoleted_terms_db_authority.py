"""Retired database authority helpers and schema surfaces."""

DB_PATH_HELPER_PATTERN = r"\bresolve" + r"_db_path\b"
ITEM_REWORK_COUNTER_PATTERN = r"\b" + "rework" + r"_count\b"

DB_AUTHORITY_RETIREMENT_PATTERNS = (
    DB_PATH_HELPER_PATTERN,
    ITEM_REWORK_COUNTER_PATTERN,
)

DB_AUTHORITY_RETIREMENT_LABELS = {
    DB_PATH_HELPER_PATTERN: (
        "retired SQLite path-resolution helper "
        "(Postgres authority uses YOKE_PG_DSN / connect())"
    ),
    ITEM_REWORK_COUNTER_PATTERN: "retired items rework counter column",
}

_PACKET_TEACHING_PATHS = (
    "packages/yoke-core/src/yoke_core/domain/"
    "schema_api_context_tables_python_helpers.py",
)

DB_AUTHORITY_RETIREMENT_ALLOWLIST = {
    DB_PATH_HELPER_PATTERN: _PACKET_TEACHING_PATHS,
    ITEM_REWORK_COUNTER_PATTERN: (
        "packages/yoke-core/src/yoke_core/domain/migrations/"
        "0026_remove_item_rework_counter.py",
    ),
}

__all__ = [
    "DB_AUTHORITY_RETIREMENT_ALLOWLIST",
    "DB_AUTHORITY_RETIREMENT_LABELS",
    "DB_AUTHORITY_RETIREMENT_PATTERNS",
    "DB_PATH_HELPER_PATTERN",
    "ITEM_REWORK_COUNTER_PATTERN",
]
