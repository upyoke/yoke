"""Shared hook-tail registration, presentation, and observation persistence."""

from __future__ import annotations

from typing import Any


def apply_hook_session_tail(
    conn: Any,
    *,
    ensure_session: tuple[Any, ...] | None,
    observed_session: tuple[Any, ...] | None,
) -> None:
    """Apply independent registration and row observations on one connection.

    ``observed_session`` carries an existing row's payload, trusted
    executor, and whether this process is the one running the session.
    Unlike registration it is valid for terminal hooks and can never
    create or revive a row, which is what lets the last hook of a turn
    record evidence that only exists once that turn has finished.
    """
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
        except Exception:  # noqa: BLE001 — observations remain independently writable
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
        except Exception:  # noqa: BLE001 — observations remain independently writable
            pass
    if observed_session is not None:
        from yoke_core.domain.session_identity_observation import (
            record_session_identity,
        )
        from yoke_core.domain.session_usage_observation import record_session_usage

        session_id, payload_json, executor, local_evaluation = observed_session
        try:  # one failed observation must not drop the other
            record_session_usage(
                conn,
                session_id=session_id,
                payload_json=payload_json,
                executor=executor,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            record_session_identity(
                conn,
                session_id=session_id,
                payload_json=payload_json,
                executor=executor,
                local_evaluation=local_evaluation,
            )
        except Exception:  # noqa: BLE001
            pass


__all__ = ["apply_hook_session_tail"]
