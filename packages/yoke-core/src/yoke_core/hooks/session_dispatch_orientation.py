"""Orientation and reminder text the session-start hooks return.

Split from :mod:`yoke_core.hooks.session_dispatch`, which owns the hook
dispatch itself. Everything here is rendering: what a newly registered
session is told about its identity and its model, and how to recover when
registration failed. The model line goes through ``model_display`` so an
unattested session shows its request labelled as one rather than reading
as a report of what ran.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yoke_contracts.session_model_facts import SessionModelFacts, model_display

from yoke_core.hooks import session_dispatch_codex_lifecycle as _codex_lifecycle


_session_begin_recovery_command = _codex_lifecycle.recovery_command


def _requested(facts: SessionModelFacts) -> str:
    """The model an operator recovery recipe should re-request."""
    return facts.requested_model or facts.model or ""


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


def _render_codex_orientation(
    session_id: str,
    root: str,
    registration_failed: str,
    facts: SessionModelFacts,
    entrypoint: Optional[str],
) -> str:
    return _source_orientation(
        session_id,
        root,
        registration_failed,
        [
            "Executor: codex",
            "Mode: hook-enhanced (SessionStart)",
        ],
    )


def _render_codex_reminder(
    session_id: str,
    root: str,
    registration_failed: str,
    facts: SessionModelFacts,
    entrypoint: Optional[str],
) -> str:
    from yoke_core.domain.harness_capability_registry import (
        prompt_reminder_lines,
        shared_downstream_paths,
    )
    from yoke_core.domain.main_agent_packet import render_install_advisory_block
    from yoke_core.hooks.codex_payload import session_marker_path

    lines: list[str] = []
    # When orientation was suppressed for source="startup"+no-transcript,
    # SESSION_MARKER is unarmed and the bootstrap-compact advisory never rendered.
    # Surface it here so the first model-visible Codex output still teaches the install path.
    if not os.path.exists(session_marker_path(session_id)):
        advisory = render_install_advisory_block()
        if advisory:
            lines.extend([advisory, ""])
    lines.append("Yoke/Codex safe operator commands for this session:")
    if registration_failed:
        lines.append(
            "WARNING: Session registration backfill failed - scheduler may "
            f"not see this session. Reason: {registration_failed}. "
            f"Run: {_session_begin_recovery_command(session_id, root, _requested(facts), entrypoint)}"
        )
        remediation = _connected_env_remediation(registration_failed)
        if remediation:
            lines.append(remediation)
        lines.append("")
    lines.extend(prompt_reminder_lines())
    lines.extend(
        [
            "  /yoke help   -- show available commands",
            "",
            "Local terminal helpers (no harness session required):",
            "  yoke board art variant create --ascii|--mixed|--image PATH",
            "",
            "Downstream paths: "
            + ", ".join(shared_downstream_paths())
            + " (from shared registry)",
            "",
            "Prefer /yoke commands and the yoke CLI.",
            "Do not call internal scripts directly unless instructed.",
        ]
    )
    return "\n".join(lines) + "\n"


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
    from yoke_cli.config.setup_facts_summary import orientation_lines
    from yoke_core.domain.session_orientation import render_orientation

    if registration_failed:
        required.append(f"WARNING: Session registration failed: {registration_failed}")
        required.append(
            _connected_env_remediation(registration_failed)
            or "Run: yoke sessions identity --json to diagnose registration."
        )
    return render_orientation(
        {
            "session_id": session_id,
            "_yoke_setup_lines": orientation_lines(Path(root)),
            "_yoke_required_lines": required,
        },
        Path(root),
    )


__all__ = [
    "_connected_env_remediation",
    "_render_claude_orientation",
    "_render_codex_orientation",
    "_render_codex_reminder",
    "_requested",
]
