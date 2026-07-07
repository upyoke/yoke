"""PreToolUse hook event engine.

Extracted from the inline Python heredoc in ``observe-tool-pre.sh`` so the
PreToolUse hot-path lives in Python with shell surviving only as the hook
launcher. The PostToolUse / PostToolUseFailure engine lives in
:mod:`yoke_core.domain.observe`; this module owns the lightweight
``HarnessToolCallStarted`` emission that :mod:`yoke_core.domain.observe`
later joins on to compute ``duration_ms``.

Responsibilities:

* Parse the PreToolUse JSON payload.
* Build a minimal ``HarnessToolCallStarted`` envelope (``tool_use_id``,
  ``tool_name``, ``session_id``, optional ``turn_id`` / ``cwd``, fixed
  ``hook_event_name=PreToolUse``).
* Insert the event via :func:`yoke_core.domain.observe.insert_event` so the
  post-hook and pre-hook share a single writer.

Typed runner contract ( spec):
    ``evaluate(record: HookContext) -> HookDecision``

This module is telemetry-only: ``evaluate`` always returns
``HookDecision(outcome=NOOP, next=CONTINUE)`` so the chain advances. All
failures degrade silently (returning the same NOOP) so the PreToolUse
hook cannot block tool execution.

The CLI ``__main__`` form is preserved for the registered hook entry
(``python3 -m yoke_core.domain.observe_pre``); ``--db`` is a legacy
connection-token override for tests.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from yoke_core.domain.observe import insert_event
from yoke_core.domain.observe_db import (
    connect_observe_db,
    should_write_observe_event,
)
from runtime.harness.hook_runner.types import (
    HookContext,
    HookDecision,
    Next,
    Outcome,
)


def _nonempty_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _payload_agent_type(data: Dict[str, Any]) -> str:
    return _nonempty_str(data.get("agent_type"))


def parse_pre_event(
    data: Dict[str, Any],
    *,
    fallback_cwd: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Parse a PreToolUse JSON payload into a ``HarnessToolCallStarted`` envelope.

    Returns ``None`` when the event should be silently dropped (missing
    ``tool_use_id`` — matches the original shell behavior).
    """
    if not isinstance(data, dict):
        return None

    tool_use_id = data.get("tool_use_id") or None
    if not tool_use_id:
        return None

    tool_name = data.get("tool_name") or None
    session_id = data.get("session_id") or "unknown"
    turn_id = data.get("turn_id") or None
    agent_type = _payload_agent_type(data)
    cwd = (
        _nonempty_str(data.get("cwd"))
        or _nonempty_str(data.get("project_dir"))
        or _nonempty_str(fallback_cwd)
    )

    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    event_time = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    # Shape matches what insert_event() expects. Fields the post-hook uses
    # (duration_ms, exit_code, anomaly_flags, agent, item_id, task_num) are
    # intentionally omitted — insert_event reads them via .get() and writes
    # NULL when absent. The full dict is stored verbatim as the envelope JSON.
    envelope: Dict[str, Any] = {
        "event_id": event_id,
        "event_name": "HarnessToolCallStarted",
        "event_outcome": "started",
        "severity": "INFO",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "hook_event_name": "PreToolUse",
        "event_time": event_time,
    }
    if turn_id:
        envelope["turn_id"] = turn_id
    if agent_type:
        envelope["agent"] = agent_type
    if cwd:
        envelope["cwd"] = cwd
    # Carry the invoked tool body (Bash command / Monitor watcher
    # invocation / Edit-Write file path) on the Started event so consumers
    # that need to correlate the invocation BEFORE it exits can read it
    # without waiting for HarnessToolCallCompleted. Mirror the truncation
    # cap that observe_event_emission uses for the completion envelope.
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str) and command:
            envelope["context"] = {"detail": {"tool_input": command[:2048]}}
        else:
            file_path = tool_input.get("file_path")
            if isinstance(file_path, str) and file_path:
                envelope["context"] = {"detail": {"tool_input": file_path}}
    if agent_type:
        detail = envelope.setdefault("context", {}).setdefault("detail", {})
        detail["actor_role"] = agent_type
    return envelope


def write_pre_event(db_path: Optional[str], envelope: Dict[str, Any]) -> bool:
    """Insert a parsed pre-event envelope into ``events``.

    Silently no-ops on any error — PreToolUse hooks must never block.
    """
    try:
        conn = connect_observe_db(db_path)
        if conn is None:
            return False
        try:
            insert_event(conn, envelope)
        finally:
            conn.close()
    except Exception:
        return False
    return True


