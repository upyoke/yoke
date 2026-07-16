"""Raw diagnostic DB read handler for ``db.read.run``.

This is deliberately separate from ``yoke_core.cli.raw_query``. The legacy
operator-debug query surface is write-capable; this product/API surface is a
bounded, read-only diagnostic runner with dispatcher authorization.
"""

from __future__ import annotations

import base64
import math
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend, db_helpers, json_helper
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.handlers.db_read_sql import (
    DbReadRefusal,
    validate_read_only_sql,
)
from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES


DEFAULT_ROW_CAP = 100
DEFAULT_STATEMENT_TIMEOUT_MS = 5000


class DbReadRunRequest(BaseModel):
    sql: str = Field(..., min_length=1)
    row_cap: Optional[int] = Field(default=None, ge=1, le=DEFAULT_ROW_CAP)
    statement_timeout_ms: Optional[int] = Field(
        default=None,
        ge=1,
        le=DEFAULT_STATEMENT_TIMEOUT_MS,
    )


class DbReadRunResponse(BaseModel):
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    row_cap: int
    truncated: bool
    statement_timeout_ms: int


def handle_db_read(request: FunctionCallRequest) -> HandlerOutcome:
    """Dispatch handler for ``db.read.run``."""
    spec, refusal = _coerce_payload(request.payload or {})
    if refusal is not None:
        return _error_outcome(refusal)
    assert spec is not None

    refusal = validate_read_only_sql(spec.sql)
    if refusal is not None:
        return _error_outcome(refusal)

    try:
        result = run_db_read(spec)
    except Exception as exc:
        message = f"read query failed: {exc}"
        hint = _schema_hint_for_error(spec.sql, exc)
        if hint:
            message = f"{message}\n\n{hint}"
        return _error_outcome(
            DbReadRefusal(
                code="sql_execution_failed",
                message=message,
            )
        )
    return HandlerOutcome(
        result_payload=result.model_dump(),
        primary_success=True,
    )


def _coerce_payload(payload: Dict[str, Any]) -> tuple[
    Optional[DbReadRunRequest],
    Optional[DbReadRefusal],
]:
    try:
        return DbReadRunRequest.model_validate(payload), None
    except ValidationError as exc:
        return None, DbReadRefusal(
            code="payload_invalid",
            message=str(exc),
            jsonpath="$.payload",
        )


def _error_outcome(refusal: DbReadRefusal) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code=refusal.code,
            message=refusal.message,
            jsonpath=refusal.jsonpath,
        ),
    )


def run_db_read(spec: DbReadRunRequest) -> DbReadRunResponse:
    """Execute a validated diagnostic read and return JSON-safe rows."""
    refusal = validate_read_only_sql(spec.sql)
    if refusal is not None:
        raise ValueError(f"{refusal.code}: {refusal.message}")
    row_cap = spec.row_cap or DEFAULT_ROW_CAP
    timeout_ms = spec.statement_timeout_ms or DEFAULT_STATEMENT_TIMEOUT_MS
    conn = db_helpers.connect()
    try:
        if db_backend.connection_is_postgres(conn):
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{timeout_ms}ms",),
            )
        else:
            conn.execute("PRAGMA query_only = ON")
        cursor = conn.execute(spec.sql)
        if cursor.description is None:
            raise ValueError("read query did not return result columns")
        columns = [_column_name(desc) for desc in cursor.description]
        fetched = cursor.fetchmany(row_cap + 1)
        truncated = len(fetched) > row_cap
        rows = [
            [
                _json_safe(value, column_name=columns[index])
                for index, value in enumerate(row)
            ]
            for row in fetched[:row_cap]
        ]
        return DbReadRunResponse(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            row_cap=row_cap,
            truncated=truncated,
            statement_timeout_ms=timeout_ms,
        )
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def _column_name(description: Any) -> str:
    name = getattr(description, "name", None)
    if name is not None:
        return str(name)
    return str(description[0])


def _json_safe(value: Any, *, column_name: str = "") -> Any:
    if _is_sensitive_key(column_name):
        return "<redacted>" if value is not None else None
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return _redact_json_text(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time, UUID)):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>"
                if _is_sensitive_key(str(key)) and item is not None
                else _json_safe(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


_SENSITIVE_KEY_TOKENS = (
    "credential",
    "dsn",
    "encryptedkey",
    "password",
    "passwd",
    "privatekey",
    "secret",
    "token",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(
        character for character in key.lower() if character.isalnum()
    )
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def _redact_json_text(value: str) -> str:
    stripped = value.lstrip()
    if not stripped.startswith(("{", "[")):
        return value
    try:
        decoded = json_helper.loads_text(value)
    except (TypeError, ValueError):
        return value
    if not isinstance(decoded, (dict, list)):
        return value
    return json_helper.dumps_compact(_json_safe(decoded))


_TABLE_REF_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)",
    re.IGNORECASE,
)
_NO_SUCH_TABLE_RE = re.compile(
    r"(?:no such table|relation .* does not exist):?\s+\"?([A-Za-z_][\w.]*)\"?",
    re.IGNORECASE,
)


def _schema_hint_for_error(sql: str, exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if not any(
        token in lowered
        for token in (
            "no such column",
            "undefinedcolumn",
            "does not exist",
            "no such table",
            "undefinedtable",
        )
    ):
        return ""
    tables = _tables_for_error(sql, message)
    parts: list[str] = []
    for table in tables[:3]:
        columns = _live_columns_for_table(table)
        canonical = CANONICAL_TABLES.get(table)
        if columns:
            parts.append(
                f"Live columns for {table}: "
                + ", ".join(f"{name} {dtype}" for name, dtype in columns)
            )
        if canonical:
            notes = _compact_text(str(canonical.get("notes") or ""))
            if notes:
                parts.append(f"Packet note for {table}: {notes}")
    if not parts:
        return ""
    return "Schema hint from db.read.run:\n" + "\n".join(parts)


def _tables_for_error(sql: str, message: str) -> list[str]:
    tables: list[str] = []
    table_match = _NO_SUCH_TABLE_RE.search(message)
    if table_match is not None:
        tables.append(_clean_table_name(table_match.group(1)))
    for match in _TABLE_REF_RE.finditer(sql):
        table = _clean_table_name(match.group(1))
        if table and table not in tables:
            tables.append(table)
    return tables


def _clean_table_name(name: str) -> str:
    name = name.strip().strip('"')
    if "." in name:
        name = name.rsplit(".", 1)[-1].strip('"')
    return name


def _live_columns_for_table(table: str) -> list[tuple[str, str]]:
    if not table:
        return []
    conn = db_helpers.connect()
    try:
        if db_backend.connection_is_postgres(conn):
            rows = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position",
                (table,),
            ).fetchall()
            return [(str(row[0]), str(row[1])) for row in rows]
        if not _sqlite_table_exists(conn, table):
            return []
        rows = conn.execute(f'PRAGMA table_info("{_sqlite_ident(table)}")').fetchall()
        return [(str(row[1]), str(row[2])) for row in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _sqlite_table_exists(conn: Any, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _sqlite_ident(identifier: str) -> str:
    return identifier.replace('"', '""')


def _compact_text(text: str, limit: int = 700) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


__all__ = [
    "DB_READ_FUNCTION_ID",
    "DEFAULT_ROW_CAP",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "DbReadRunRequest",
    "DbReadRunResponse",
    "handle_db_read",
    "run_db_read",
    "validate_read_only_sql",
]
