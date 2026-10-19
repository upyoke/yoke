"""Work admission from observed model facts and the target project's levels."""

from __future__ import annotations

from yoke_contracts.levels import (
    UNRESOLVED_LEVEL_REASONS,
    LevelsError,
    level_for_session,
)
from yoke_contracts.model_level_resolution import resolve_model_level
from yoke_contracts.model_level_resolution import (
    routing_effort_of,
    routing_model_of,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_model_catalog import current_model_records
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.universe_levels import UniverseLevelsError, effective_levels


def require_work_selection(conn, *, project_id, executor, model, reasoning_effort):
    """Any configured level admits work; unresolved selections refuse it."""
    try:
        levels, _ = effective_levels(conn, project_id)
    except (LevelsError, UniverseLevelsError) as exc:
        raise SessionError(
            "SESSION_LEVELS_INVALID",
            f"{exc}. Recovery: repair the universe Levels or project session-routing document before acquiring work.",
        ) from exc
    records = current_model_records(conn)
    level = level_for_session(
        levels,
        executor=executor,
        model=model or "",
        reasoning_effort=reasoning_effort,
        records=records,
    )
    if level is None:
        resolution = resolve_model_level(
            levels, model=model, effort=reasoning_effort, records=records
        )
        raise SessionError(
            "SESSION_BELOW_INTERN",
            f"{resolution.reason} ({UNRESOLVED_LEVEL_REASONS.get(resolution.reason, 'unresolved')}): "
            "selection meets no configured execution level; model or effort "
            "is unknown, or both are below every option. Recovery: choose a "
            "known model and effort meeting a configured level, or ask an org "
            "admin to publish the missing catalog facts and approve Levels. "
            "Steering without item claims remains available.",
        )
    return level


def _session_and_item(conn, session_id, item_id):
    """Load the claiming session row and the target item's project facts."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    session = conn.execute(
        f"SELECT * FROM harness_sessions WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    if session is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    project = conn.execute(
        f"SELECT i.project_id, ir.public_ref, i.title, p.slug FROM items i "
        f"JOIN projects p ON p.id = i.project_id "
        f"JOIN item_refs ir ON ir.item_id = i.id WHERE i.id = {marker}",
        (item_id,),
    ).fetchone()
    if project is None:
        raise SessionError("INVALID_CLAIM", "Work target item does not exist.")
    return dict(session), project


def _project_mismatch(conn, observed, project, *, recovery):
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    session_project = None
    if observed.get("project_id") is not None:
        session_project = conn.execute(
            f"SELECT slug FROM projects WHERE id = {marker}",
            (observed["project_id"],),
        ).fetchone()
    origin = (
        f"in project {session_project[0]}" if session_project else "outside any project"
    )
    code = (
        "SESSION_MACHINE_SCOPE_WORK_REFUSED"
        if observed.get("project_id") is None
        else "SESSION_PROJECT_MISMATCH"
    )
    return SessionError(
        code,
        f"Open a session in the {project[3]} project folder to work on "
        f"{project[1]} ({project[2]}). This session was started {origin}; "
        f"sessions never switch projects.{recovery}",
    )


def require_session_work_eligibility(conn, session_id, target):
    """Process-only coordination is exempt; item and epic-task claims are work."""
    item_id = target.item_id or target.epic_id
    if item_id is None:
        return
    observed, project = _session_and_item(conn, session_id, item_id)
    if observed.get("project_id") != project[0]:
        raise _project_mismatch(conn, observed, project, recovery="")
    require_work_selection(
        conn,
        project_id=project[0],
        executor=observed.get("executor_surface") or observed.get("executor") or "",
        model=routing_model_of(observed.get("model"), observed.get("requested_model")),
        reasoning_effort=routing_effort_of(
            observed.get("reasoning_effort"),
            observed.get("requested_reasoning_effort"),
            observed.get("model"),
        ),
    )


def require_session_close_eligibility(conn, session_id, target):
    """Admit an administrative close: no model level, project or covering seat.

    Closing an item does no work on it, so the session's model selection is
    not consulted. A session in the item's project may close it; a session
    elsewhere needs its own live steering seat covering the item.
    """
    from yoke_core.domain.session_steering_authority import (
        covering_session_seat,
        steering_authority_message,
    )

    observed, project = _session_and_item(conn, session_id, target.item_id)
    if observed.get("project_id") == project[0]:
        return
    seat = covering_session_seat(
        conn,
        caller_session_id=str(session_id),
        target={"project_id": int(project[0]), "item_id": int(target.item_id)},
    )
    if seat is None:
        raise _project_mismatch(
            conn,
            observed,
            project,
            recovery=" Closing an item from another project "
            + steering_authority_message(project[3]),
        )
