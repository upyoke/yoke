"""Work admission from observed model facts and the target project's levels."""

from __future__ import annotations

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.levels import (
    UNRESOLVED_LEVEL_REASONS,
    LevelsError,
    level_for_session,
)
from yoke_contracts.model_level_resolution import (
    resolve_model_level,
    routing_effort_of,
    routing_model_of,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.session_model_facts import (
    PLACEHOLDER_MODEL_GUIDANCE,
    is_placeholder_model,
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
            compose_refusal(
                f"{exc}.",
                recovery="repair the universe Levels or project session-routing document before acquiring work.",
            ),
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
            compose_refusal(
                f"{resolution.reason} ({UNRESOLVED_LEVEL_REASONS.get(resolution.reason, 'unresolved')}): selection meets no configured execution level; model or effort is unknown, or both are below every option.{_placeholder_note(executor, model)}",
                recovery=(
                    "choose a known model and effort meeting a configured level, or ask an org "
                    "admin to publish the missing catalog facts and approve Levels. Steering "
                    "without item claims remains available."
                ),
            ),
        )
    return level


def _placeholder_note(executor, model) -> str:
    """Name what the harness's placeholder selection hides, when the model is unnamed."""
    if not is_placeholder_model(model):
        return ""
    try:
        harness = canonical_harness_id(executor)
    except ValueError:
        return ""
    guidance = PLACEHOLDER_MODEL_GUIDANCE.get(harness)
    return f" {guidance}." if guidance else ""


def _session_and_item(conn, session_id, item_id):
    """Load the claiming session row and the target item's project id."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    session = conn.execute(
        f"SELECT * FROM harness_sessions WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    if session is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    item = conn.execute(
        f"SELECT project_id FROM items WHERE id = {marker}",
        (item_id,),
    ).fetchone()
    if item is None:
        raise SessionError("INVALID_CLAIM", "Work target item does not exist.")
    return dict(session), item[0]


def require_session_work_eligibility(conn, session_id, target):
    """Process-only coordination is exempt; item and epic-task claims are work.

    Any session may work an item in any project; the item's project Levels
    decide whether the session's model selection admits the work.
    """
    item_id = target.item_id or target.epic_id
    if item_id is None:
        return
    observed, project_id = _session_and_item(conn, session_id, item_id)
    require_work_selection(
        conn,
        project_id=project_id,
        executor=observed.get("executor_surface") or observed.get("executor") or "",
        model=routing_model_of(observed.get("model"), observed.get("requested_model")),
        reasoning_effort=routing_effort_of(
            observed.get("reasoning_effort"),
            observed.get("requested_reasoning_effort"),
            observed.get("model"),
        ),
    )


def require_session_close_eligibility(conn, session_id, target):
    """Admit an administrative close from any session in any project.

    Closing an item does no work on it, so the session's model selection is
    not consulted; only the session and the item must exist.
    """
    _session_and_item(conn, session_id, target.item_id)
