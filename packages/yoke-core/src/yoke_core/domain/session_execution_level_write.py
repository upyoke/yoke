"""Keep stored session levels aligned with observed model and effort facts."""

from yoke_core.domain.session_level_resolution import (
    resolve_execution_level,
    session_levels,
)
from yoke_contracts.model_level_resolution import (
    routing_effort_of,
    routing_model_of,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_model_catalog import current_model_records


def refresh_session_execution_level(conn, session_id):
    """Update within the caller's identity transaction, without committing it."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    fetched = conn.execute(
        "SELECT executor, executor_surface, project_id, model, requested_model, "
        "reasoning_effort, requested_reasoning_effort, execution_level "
        f"FROM harness_sessions WHERE session_id={p}",
        (session_id,),
    ).fetchone()
    if fetched is None:
        return None
    row = dict(fetched)
    level = resolve_execution_level(
        executor=row.get("executor_surface") or row.get("executor"),
        explicit_level=None,
        levels=session_levels(conn, row.get("project_id")),
        model=routing_model_of(row.get("model"), row.get("requested_model")),
        reasoning_effort=routing_effort_of(
            row.get("reasoning_effort"),
            row.get("requested_reasoning_effort"),
            row.get("model"),
        ),
        records=current_model_records(conn),
    )
    if level != row.get("execution_level"):
        conn.execute(
            f"UPDATE harness_sessions SET execution_level={p} WHERE session_id={p}",
            (level, session_id),
        )
    return level