def _try_refresh_session_model(data: Dict[str, Any], db_path: str) -> None:
    """Best-effort upgrade of a placeholder ``harness_sessions.model``.

    PreToolUse is the earliest hook that fires *after* the LLM has begun
    generating a response, so the transcript's latest assistant-message
    ``model`` field is already present. For surfaces whose SessionStart
    payload omits ``model`` (notably VS Code — see
    runtime/harness/hook_helpers.detect_model docstring), this is the
    turn-1 correction point. Without it, VS Code sessions stay on
    ``model=unknown`` until the user sends a second prompt and
    SessionStart reactivation's transcript walk catches up.
    """
    session_id = data.get("session_id")
    transcript_path = data.get("transcript_path")
    if not isinstance(session_id, str) or not isinstance(transcript_path, str):
        return
    try:
        from runtime.harness.hook_runner.telemetry import (
            refresh_session_model_if_placeholder,
        )
        refresh_session_model_if_placeholder(
            db_path, session_id, transcript_path,
            hook_source="PreToolUse",
        )
    except Exception:
        pass


def _try_check_session_main_drift(data: Dict[str, Any], db_path: str) -> None:
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    repo_path = data.get("cwd") or data.get("project_dir")
    try:
        from yoke_core.domain.session_main_drift import (
            check_drift,
            format_advisory,
        )
        advisory = check_drift(
            session_id,
            db_path=db_path,
            repo_path=repo_path if isinstance(repo_path, str) else None,
        )
        if advisory is not None:
            print(format_advisory(advisory), file=sys.stderr)
    except Exception:
        pass


def process_stdin(raw: str, db_path: Optional[str]) -> bool:
    """Parse ``raw`` JSON, build the envelope, and write it.

    Returns ``True`` when an event was emitted, ``False`` otherwise. Exposed
    so tests can exercise the end-to-end path without spawning a subprocess.
    """
    if not raw or not raw.strip():
        return False
    try:
        data = json.loads(raw)
    except Exception:
        return False

    envelope = parse_pre_event(data)
    if envelope is None:
        return False

    if not should_write_observe_event(db_path):
        return False

    if db_path:
        _try_refresh_session_model(data, db_path)
        _try_check_session_main_drift(data, db_path)
    return write_pre_event(db_path, envelope)


def _process_payload(
    payload: Dict[str, Any],
    db_path: Optional[str],
    *,
    fallback_cwd: Optional[str] = None,
) -> bool:
    """Same as :func:`process_stdin` but skips the JSON re-parse.

    The typed ``evaluate`` entry already has the parsed payload on
    ``record.payload``; calling :func:`process_stdin` would force a
    json.dumps round-trip just to re-parse it. This helper preserves the
    failure-swallowing contract while reusing the existing emission path.
    """
    if not isinstance(payload, dict):
        return False
    envelope = parse_pre_event(payload, fallback_cwd=fallback_cwd)
    if envelope is None:
        return False
    if not should_write_observe_event(db_path):
        return False
    if db_path:
        _try_refresh_session_model(payload, db_path)
        _try_check_session_main_drift(payload, db_path)
    return write_pre_event(db_path, envelope)


def evaluate(record: HookContext) -> HookDecision:
    """Run the observe-pre telemetry tail against a typed :class:`HookContext`.

    Always returns ``HookDecision(outcome=NOOP, next=CONTINUE)`` —
    PreToolUse telemetry must never block tool execution. All failures
    are swallowed.
    """
    try:
        payload = record.payload if isinstance(record.payload, dict) else {}
        db_path = _resolve_db_fallback()
        if payload and db_path:
            _process_payload(payload, db_path, fallback_cwd=record.cwd)
    except Exception:
        pass
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def _resolve_db_fallback() -> Optional[str]:
    """Resolve the events DB path when ``--db`` is not supplied.

    Delegates to :mod:`yoke_core.domain.db_helpers` so the CLI honors the
    ``YOKE_DB`` env and repo walk-up without forcing every hook caller to
    thread ``--db`` explicitly. All failures degrade to ``None``; PreToolUse
    hooks must never block tool execution.
    """
    try:
        from yoke_core.domain.db_helpers import resolve_db_path

        return resolve_db_path()
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Emit HarnessToolCallStarted event from a PreToolUse hook payload",
    )
    parser.add_argument("--db", default=None, help="Legacy DB token override")
    args = parser.parse_args()

    try:
        raw = sys.stdin.read()
    except Exception:
        return 0

    db_path = args.db or _resolve_db_fallback()
    try:
        process_stdin(raw, db_path)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
