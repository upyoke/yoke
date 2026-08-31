"""Typed session-lifecycle dispatch consumed by the shared hook runner."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.session_model_facts import SessionModelFacts, model_display

from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.hooks import session_dispatch_codex_lifecycle as _codex_lifecycle
from yoke_core.hooks.resume_block_dispatch import render as _render_resume_block
from yoke_core.hooks.session_dispatch_orientation import (
    _connected_env_remediation,
    _render_claude_orientation,
    _render_codex_orientation,
    _render_codex_reminder,
    _requested,
)

_register_codex = _codex_lifecycle.register
_session_begin_recovery_command = _codex_lifecycle.recovery_command
_touch = _codex_lifecycle.touch  # retained for adapter wiring tests

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
        from yoke_core.hooks import codex_payload as _codex

        root = _codex.resolve_root(raw)
        return root, _codex.resolve_yoke_db(root)

    from yoke_core.hooks.helpers import resolve_yoke_db
    from yoke_core.hooks.target import resolve_hook_script_dir, resolve_target_root

    script_dir = resolve_hook_script_dir()
    if record.executor_family == "cursor":
        from yoke_core.hooks import cursor_payload as _cursor

        # Payload-first root: Cursor names the opened workspace in every
        # payload, which stays correct across mid-session shell cwd drift.
        root = _cursor.resolve_root(raw) or resolve_target_root(script_dir)
        return root, resolve_yoke_db(script_dir)
    root = resolve_target_root(script_dir)
    return root, resolve_yoke_db(script_dir)

def _is_yoke_target(root: str, db_path: str) -> bool:
    try:
        from yoke_core.hooks.target import is_yoke_target

        return is_yoke_target(root, db_path)
    except Exception:
        return bool(root and db_path and Path(db_path).is_file())

def _end_session_if_empty(
    root: str,
    session_id: str,
    *,
    executor: Optional[str] = None,
    event_source: str = "unknown",
) -> None:
    from yoke_core.hooks.session_end_cleanup import run_session_end_cleanup

    run_session_end_cleanup(
        root, session_id, executor=executor, event_source=event_source,
    )

def _first_prompt(session_id: str, *, codex: bool) -> bool:
    from yoke_core.hooks.session_dispatch_first_prompt import (
        first_prompt as _first_prompt_impl,
    )

    return _first_prompt_impl(session_id, codex=codex)

def _codex_model_facts(payload: Any, thread_id: str) -> SessionModelFacts:
    """Resolve Codex's requested ask and its rollout-attested served truth.

    The rollout is keyed by the thread this dispatch already resolved, so
    it is handed over rather than re-derived from the raw payload.
    """
    from yoke_harness.hooks.identity_relay import resolve_model_facts

    block = dict(payload) if isinstance(payload, dict) else {}
    block["thread_id"] = thread_id
    return resolve_model_facts(block, "codex")


def _run_codex_session_start(record: HookContext, root: str) -> str:
    from yoke_core.hooks import codex_payload as _codex
    from yoke_core.hooks.codex_model import resolve_entrypoint

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
    if _field(record.payload, "source") == "startup" and not _field(record.payload, "transcript_path"):
        return ""
    if not _codex.check_and_arm_marker(_codex.session_marker_path(session_id)):
        return _render_resume_block(root, session_id, "SessionStart")
    facts = _codex_model_facts(record.payload, session_id)
    entrypoint = resolve_entrypoint()
    err = _register_codex(root, session_id, facts, entrypoint)
    return _render_codex_orientation(session_id, root, err, facts, entrypoint) + \
        _render_resume_block(root, session_id, "SessionStart")

def _run_codex_prompt_submit(record: HookContext, root: str) -> str:
    from yoke_core.hooks import codex_payload as _codex
    from yoke_core.hooks.codex_model import resolve_entrypoint
    from yoke_core.hooks import telemetry

    raw = _payload_json(record.payload)
    session_id = _codex.resolve_session_id(raw)
    if not session_id:
        return ""
    source = _field(record.payload, "source") or _codex.read_runtime_cache_field(session_id, "source")
    transcript = _field(record.payload, "transcript_path") or _codex.read_runtime_cache_field(session_id, "transcript_path")
    if source == "startup" and not transcript:
        return ""
    if not _first_prompt(session_id, codex=True):
        return ""
    # First prompt may safety-net register. Do not heartbeat: a wake-
    # injected prompt is not the session's own activity.
    facts = _codex_model_facts(record.payload, session_id)
    entrypoint = resolve_entrypoint()
    err = _register_codex(root, session_id, facts, entrypoint)
    telemetry.emit_harness_session_sent_first_user_prompt_submit("", session_id)
    return _render_codex_reminder(session_id, root, err, facts, entrypoint)

def _run_claude_session_start(record: HookContext) -> None:
    from yoke_core.hooks import telemetry
    from yoke_core.hooks.registration import _register_from_hook

    raw = _payload_json(record.payload)
    session_id = telemetry.resolve_env_init_session_id(raw)
    if not session_id:
        return
    env_file = os.environ.get("CLAUDE_ENV_FILE", "")
    telemetry.persist_session_id_to_env_file(session_id, env_file)
    _register_from_hook(raw, session_id)

def _run_claude_prompt_submit(record: HookContext, root: str) -> str:
    from yoke_core.hooks import telemetry
    from yoke_core.hooks.registration import _register_from_hook

    raw = _payload_json(record.payload)
    session_id, canonical = telemetry.resolve_session_id_from_env_and_payload(raw)
    transcript_path = _field(record.payload, "transcript_path")
    err = executor = ""
    facts = SessionModelFacts()
    if canonical:
        err, executor, _provider, facts, _entrypoint = _register_from_hook(
            raw, session_id, transcript_path=transcript_path,
        )
    if not _first_prompt(session_id, codex=False):
        return _render_resume_block(root, session_id, "UserPromptSubmit")
    telemetry.emit_harness_session_sent_first_user_prompt_submit("", session_id)
    return _render_claude_orientation(session_id, root, err, executor, facts) + \
        _render_resume_block(root, session_id, "UserPromptSubmit")

def _run_stop(record: HookContext, root: str, db_path: str) -> str:
    from yoke_core.hooks import telemetry

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
            from yoke_core.engines.main_checkout_sync import sync_main_checkout_at_session_start
            sync_main_checkout_at_session_start(root)
            if context.executor_family == "codex":
                return _decision(_run_codex_session_start(context, root))
            if context.executor_family == "cursor":
                from yoke_core.hooks import session_dispatch_cursor as _cursor_dispatch

                return _decision(_cursor_dispatch.run_session_start(context, root))
            _run_claude_session_start(context)
            return _decision()
        if context.event_name == "UserPromptSubmit":
            if context.executor_family == "codex":
                return _decision(_run_codex_prompt_submit(context, root))
            if context.executor_family == "cursor":
                from yoke_core.hooks import session_dispatch_cursor as _cursor_dispatch

                return _decision(_cursor_dispatch.run_prompt_submit(context, root))
            return _decision(_run_claude_prompt_submit(context, root))
        if context.event_name in {"Stop", "SessionEnd"}:
            return _decision(_run_stop(context, root, db_path))
    except Exception:
        return _decision()
    return _decision()

__all__ = ["evaluate"]
