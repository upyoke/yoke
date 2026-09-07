"""Shared hook-tail registration, presentation, and usage persistence."""

from __future__ import annotations

from typing import Any


def apply_hook_registration(conn: Any, ensure_session: tuple[Any, ...]) -> None:
    """Ensure the session row, then record what the client observed about it."""
    from yoke_core.hooks.registration import ensure_registered_from_hook

    (
        session_id,
        payload_json,
        transcript_path,
        record_anchor,
        executor_hint,
        in_process,
        force,
        actor_id,
        project_id,
    ) = ensure_session
    registered = ensure_registered_from_hook(
        conn,
        payload_json,
        session_id,
        transcript_path=transcript_path,
        record_anchor=record_anchor,
        executor_hint=executor_hint,
        register_in_process=in_process,
        force_reregister=force,
        actor_id=actor_id,
        project_id=project_id,
    )
    from yoke_core.domain.session_presentation_observation import (
        record_session_presentation,
    )

    record_session_presentation(
        conn,
        session_id=session_id,
        payload_json=payload_json,
    )
    from yoke_core.domain.session_usage_observation import record_session_usage

    # The resolved executor comes back from registration rather than being
    # detected again: a local hook has no wire-carried reading, so this
    # process takes one, and taking it needs the harness family that names
    # which artifact to open.
    record_session_usage(
        conn,
        session_id=session_id,
        payload_json=payload_json,
        executor=registered[1] if registered else "",
    )


__all__ = ["apply_hook_registration"]
