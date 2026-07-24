"""Typed session-lifecycle dispatch consumed by the shared hook runner."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from runtime.harness.hook_runner.session_workspace import export_bound_workspace_for_session
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome
from runtime.harness.hook_runner import session_dispatch_codex_lifecycle as _codex_lifecycle

_register_codex = _codex_lifecycle.register
_session_begin_recovery_command = _codex_lifecycle.recovery_command
_touch = _codex_lifecycle.touch

def _decision(stdout: str = "") -> HookDecision:
    fields = {"stdout": stdout} if stdout else {}
    return HookDecision(outcome=Outcome.AUDIT_ONLY, audit_fields=fields, next=Next.CONTINUE)

def _payload_json(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload)
    except TypeError:
        return "{}"

def _field(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name, "")
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)

def _root_and_db(record: HookContext) -> tuple[str, str]:
    raw = _payload_json(record.payload)
    if record.executor_family == "codex":
        from runtime.harness.codex import codex_hooks_payload as _codex

        root = _codex.resolve_root(raw)
        return root, _codex.resolve_yoke_db(root)

    from runtime.harness.hook_helpers import resolve_yoke_db
    from runtime.harness.hook_runner.target import resolve_hook_script_dir, resolve_target_root

    script_dir = resolve_hook_script_dir()
    root = resolve_target_root(script_dir)
    return root, resolve_yoke_db(script_dir)

def _is_yoke_target(root: str, db_path: str) -> bool:
    try:
        from runtime.harness.hook_runner.target import is_yoke_target

        return is_yoke_target(root, db_path)
    except Exception:
        return bool(root and db_path and Path(db_path).is_file())

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

def _bootstrap_lines(root: str, *, codex: bool) -> list[str]:
    try:
        from runtime.harness.bootstrap import load_spec, render_compact

        spec_path = Path(root) / "runtime" / "harness" / "bootstrap-spec.json"
        extra = ["CODEX.md"] if codex else []
        if spec_path.is_file():
            rendered = render_compact(Path(root), load_spec(spec_path), extra_files=extra)
            if rendered:
                return rendered.splitlines()
    except Exception:
        pass
    fallback = ["Read before editing:"]
    if codex and (Path(root) / "CODEX.md").is_file():
        fallback.append("- CODEX.md")
    return fallback

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

def _end_session_if_empty(
    root: str,
    session_id: str,
    *,
    executor: Optional[str] = None,
    event_source: str = "unknown",
) -> None:
    from runtime.harness.hook_runner.session_end_cleanup import run_session_end_cleanup

    run_session_end_cleanup(
        root, session_id, executor=executor, event_source=event_source,
    )

from runtime.harness.hook_runner.resume_block_dispatch import render as _render_resume_block


def _first_prompt(session_id: str, *, codex: bool) -> bool:
    from runtime.harness.hook_runner.session_dispatch_first_prompt import (
        first_prompt as _first_prompt_impl,
    )

    return _first_prompt_impl(session_id, codex=codex)

def _orientation_base(title: str, session_id: str, root: str, *, codex: bool) -> list[str]:
    lines = [title, "", f"Your Session: {session_id}",
        "Do NOT infer your identity from the active sessions table on the board.", ""]
    lines.extend(_bootstrap_lines(root, codex=codex))
    lines.extend(["", "Recent commits:",
        _git_line(root, ["log", "--oneline", "-3"]) or "(git log unavailable)",
        "", "Current branch:",
        _git_line(root, ["branch", "--show-current"]) or "(branch unavailable)", ""])
    if (Path(root) / ".yoke" / "BOARD.md").is_file():
        lines.append("Board available at .yoke/BOARD.md")
    return lines

def _render_codex_orientation(
    session_id: str, root: str, registration_failed: str, model: str, entrypoint: Optional[str],
) -> str:
    from yoke_core.domain.harness_capability_registry import compact_entrypoint_display, shared_downstream_paths

    lines = _orientation_base(
        "## Yoke Orientation (Codex hook-enhanced)", session_id, root, codex=True,
    )
    if registration_failed:
        remediation = _connected_env_remediation(registration_failed)
        warning = [
            "WARNING: Session registration failed - scheduler will not see this "
            f"session. Run: {_session_begin_recovery_command(session_id, root, model, entrypoint)}",
        ]
        warning += [remediation] if remediation else []
        lines[5:5] = [*warning, ""]
    lines[5:5] = ["Executor: codex", "Mode: hook-enhanced (SessionStart)", f"Root: {root}", ""]
    lines.extend([
        "Safe commands: " + compact_entrypoint_display(),
        "Downstream paths: " + ", ".join(shared_downstream_paths()) + " (derived from shared registry)",
        "Full bootstrap: python3 -m runtime.harness.bootstrap render-full "
        "--spec runtime/harness/bootstrap-spec.json --root " + root,
    ])
    return "\n".join(lines) + "\n"

def _render_codex_reminder(
    session_id: str, root: str, registration_failed: str, model: str, entrypoint: Optional[str],
) -> str:
    from yoke_core.domain.harness_capability_registry import prompt_reminder_lines, shared_downstream_paths
    from yoke_core.domain.main_agent_packet import render_install_advisory_block
    from runtime.harness.codex.codex_hooks_payload import session_marker_path

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
            f"not see this session. Run: {_session_begin_recovery_command(session_id, root, model, entrypoint)}"
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
    session_id: str, root: str, registration_failed: str, executor: str, model: str,
) -> str:
    lines = _orientation_base("## Yoke Orientation", session_id, root, codex=False)
    if registration_failed:
        remediation = _connected_env_remediation(registration_failed)
        warning = ["WARNING: Session registration failed - scheduler will not see this session."]
        warning += [remediation] if remediation else []
        lines[5:5] = [*warning, ""]
    lines[5:5] = [f"Executor: {executor or 'claude-code'}", f"Model: {model or 'unknown'}", f"Root: {root}", ""]
    return "\n".join(lines) + "\n"

def _run_codex_session_start(record: HookContext, root: str) -> str:
    from runtime.harness.codex import codex_hooks_payload as _codex
    from runtime.harness.codex.codex_model import resolve, resolve_entrypoint

    raw = _payload_json(record.payload)
    session_id = _codex.resolve_session_id(raw)
    if not session_id:
        return (
            "## Yoke Orientation (Codex hook-enhanced)\n\n"
            "WARNING: No stable session ID available. Running in degraded mode.\n"
            "Do NOT infer your identity from the active sessions table on the board.\n"
        )
    _codex.write_runtime_cache(session_id, raw)
    os.environ["YOKE_SESSION_ID"] = session_id
    if root:
        export_bound_workspace_for_session(root)
    if _field(record.payload, "source") == "startup" and not _field(record.payload, "transcript_path"):
        return ""
    if not _codex.check_and_arm_marker(_codex.session_marker_path(session_id)):
        return _render_resume_block(root, session_id, "SessionStart")
    model = resolve(_field(record.payload, "model")) or _field(record.payload, "model") or "unknown"
    entrypoint = resolve_entrypoint()
    err = _register_codex(root, session_id, model, entrypoint)
    return _render_codex_orientation(session_id, root, err, model, entrypoint) + \
        _render_resume_block(root, session_id, "SessionStart")

def _run_codex_prompt_submit(record: HookContext, root: str) -> str:
    from runtime.harness.codex import codex_hooks_payload as _codex
    from runtime.harness.codex.codex_model import resolve, resolve_entrypoint
    from runtime.harness.hook_runner import telemetry

    raw = _payload_json(record.payload)
    session_id = _codex.resolve_session_id(raw)
    if not session_id:
        return ""
    source = _field(record.payload, "source") or _codex.read_runtime_cache_field(session_id, "source")
    transcript = _field(record.payload, "transcript_path") or _codex.read_runtime_cache_field(session_id, "transcript_path")
    if source == "startup" and not transcript:
        return ""
    model = resolve(_field(record.payload, "model")) or "unknown"
    entrypoint = None
    err = ""
    if _touch(root, session_id) != 0:
        entrypoint = resolve_entrypoint()
        err = _register_codex(root, session_id, model, entrypoint)
    if not _first_prompt(session_id, codex=True):
        return ""
    telemetry.emit_harness_session_sent_first_user_prompt_submit("", session_id)
    return _render_codex_reminder(session_id, root, err, model, entrypoint)

def _run_claude_session_start(record: HookContext) -> None:
    from runtime.harness.hook_runner import telemetry
    from runtime.harness.hook_runner_register import _register_from_hook

    raw = _payload_json(record.payload)
    session_id = telemetry.resolve_env_init_session_id(raw)
    if not session_id:
        return
    env_file = os.environ.get("CLAUDE_ENV_FILE", "")
    telemetry.persist_session_id_to_env_file(session_id, env_file)
    _register_from_hook(raw, session_id)
    # Defense in depth: pin YOKE_BOUND_WORKSPACE for the writer guard +
    # cross-checkout PreToolUse lint.
    root, _ = _root_and_db(record)
    if root:
        export_bound_workspace_for_session(root, env_file)

def _run_claude_prompt_submit(record: HookContext, root: str) -> str:
    from runtime.harness.hook_runner import telemetry
    from runtime.harness.hook_runner_register import _register_from_hook

    raw = _payload_json(record.payload)
    session_id, canonical = telemetry.resolve_session_id_from_env_and_payload(raw)
    transcript_path = _field(record.payload, "transcript_path")
    err = executor = model = ""
    if canonical:
        err, executor, _provider, model, _entrypoint = _register_from_hook(
            raw, session_id, transcript_path=transcript_path,
        )
    if not _first_prompt(session_id, codex=False):
        return _render_resume_block(root, session_id, "UserPromptSubmit")
    telemetry.emit_harness_session_sent_first_user_prompt_submit("", session_id)
    return _render_claude_orientation(session_id, root, err, executor, model) + \
        _render_resume_block(root, session_id, "UserPromptSubmit")

def _run_stop(record: HookContext, root: str, db_path: str) -> str:
    from runtime.harness.hook_runner import telemetry

    raw = _payload_json(record.payload)
    if record.executor_family == "codex" and _field(record.payload, "stop_hook_active").lower() in {"true", "1"}:
        return "{}\n"
    session_id = telemetry.resolve_direct_session_id(raw)
    if session_id and root and _is_yoke_target(root, db_path):
        _end_session_if_empty(
            root, session_id, executor=record.executor_family,
            event_source=record.event_name,
        )
    return "{}\n" if record.executor_family == "codex" else ""

def evaluate(context: HookContext) -> HookDecision:
    """Dispatch lifecycle side effects and return any harness stdout."""
    try:
        root, db_path = _root_and_db(context)
        if not root or not _is_yoke_target(root, db_path):
            return _decision("{}\n" if context.executor_family == "codex" and context.event_name == "Stop" else "")
        if context.event_name == "SessionStart":
            if context.executor_family == "codex":
                return _decision(_run_codex_session_start(context, root))
            _run_claude_session_start(context)
            return _decision()
        if context.event_name == "UserPromptSubmit":
            if context.executor_family == "codex":
                return _decision(_run_codex_prompt_submit(context, root))
            return _decision(_run_claude_prompt_submit(context, root))
        if context.event_name in {"Stop", "SessionEnd"}:
            return _decision(_run_stop(context, root, db_path))
    except Exception:
        return _decision()
    return _decision()

__all__ = ["evaluate"]
