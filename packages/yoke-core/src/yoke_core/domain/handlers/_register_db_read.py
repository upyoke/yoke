"""Handler registration for the db.read diagnostic read family."""

from __future__ import annotations

from yoke_core.domain.handlers import db_read as _db


def register(registry) -> None:
    registry.register(
        _db.DB_READ_FUNCTION_ID,
        _db.handle_db_read,
        _db.DbReadRunRequest,
        _db.DbReadRunResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.db_read",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["read_only_sql", "row_cap", "statement_timeout"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
