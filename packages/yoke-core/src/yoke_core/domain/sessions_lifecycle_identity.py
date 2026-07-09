"""Model/lane healing helpers for session registration."""

from __future__ import annotations

from typing import Any, Optional


# Lane value meaning "no lane-aware routing resolved": the registration
# default and the routing-config fallback when no executor key matches.
DEFAULT_EXECUTION_LANE = "primary"


def _stored_value(row: Any, key: str, default: str = "") -> str:
    if row is None:
        return default
    value = row[key]
    return value or default


def lane_should_upgrade(stored_lane: str, incoming_lane: str) -> bool:
    """True when an opt-out stored lane can heal to a real incoming lane."""
    return (
        stored_lane in ("", DEFAULT_EXECUTION_LANE)
        and bool(incoming_lane)
        and incoming_lane != DEFAULT_EXECUTION_LANE
    )


def resolve_reactivation_identity(
    existing: Any,
    *,
    model: str,
    execution_lane: str,
) -> tuple[str, str]:
    """Return ``(model, lane)`` for reactivating an ended session."""
    from yoke_harness.hooks.identity import _is_placeholder_model

    stored_model = _stored_value(existing, "model")
    resolved_model = (
        stored_model
        if _is_placeholder_model(model) and not _is_placeholder_model(stored_model)
        else model
    )
    stored_lane = _stored_value(existing, "execution_lane")
    resolved_lane = (
        stored_lane
        if (not execution_lane or execution_lane == DEFAULT_EXECUTION_LANE)
        and stored_lane not in ("", DEFAULT_EXECUTION_LANE)
        else execution_lane
    )
    return resolved_model, resolved_lane


def refresh_active_duplicate_identity(
    conn: Any,
    *,
    placeholder: str,
    existing: Any,
    session_id: str,
    model: str,
    execution_lane: str,
    actor_id: Optional[int],
    resolved_actor_id: Optional[int],
) -> None:
    """Upgrade mutable identity fields on an active duplicate registration.

    Duplicate registration still raises ``SESSION_EXISTS`` to preserve
    caller semantics; this helper only performs upgrade-only healing first.
    """
    if existing is None:
        return
    from yoke_harness.hooks.identity import _is_placeholder_model

    stored_model = _stored_value(existing, "model")
    if _is_placeholder_model(stored_model) and not _is_placeholder_model(model):
        conn.execute(
            f"UPDATE harness_sessions SET model = {placeholder} "
            f"WHERE session_id = {placeholder}",
            (model, session_id),
        )
        conn.commit()

    stored_lane = _stored_value(existing, "execution_lane")
    if lane_should_upgrade(stored_lane, execution_lane):
        conn.execute(
            f"UPDATE harness_sessions SET execution_lane = {placeholder} "
            f"WHERE session_id = {placeholder}",
            (execution_lane, session_id),
        )
        conn.commit()

    if (
        actor_id is not None
        and resolved_actor_id is not None
        and existing["actor_id"] is None
    ):
        conn.execute(
            f"UPDATE harness_sessions SET actor_id = {placeholder} "
            f"WHERE session_id = {placeholder} AND actor_id IS NULL",
            (resolved_actor_id, session_id),
        )
        conn.commit()


__all__ = [
    "DEFAULT_EXECUTION_LANE",
    "lane_should_upgrade",
    "refresh_active_duplicate_identity",
    "resolve_reactivation_identity",
]
