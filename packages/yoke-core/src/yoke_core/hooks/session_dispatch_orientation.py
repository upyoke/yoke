"""Lifecycle registration recovery and Claude source orientation rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_contracts.session_model_facts import SessionModelFacts, model_display


def _connected_env_remediation(registration_failed: str) -> Optional[str]:
    """Connected-env/tunnel recovery line when registration failed because the
    Postgres authority was unreachable (else ``None``) -- surfaces a dead local
    tunnel loudly instead of a generic "registration failed"."""
    try:
        from yoke_core.domain.connected_env_readiness import (
            registration_failure_remediation,
        )

        return registration_failure_remediation(registration_failed)
    except Exception:  # noqa: BLE001 -- orientation text must never crash the hook
        return None


def registration_failure_stdout(
    reason: str, *, event_name: str = "SessionStart"
) -> str:
    """Keep registration recovery in the same budgeted harness envelope."""
    if not reason:
        return ""
    from yoke_harness.hooks.decision_render import render_context_stdout

    recovery = _connected_env_remediation(reason) or (
        "Run: yoke sessions identity --json to diagnose registration; "
        "repair the named cause before resuming work."
    )
    return render_context_stdout(
        f"WARNING: Session registration failed: {reason}\n{recovery}", event_name
    )


def _render_claude_orientation(
    session_id: str,
    root: str,
    registration_failed: str,
    executor: str,
    facts: SessionModelFacts,
) -> str:
    return _source_orientation(
        session_id,
        root,
        registration_failed,
        [
            f"Executor: {executor or 'claude-code'}",
            f"Model: {model_display(facts)}",
        ],
    )


def _source_orientation(session_id, root, registration_failed, required):
    from yoke_core.domain.session_orientation import (
        render_scoped_orientation,
        REQUIRED_LINES_KEY,
    )

    if registration_failed:
        required.append(f"WARNING: Session registration failed: {registration_failed}")
        required.append(
            _connected_env_remediation(registration_failed)
            or "Run: yoke sessions identity --json to diagnose registration."
        )
    return render_scoped_orientation(
        {
            "session_id": session_id,
            REQUIRED_LINES_KEY: required,
        },
        Path(root),
    )


__all__ = [
    "_connected_env_remediation",
    "_render_claude_orientation",
    "registration_failure_stdout",
]
