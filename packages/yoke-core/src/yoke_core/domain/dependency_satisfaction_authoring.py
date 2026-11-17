"""Refuse dependency satisfaction values an edge cannot be authored with."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.dependency_satisfaction import _placeholder, _row_value
from yoke_core.domain.dependency_status_stage import require_authorable_status_stage
from yoke_core.domain.dependency_types import (
    SATISFACTION_GRAMMAR,
    Satisfaction,
    deployed_environment,
)
from yoke_core.domain.environment_delivery_record import (
    UnregisteredEnvironment,
    require_registered_environment,
)
from yoke_core.domain.project_identity import render_item_ref


def require_authorable_satisfaction(
    conn: Any,
    *,
    blocking_item_id: int,
    satisfaction: str,
) -> None:
    """Refuse unknown values, unknown stages, and unregistered environments."""
    try:
        Satisfaction.from_db(satisfaction)
    except ValueError as exc:
        raise ValueError(
            f"unknown_satisfaction: {satisfaction!r}; accepted grammar: "
            f"{SATISFACTION_GRAMMAR}"
        ) from exc
    environment = deployed_environment(satisfaction)
    if environment is None:
        require_authorable_status_stage(
            conn, blocking_item_id=blocking_item_id, satisfaction=satisfaction
        )
        return
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id={p}",
        (int(blocking_item_id),),
    ).fetchone()
    if row is None:
        raise LookupError(
            f"blocking {render_item_ref(conn, blocking_item_id)} not found"
        )
    try:
        require_registered_environment(
            conn,
            int(_row_value(row, "project_id", 0)),
            environment,
        )
    except UnregisteredEnvironment as exc:
        raise UnregisteredEnvironment(f"environment_unregistered: {exc}") from exc


__all__ = ["require_authorable_satisfaction"]
