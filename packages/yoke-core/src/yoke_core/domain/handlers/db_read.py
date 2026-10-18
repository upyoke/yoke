"""Raw diagnostic DB read handler for ``db.read.run``.

This product/API surface is a bounded, read-only diagnostic runner with
dispatcher authorization. Source-debug raw_query likewise refuses writes;
reviewed human repairs use operator.data_repair.run.
"""

from __future__ import annotations

from yoke_contracts.timestamps import format_instant

import base64
import math
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
from yoke_core.domain.db_read_column_hints import (
    ITEM_REFS_LINE,
    item_reference_warnings,
    sql_touches_item_ids,
)
from yoke_core.domain.db_read_schema_hint import schema_hint_for_error
from yoke_core.domain.handlers.db_read_sql import (
    DbReadRefusal,
    validate_read_only_sql,
)


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
        hint = schema_hint_for_error(spec.sql, exc)
        if hint:
            message = f"{message}\n\n{hint}"
        if sql_touches_item_ids(spec.sql):
            message = f"{message}\n\n{ITEM_REFS_LINE}"
        return _error_outcome(
            DbReadRefusal(
                code="sql_execution_failed",
                message=message,
            )
        )
    return HandlerOutcome(
        result_payload=result.model_dump(),
        warnings=item_reference_warnings(spec.sql, result.columns),
        primary_success=True,
    )


def _coerce_payload(
    payload: Dict[str, Any],
) -> tuple[
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
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, (date, time, UUID)):
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
    normalized = "".join(character for character in key.lower() if character.isalnum())
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
