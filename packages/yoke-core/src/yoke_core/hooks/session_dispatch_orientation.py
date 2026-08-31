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
import subprocess
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


def _git_line(root: str, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    return result.stdout.rstrip("\n").strip() if result.returncode == 0 else ""

def _bootstrap_lines(root: str, *, extra_files: list[str]) -> list[str]:
    try:
        from yoke_core.hooks.bootstrap import load_spec, render_compact

        spec_path = Path(root) / "runtime" / "harness" / "bootstrap-spec.json"
        if spec_path.is_file():
            rendered = render_compact(Path(root), load_spec(spec_path), extra_files=extra_files)
            if rendered:
                return rendered.splitlines()
    except Exception:
        pass
    fallback = ["Read before editing:"]
    for name in extra_files:
        if (Path(root) / name).is_file():
            fallback.append(f"- {name}")
    return fallback


def _orientation_base(
    title: str, session_id: str, root: str, *, extra_files: list[str]
) -> list[str]:
    lines = [title, "", f"Your Session: {session_id}",
        "Do NOT infer your identity from the active sessions table on the board.", ""]
    lines.extend(_bootstrap_lines(root, extra_files=extra_files))
    lines.extend(["", "Recent commits:",
        _git_line(root, ["log", "--oneline", "-3"]) or "(git log unavailable)",
        "", "Current branch:",
        _git_line(root, ["branch", "--show-current"]) or "(branch unavailable)", ""])
    if (Path(root) / ".yoke" / "BOARD.md").is_file():
        lines.append("Board available at .yoke/BOARD.md")
    return lines

def _render_codex_orientation(
    session_id: str, root: str, registration_failed: str,
    facts: SessionModelFacts, entrypoint: Optional[str],
) -> str:
    from yoke_core.domain.harness_capability_registry import compact_entrypoint_display, shared_downstream_paths

    lines = _orientation_base(
        "## Yoke Orientation (Codex hook-enhanced)", session_id, root,
        extra_files=["CODEX.md"],
    )
    if registration_failed:
        remediation = _connected_env_remediation(registration_failed)
        warning = [
            "WARNING: Session registration failed - scheduler will not see this "
            f"session. Reason: {registration_failed}. "
            f"Run: {_session_begin_recovery_command(session_id, root, _requested(facts), entrypoint)}",
        ]
        warning += [remediation] if remediation else []
        lines[5:5] = [*warning, ""]
    lines[5:5] = ["Executor: codex", "Mode: hook-enhanced (SessionStart)", f"Root: {root}", ""]
    lines.extend([
        "Safe commands: " + compact_entrypoint_display(),
        "Downstream paths: " + ", ".join(shared_downstream_paths()) + " (derived from shared registry)",
        "Full bootstrap: python3 -m yoke_core.hooks.bootstrap render-full "
        "--spec runtime/harness/bootstrap-spec.json --root " + root,
    ])
    return "\n".join(lines) + "\n"

def _render_codex_reminder(
    session_id: str, root: str, registration_failed: str,
    facts: SessionModelFacts, entrypoint: Optional[str],
) -> str:
    from yoke_core.domain.harness_capability_registry import prompt_reminder_lines, shared_downstream_paths
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
    lines.extend([
        "  /yoke help   -- show available commands",
        "",
        "Local terminal helpers (no harness session required):",
        "  yoke board art variant create --ascii|--mixed|--image PATH",
        "",
        "Downstream paths: " + ", ".join(shared_downstream_paths()) + " (from shared registry)",
        "",
        "Prefer /yoke commands and the yoke CLI.",
        "Do not call internal scripts directly unless instructed.",
    ])
    return "\n".join(lines) + "\n"

def _render_claude_orientation(
    session_id: str, root: str, registration_failed: str, executor: str,
    facts: SessionModelFacts,
) -> str:
    lines = _orientation_base("## Yoke Orientation", session_id, root, extra_files=[])
    if registration_failed:
        remediation = _connected_env_remediation(registration_failed)
        warning = [
            "WARNING: Session registration failed - scheduler will not see "
            f"this session. Reason: {registration_failed}",
        ]
        warning += [remediation] if remediation else []
        lines[5:5] = [*warning, ""]
    lines[5:5] = [f"Executor: {executor or 'claude-code'}",
        f"Model: {model_display(facts)}", f"Root: {root}", ""]
    return "\n".join(lines) + "\n"


__all__ = [
    "_bootstrap_lines",
    "_connected_env_remediation",
    "_git_line",
    "_orientation_base",
    "_render_claude_orientation",
    "_render_codex_orientation",
    "_render_codex_reminder",
    "_requested",
]
