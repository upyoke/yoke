"""Retired SQLite file-path authority helper."""

DB_PATH_HELPER_PATTERN = r"\bresolve" + r"_db_path\b"

DB_AUTHORITY_RETIREMENT_PATTERNS = (DB_PATH_HELPER_PATTERN,)

DB_AUTHORITY_RETIREMENT_LABELS = {
    DB_PATH_HELPER_PATTERN: (
        "retired SQLite path-resolution helper "
        "(Postgres authority uses YOKE_PG_DSN / connect())"
    ),
}

_PACKET_TEACHING_PATHS = (
    "packages/yoke-core/src/yoke_core/domain/"
    "schema_api_context_tables_python_helpers.py",
)

DB_AUTHORITY_RETIREMENT_ALLOWLIST = {
    DB_PATH_HELPER_PATTERN: _PACKET_TEACHING_PATHS,
}

__all__ = [
    "DB_AUTHORITY_RETIREMENT_ALLOWLIST",
    "DB_AUTHORITY_RETIREMENT_LABELS",
    "DB_AUTHORITY_RETIREMENT_PATTERNS",
    "DB_PATH_HELPER_PATTERN",
]
