"""Shared hook-tail registration, presentation, and usage persistence."""

from __future__ import annotations

from typing import Any


def apply_hook_session_tail(
    conn: Any,
    *,
    ensure_session: tuple[Any, ...] | None,
    usage_session: tuple[Any, ...] | None,
) -> None:
    """Apply independent registration and usage observations on one connection."""
    if ensure_session is not None:
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
        try:
            ensure_registered_from_hook(
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
        except Exception:  # noqa: BLE001 — usage remains independently writable
            pass
        from yoke_core.domain.session_presentation_observation import (
            record_session_presentation,
        )

        try:
            record_session_presentation(
                conn,
                session_id=session_id,
                payload_json=payload_json,
            )
        except Exception:  # noqa: BLE001 — usage remains independently writable
            pass
    if usage_session is not None:
        from yoke_core.domain.session_usage_observation import record_session_usage

        session_id, payload_json, executor = usage_session
        record_session_usage(
            conn,
            session_id=session_id,
            payload_json=payload_json,
            executor=executor,
        )


__all__ = ["apply_hook_session_tail"]
