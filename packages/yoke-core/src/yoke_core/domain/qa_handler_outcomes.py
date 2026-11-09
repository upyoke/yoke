"""Shared QA SQL markers and refusal outcomes."""

from typing import Any, Optional
from yoke_core.domain import db_backend
from yoke_contracts.api.function_call import FunctionError, HandlerOutcome


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _error(
    code: str, message: str, *, jsonpath: Optional[str] = None
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )
