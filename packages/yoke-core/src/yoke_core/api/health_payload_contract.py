"""Shared migration-readiness checks for Yoke health payload consumers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MIGRATIONS_CURRENT_FIELD = "migrations_current"
PENDING_MIGRATIONS_FIELD = "pending_migrations"
CAN_SERVE_DATABASE_FIELD = "can_serve_this_database"
STRANDED_MIGRATIONS_FIELD = "stranded_by_migrations"


def _list_detail(payload: Mapping[str, Any], field: str, label: str) -> str:
    values = payload.get(field)
    if not isinstance(values, list) or not values:
        return ""
    return f" ({label}: {'; '.join(str(value) for value in values)})"


def migration_readiness_problem(
    payload: Mapping[str, Any],
    *,
    require_current: bool,
) -> str:
    """Return why a health payload cannot serve, or an empty string.

    ``migrations_current=false`` is always an explicit refusal. Callers that
    own the current container contract additionally set ``require_current`` so
    an absent field cannot pass. Cross-version deploy probes preserve rolling
    compatibility by accepting an absent field while still rejecting an
    explicit false value.

    ``can_serve_this_database`` was added after the original health contract.
    Missing therefore remains compatible during a mixed-version roll, but an
    explicit false is authoritative and must never be reduced to HTTP liveness.
    """
    current = payload.get(MIGRATIONS_CURRENT_FIELD)
    if current is False or (require_current and current is not True):
        return f"did not report {MIGRATIONS_CURRENT_FIELD}=true" + _list_detail(
            payload,
            PENDING_MIGRATIONS_FIELD,
            "pending migrations",
        )
    if payload.get(CAN_SERVE_DATABASE_FIELD) is False:
        return f"reported {CAN_SERVE_DATABASE_FIELD}=false" + _list_detail(
            payload,
            STRANDED_MIGRATIONS_FIELD,
            "stranded by migrations",
        )
    return ""


__all__ = [
    "CAN_SERVE_DATABASE_FIELD",
    "MIGRATIONS_CURRENT_FIELD",
    "PENDING_MIGRATIONS_FIELD",
    "STRANDED_MIGRATIONS_FIELD",
    "migration_readiness_problem",
]
